"""Identify the top rivals outranking a single app on its own core keywords.

Pure-SERP approach: tokenize the app's title/subtitle/keywords (LLM in
conversation layer), query iTunes Search top-200 per token, collect all rivals
ranked higher than self, aggregate across tokens, score by
popularity-weighted position differential, hard-filter on genre + density,
then let Claude do a batched LLM relevance pass on name + description.

The authoritative workflow lives in skills/competitor-research/SKILL.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
import sys
import time
from typing import Any

import requests

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import appmate_config  # noqa: E402
from keyword_local import lookup_popularity as _kw_lookup_popularity  # noqa: E402

# --- Network / SERP ---
SERP_LIMIT = 200
SERP_TIMEOUT_S = 20
SERP_RETRIES = 4

# --- Filtering ---
MIN_OUTRANK_COUNT = 3
MAX_CANDIDATES_BEFORE_LLM = 25

# --- LLM input ---
DESCRIPTION_TRUNCATE = 200

# --- Reporting ---
TOP_N_RIVALS = 10
MIN_RIVALS_FOR_REPORT = 3
TOP_K_KEYWORDS_PER_CARD = 3

# --- Scoring ---
SELF_NORANK_CEILING = 200

# --- Cache TTL ---
SERP_CACHE_TTL_DAYS = 7

# --- Paths (overridable in tests) ---
# appmate_config exposes DATA_DIR as a module-level constant and data_path(name)
# as a helper. There is NO data_dir() function — using the constant directly.
APPS_FULL_PATH = appmate_config.DATA_DIR / "apps_full.json"
SALES_CACHE_PATH = appmate_config.DATA_DIR / "sales_cache.json"
ITUNES_LOOKUP_CACHE_PATH = appmate_config.DATA_DIR / "itunes_lookup_cache.json"
SERP_DETAILS_CACHE_PATH = appmate_config.DATA_DIR / "serp_details_cache.json"
OUTPUT_DIR = appmate_config.DATA_DIR

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"


def _load_json_cache(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json_cache(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _is_fresh(iso_ts: str | None, max_age_days: int) -> bool:
    """True iff iso_ts parses and is within max_age_days of now."""
    if not iso_ts:
        return False
    try:
        # Accept both "...Z" and "...+00:00" forms
        fetched = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) - fetched < dt.timedelta(days=max_age_days)


def fetch_primary_genre_id(itunes_id: str, country: str) -> int:
    """Return the app's primaryGenreId from iTunes Lookup, cached forever.

    Raises RuntimeError if Lookup returns no result (app pulled / wrong id).
    """
    cache = _load_json_cache(ITUNES_LOOKUP_CACHE_PATH)
    key = f"{itunes_id}|{country.lower()}"
    if key in cache and "primaryGenreId" in cache[key]:
        return int(cache[key]["primaryGenreId"])

    params = {"id": str(itunes_id), "country": country.upper()}
    last_exc: Exception | None = None
    last_status: int | None = None
    for attempt in range(SERP_RETRIES):
        try:
            r = requests.get(ITUNES_LOOKUP_URL, params=params, timeout=SERP_TIMEOUT_S)
            if r.status_code in (429, 502, 503, 504):
                last_status = r.status_code
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                raise RuntimeError(
                    f"iTunes Lookup returned no result for id={itunes_id} country={country}"
                )
            genre_id = int(results[0]["primaryGenreId"])
            cache[key] = {
                "primaryGenreId": genre_id,
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            _save_json_cache(ITUNES_LOOKUP_CACHE_PATH, cache)
            return genre_id
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc is not None:
        detail = f"{type(last_exc).__name__}: {last_exc}"
    elif last_status is not None:
        detail = f"HTTP {last_status} (rate limited / server error)"
    else:
        detail = "unknown error"
    raise RuntimeError(f"iTunes Lookup failed after {SERP_RETRIES} retries: {detail}")


from aso_optimize_v2 import find_app, slugify  # noqa: E402
from feature_ideate import pick_primary_market  # noqa: E402
# count_downloads_in_window is NOT exposed by feature_ideate (the counting
# logic is inline inside pick_primary_market). We define it locally below.


def _is_install_ptid(ptid: str) -> bool:
    """Same install/IAP/update filter used by feature_ideate.pick_primary_market."""
    if not ptid:
        return False
    if ptid.startswith("IA") or ptid.startswith("ITA"):
        return False  # IAP
    if ptid.startswith("7"):
        return False  # update
    return True


def count_downloads_in_window(
    sales_cache: dict[str, list[dict[str, str]]],
    app_id: str,
    country: str,
    today: dt.date,
    window_days: int = 30,
) -> int:
    """Sum installs (excluding IAPs and updates) for one app in one country
    over the trailing `window_days`. Pure function; mirrors the install filter
    used by feature_ideate.pick_primary_market for consistency."""
    cutoff = today - dt.timedelta(days=window_days)
    total = 0
    for date_str, rows in (sales_cache or {}).items():
        if not isinstance(rows, list):
            continue
        try:
            day = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if day < cutoff or day > today:
            continue
        for r in rows:
            if str(r.get("Apple Identifier")) != str(app_id):
                continue
            if r.get("Country Code") != country:
                continue
            if not _is_install_ptid(r.get("Product Type Identifier", "")):
                continue
            try:
                total += int(r.get("Units", 0) or 0)
            except (TypeError, ValueError):
                pass
    return total


def _pick_locale_block(app: dict[str, Any], locale: str) -> dict[str, Any]:
    """Find the localization dict for the chosen locale, with sensible fallbacks."""
    app_info_locs = (app.get("appInfo") or {}).get("localizations") or []
    versions = app.get("versions") or []
    ver_locs = versions[0].get("localizations", []) if versions else []

    name_block = next(
        (loc for loc in app_info_locs if loc.get("locale") == locale),
        app_info_locs[0] if app_info_locs else {},
    )
    kw_block = next(
        (loc for loc in ver_locs if loc.get("locale") == locale),
        ver_locs[0] if ver_locs else {},
    )
    return {
        "title": name_block.get("name", "") or "",
        "subtitle": name_block.get("subtitle", "") or "",
        "keywords": kw_block.get("keywords", "") or "",
    }


def _platform_of(app: dict[str, Any]) -> str:
    versions = app.get("versions") or []
    return versions[0].get("attributes", {}).get("platform", "IOS") if versions else "IOS"


# Country → preferred locale prefix (most common ASO target locales).
# Used by _country_to_locale to pick the localization matching the chosen market.
COUNTRY_TO_LANG_PREFIX: dict[str, tuple[str, ...]] = {
    "US": ("en",), "GB": ("en",), "AU": ("en",), "CA": ("en", "fr"),
    "CN": ("zh-Hans", "zh"), "HK": ("zh-Hant", "zh"), "TW": ("zh-Hant", "zh"),
    "JP": ("ja",), "KR": ("ko",),
    "DE": ("de",), "FR": ("fr",), "ES": ("es",), "IT": ("it",), "NL": ("nl",),
    "BR": ("pt-BR", "pt"), "PT": ("pt-PT", "pt"),
    "RU": ("ru",), "MX": ("es-MX", "es"),
    "SE": ("sv",), "TH": ("th",), "VN": ("vi",), "TR": ("tr",), "PL": ("pl",),
    "ID": ("id",), "IN": ("en", "hi"),
}


def _country_to_locale(country: str, app: dict[str, Any]) -> str:
    """Pick the app localization locale most relevant to the chosen market.

    Resolution order:
      1. App localization whose locale ends with -<country> (e.g. en-US for US).
      2. App localization matching the country's preferred language prefix.
      3. App's `primaryLocale`.
      4. First app localization.
      5. "en-US".
    """
    country_up = (country or "").upper()
    locs = (app.get("appInfo") or {}).get("localizations") or []
    available = [(loc.get("locale") or "") for loc in locs if loc.get("locale")]

    # 1. Exact country suffix match (e.g. en-US for US)
    target = f"-{country_up}"
    for loc in available:
        if loc.upper().endswith(target):
            return loc

    # 2. Language prefix match
    for prefix in COUNTRY_TO_LANG_PREFIX.get(country_up, ()):
        for loc in available:
            if loc.startswith(prefix):
                return loc

    # 3. primaryLocale (use it even if not in localizations)
    primary = (app.get("core") or {}).get("primaryLocale") or ""
    if primary:
        return primary

    # 4. First localization
    if available:
        return available[0]

    # 5. Final fallback
    return "en-US"


def build_phase_a(app: dict[str, Any], sales_cache: dict[str, Any],
                  today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    market = pick_primary_market(app, sales_cache, today=today)
    locale = _country_to_locale(market, app)
    raw = _pick_locale_block(app, locale)
    downloads = count_downloads_in_window(
        sales_cache, app_id=str(app.get("id", "")), country=market,
        today=today, window_days=30,
    )
    itunes_id = str(app.get("id", ""))
    genre_id = fetch_primary_genre_id(itunes_id, market)
    return {
        "app": (app.get("core") or {}).get("name", ""),
        "app_id": itunes_id,
        "bundle_id": (app.get("core") or {}).get("bundleId", ""),
        "platform": _platform_of(app),
        "market": market,
        "primary_genre_id": genre_id,
        "locale": locale,
        "downloads_30d_in_market": downloads,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "raw": raw,
    }


def _phase_path(prefix: str, app_name: str, country: str) -> pathlib.Path:
    slug = slugify(app_name, country)
    return OUTPUT_DIR / f"phase_{prefix}_competitors_{slug}.json"


def _final_path(app_name: str, country: str) -> pathlib.Path:
    slug = slugify(app_name, country)
    return OUTPUT_DIR / f"competitors_{slug}.json"


def _write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_analyze(query: str) -> int:
    appmate_config.require_credentials_or_exit()
    if not APPS_FULL_PATH.exists():
        print(f"ERROR: {APPS_FULL_PATH} not found. Run /appmate-setup first.",
              file=sys.stderr)
        return 2
    apps_data = json.loads(APPS_FULL_PATH.read_text())
    apps = apps_data.get("apps") if isinstance(apps_data, dict) else apps_data
    app = find_app(query, apps)
    if app is None:
        print(f"ERROR: app not found for query '{query}'", file=sys.stderr)
        return 2

    sales_cache = (json.loads(SALES_CACHE_PATH.read_text())
                   if SALES_CACHE_PATH.exists() else {})
    phase_a = build_phase_a(app, sales_cache)
    out = _phase_path("a", phase_a["app"], phase_a["market"])
    _write_json(out, phase_a)
    print(f"wrote {out}")
    return 0


from aso_report import ITUNES_BASE  # noqa: E402  (existing iTunes Search endpoint)


def rank_keyword_with_details(
    keyword: str, country: str, entity: str = "software",
) -> list[dict[str, Any]]:
    """iTunes Search top-200 for one keyword, full per-entry metadata, cached.

    Returns a list of dicts sorted by rank_in_serp ascending. Each dict:
        {itunes_id, bundle_id, name, primary_genre_id, rating, review_count,
         description, rank_in_serp}
    On error after retries, returns an empty list (keyword is skipped).
    """
    cache = _load_json_cache(SERP_DETAILS_CACHE_PATH)
    key = f"{entity}|{country.lower()}|{keyword}"
    cached = cache.get(key)
    if (cached
            and cached.get("entries") is not None
            and "_error" not in cached
            and _is_fresh(cached.get("fetched_at"), SERP_CACHE_TTL_DAYS)):
        return cached["entries"]

    params = {"term": keyword, "country": country.upper(),
              "entity": entity, "limit": SERP_LIMIT}
    last_exc: Exception | None = None
    last_status: int | None = None
    for attempt in range(SERP_RETRIES):
        try:
            r = requests.get(ITUNES_BASE, params=params, timeout=SERP_TIMEOUT_S)
            if r.status_code in (429, 502, 503, 504):
                last_status = r.status_code
                time.sleep(1.5 * (attempt + 1))
                continue
            if not r.ok:
                cache[key] = {"_error": f"http_{r.status_code}", "entries": []}
                _save_json_cache(SERP_DETAILS_CACHE_PATH, cache)
                return []
            raw = r.json().get("results", [])
            entries: list[dict[str, Any]] = []
            for i, app in enumerate(raw, 1):
                tid = app.get("trackId")
                if tid is None:
                    continue
                entries.append({
                    "itunes_id": str(tid),
                    "bundle_id": app.get("bundleId", "") or "",
                    "name": app.get("trackName", "") or "",
                    "primary_genre_id": int(app.get("primaryGenreId") or 0),
                    "rating": float(app.get("averageUserRating") or 0.0),
                    "review_count": int(app.get("userRatingCount") or 0),
                    "description": app.get("description", "") or "",
                    "rank_in_serp": i,
                })
            cache[key] = {
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "entries": entries,
            }
            _save_json_cache(SERP_DETAILS_CACHE_PATH, cache)
            return entries
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc is not None:
        err = f"{type(last_exc).__name__}"
    elif last_status is not None:
        err = f"http_{last_status}"
    else:
        err = "unknown"
    cache[key] = {"_error": err, "entries": []}
    _save_json_cache(SERP_DETAILS_CACHE_PATH, cache)
    return []


def collect_outrankers_for_token(
    serp: list[dict[str, Any]], self_bundle_id: str,
) -> dict[str, Any]:
    """Find self's rank in this SERP and the rivals ranked strictly above it."""
    if not serp:
        return {"self_rank": None, "outrankers": []}
    self_rank: int | None = None
    for entry in serp:
        if entry.get("bundle_id") == self_bundle_id:
            self_rank = entry.get("rank_in_serp")
            break
    ceiling = self_rank if self_rank is not None else SELF_NORANK_CEILING
    outrankers = [e for e in serp if e.get("rank_in_serp", SELF_NORANK_CEILING + 1) < ceiling
                  and e.get("bundle_id") != self_bundle_id]
    return {"self_rank": self_rank, "outrankers": outrankers}


def aggregate_rivals(per_token: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine per-token outranker lists into one record per unique rival.

    per_token[keyword] = {self_rank, outrankers: [serp_entry, ...], popularity}

    Returns a list of rival dicts (unsorted; caller scores + sorts).
    """
    accum: dict[str, dict[str, Any]] = {}
    for keyword, payload in per_token.items():
        self_rank = payload.get("self_rank")
        self_rank_norm = self_rank if self_rank is not None else SELF_NORANK_CEILING
        popularity = int(payload.get("popularity") or 1)
        for entry in payload.get("outrankers", []):
            rid = entry.get("itunes_id")
            if not rid:
                continue
            diff = self_rank_norm - int(entry.get("rank_in_serp", SELF_NORANK_CEILING))
            if diff <= 0:
                continue  # strict outrank only
            rival = accum.setdefault(rid, {
                "itunes_id": rid,
                "bundle_id": entry.get("bundle_id", ""),
                "name": entry.get("name", ""),
                "primary_genre_id": entry.get("primary_genre_id", 0),
                "rating": entry.get("rating", 0.0),
                "review_count": entry.get("review_count", 0),
                "description_short": (entry.get("description") or "")[:DESCRIPTION_TRUNCATE],
                "outranked_keywords": [],
            })
            rival["outranked_keywords"].append({
                "keyword": keyword,
                "self_rank": self_rank_norm,
                "rival_rank": int(entry.get("rank_in_serp", SELF_NORANK_CEILING)),
                "diff": diff,
                "popularity": popularity,
            })

    for rival in accum.values():
        rival["outrank_count"] = len(rival["outranked_keywords"])
        diffs = [k["diff"] for k in rival["outranked_keywords"]]
        rival["avg_rank_diff"] = statistics.mean(diffs) if diffs else 0
        rival["threat_score"] = sum(k["popularity"] * k["diff"]
                                    for k in rival["outranked_keywords"])
    return list(accum.values())


def score_threat(rival: dict[str, Any]) -> int:
    """Threat score = sum over outranked_keywords of (popularity * diff).

    Pure function; kept separate from aggregate_rivals so the formula has
    an independent test and any refactor that touches it shows up here.
    """
    return sum(int(k.get("popularity", 0)) * int(k.get("diff", 0))
               for k in rival.get("outranked_keywords", []))


def filter_by_genre_and_density(
    rivals: list[dict[str, Any]], self_genre_id: int,
) -> list[dict[str, Any]]:
    """Apply spec §6.5: same primary_genre_id + outrank_count >= MIN_OUTRANK_COUNT.

    Sorts the survivors by threat_score desc and truncates to
    MAX_CANDIDATES_BEFORE_LLM. Idempotent: calling twice gives the same result.
    """
    keep = [r for r in rivals
            if r.get("primary_genre_id") == self_genre_id
            and r.get("outrank_count", 0) >= MIN_OUTRANK_COUNT]
    keep.sort(key=lambda r: r.get("threat_score", 0), reverse=True)
    return keep[:MAX_CANDIDATES_BEFORE_LLM]


def _lookup_popularity(keyword: str, region: str) -> int:
    """Tiny wrapper so tests can monkeypatch a single symbol.

    keyword_local.lookup_popularity returns a dict shaped like
        {"keyword", "store", "popularity", "difficulty", ...}
    We extract the integer popularity (1-99). On any failure, return 1
    (neutral weight) so scoring continues — popularity 1 means a contribution
    of just `diff` per outranked keyword, which is small but not zero.
    """
    try:
        row = _kw_lookup_popularity(keyword, region)
        if not isinstance(row, dict):
            return 1
        pop = row.get("popularity")
        return int(pop) if pop is not None else 1
    except Exception:  # noqa: BLE001
        return 1


def build_phase_b(phase_a: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    self_bundle = phase_a.get("bundle_id", "")
    country = phase_a.get("market", "US")
    region = country.lower()
    self_genre_id = int(phase_a.get("primary_genre_id") or 0)

    self_ranks: dict[str, int | None] = {}
    per_token: dict[str, dict[str, Any]] = {}
    for tok in tokens:
        serp = rank_keyword_with_details(tok, country=country)
        bundle_view = collect_outrankers_for_token(serp, self_bundle_id=self_bundle)
        self_ranks[tok] = bundle_view["self_rank"]
        per_token[tok] = {
            "self_rank": bundle_view["self_rank"],
            "outrankers": bundle_view["outrankers"],
            "popularity": _lookup_popularity(tok, region),
        }

    rivals = aggregate_rivals(per_token)
    candidates = filter_by_genre_and_density(rivals, self_genre_id=self_genre_id)

    return {
        "app": phase_a.get("app", ""),
        "app_id": phase_a.get("app_id", ""),
        "bundle_id": self_bundle,
        "market": country,
        "primary_genre_id": self_genre_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tokens": tokens,
        "self_ranks": self_ranks,
        "candidates": candidates,
    }


def cmd_rank(query: str, tokens: list[str]) -> int:
    appmate_config.require_credentials_or_exit()
    # Locate phase_a by scanning OUTPUT_DIR for phase_a_competitors_*.json
    # whose `app` matches the query (or itunes_id / bundle).
    phase_a = _load_phase_a_for_query(query)
    if phase_a is None:
        print(f"ERROR: no phase_a file for '{query}'. "
              f"Run analyze first.", file=sys.stderr)
        return 2
    if not tokens:
        print("ERROR: no tokens provided. Pass --tokens 'a,b,c'", file=sys.stderr)
        return 2
    phase_b = build_phase_b(phase_a, tokens)
    out_path = _phase_path("b", phase_b["app"], phase_b["market"])
    _write_json(out_path, phase_b)
    print(f"wrote {out_path}")
    return 0


def _load_phase_a_for_query(query: str) -> dict[str, Any] | None:
    """Find the most recent phase_a whose app name or id/bundle matches query."""
    candidates = sorted(OUTPUT_DIR.glob("phase_a_competitors_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    q = query.lower()
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if q in (str(data.get("app", "")).lower(),
                 str(data.get("app_id", "")).lower(),
                 str(data.get("bundle_id", "")).lower()):
            return data
        # also accept fuzzy match (substring of name)
        if q in str(data.get("app", "")).lower():
            return data
    return None


def cmd_show_a(query: str) -> int:
    data = _load_phase_a_for_query(query)
    if data is None:
        print(f"ERROR: no phase_a file for '{query}'", file=sys.stderr)
        return 2
    raw = data.get("raw", {})
    print(f"App: {data.get('app')} ({data.get('app_id')})")
    print(f"Market: {data.get('market')} · genre_id={data.get('primary_genre_id')}")
    print(f"Title:    {raw.get('title')}")
    print(f"Subtitle: {raw.get('subtitle')}")
    print(f"Keywords: {raw.get('keywords')}")
    return 0


def cmd_show_b(query: str) -> int:
    # Find latest phase_b file matching query
    candidates = sorted(OUTPUT_DIR.glob("phase_b_competitors_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    q = query.lower()
    data = None
    for path in candidates:
        try:
            d = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if q in str(d.get("app", "")).lower():
            data = d
            break
    if data is None:
        print(f"ERROR: no phase_b file for '{query}'", file=sys.stderr)
        return 2
    cands = data.get("candidates", [])
    print(f"App: {data.get('app')} · {len(cands)} candidates after filters")
    for i, c in enumerate(cands[:10], 1):
        print(f"  {i:>2}. [{c['threat_score']:>8}] {c['name']} "
              f"(outrank={c['outrank_count']}, avg_diff={c['avg_rank_diff']:.1f})")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage:")
        print("  competitor_research.py analyze <app>")
        print("  competitor_research.py rank <app> --tokens 'k1,k2,k3'")
        print("  competitor_research.py show-a <app>")
        print("  competitor_research.py show-b <app>")
        return 2

    parser = argparse.ArgumentParser(prog="competitor_research")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_analyze = sub.add_parser("analyze")
    p_analyze.add_argument("app")

    p_rank = sub.add_parser("rank")
    p_rank.add_argument("app")
    p_rank.add_argument("--tokens", required=True,
                        help="comma-separated token list from Claude")

    p_show_a = sub.add_parser("show-a")
    p_show_a.add_argument("app")

    p_show_b = sub.add_parser("show-b")
    p_show_b.add_argument("app")

    args = parser.parse_args(argv)
    if args.cmd == "analyze":
        return cmd_analyze(args.app)
    if args.cmd == "rank":
        tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
        return cmd_rank(args.app, tokens)
    if args.cmd == "show-a":
        return cmd_show_a(args.app)
    if args.cmd == "show-b":
        return cmd_show_b(args.app)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
