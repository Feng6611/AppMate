"""ASO Optimize v2 — on-demand single-app optimizer.

See docs/superpowers/specs/2026-05-13-aso-optimize-v2-design.md for the design.

CLI:
    python3 aso_optimize_v2.py analyze <app>
    python3 aso_optimize_v2.py validate <app> --candidates kw1,kw2,...
    python3 aso_optimize_v2.py show-a <app>
    python3 aso_optimize_v2.py show-b <app>
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
from typing import Any, Callable

# Reuse from siblings — keep imports explicit
from aso_optimize import (
    find_top_market,
    pick_locales_for_country,
    COUNTRY_FLAG,
    PLATFORM_TO_ENTITY,
    PLATFORM_LABEL,
)
from aso_report import (
    tokenize_text,
    rank_keyword as itunes_rank,
    load_rank_cache, save_rank_cache,
    latest_version_localizations,
    app_platform,
)
from aso_daily import _good_token
import appmate_config
import astro_client

APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")


def find_app(query: str, apps: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Find an app by App Store ID, bundle ID, SKU, or fuzzy name match.

    `apps` defaults to apps_full.json["apps"] — pass explicit list for testing.
    Match order:
      1. exact app["id"]
      2. exact core.bundleId
      3. exact core.sku
      4. case-insensitive substring on core.name
    """
    if apps is None:
        apps = json.loads(APPS_FULL.read_text())["apps"]

    # Exact id / bundleId / sku
    for a in apps:
        core = a.get("core") or {}
        if a.get("id") == query:
            return a
        if core.get("bundleId") == query or core.get("sku") == query:
            return a

    # Case-insensitive substring on name
    q_lower = query.lower()
    for a in apps:
        name = (a.get("core") or {}).get("name") or ""
        if q_lower in name.lower():
            return a
    return None


def slugify(name: str, country: str) -> str:
    """Build a filesystem-safe slug from an app name + country code.

    Strategy: take the first ASCII word in the name, lowercase it.
    If no ASCII word exists, use 'app'. Append '_<country>' lowercased.
    """
    m = re.search(r"[A-Za-z][A-Za-z0-9]*", name or "")
    first_word = m.group(0).lower() if m else "app"
    return f"{first_word}_{country.lower()}"


def collect_tokens(
    app: dict[str, Any],
    info_loc: str | None,
    ver_loc: str | None,
) -> list[dict[str, Any]]:
    """Extract candidate tokens from title/subtitle/keywords for the given locales.

    Returns list of {keyword, source}. `source` is a sorted list of tags drawn
    from {T, S, K} (Title, Subtitle, Keywords).

    Filtering via `_good_token` (CJK >= 6 chars rejected, Latin stopwords rejected,
    pure digits rejected, etc.).
    """
    info_by_locale = {
        L.get("locale"): L
        for L in (app.get("appInfo") or {}).get("localizations", [])
    }
    ver_by_locale = {
        L.get("locale"): L
        for L in latest_version_localizations(app)
    }
    info = info_by_locale.get(info_loc) or {}
    ver = ver_by_locale.get(ver_loc) or {}

    title = info.get("name")
    subtitle = info.get("subtitle")
    keywords_raw = ver.get("keywords")

    tagged = tokenize_text(title, subtitle, keywords_raw)  # {token: {T/S/K}}
    out = []
    for tok, srcs in tagged.items():
        if not _good_token(tok):
            continue
        out.append({"keyword": tok, "source": sorted(srcs)})
    return out


RankFn = Callable[[str, str, str, str], int | None]
PopFn = Callable[[list[str], str], dict[str, dict[str, Any]]]


def build_phase_a(
    app: dict[str, Any],
    market: str,
    info_loc: str | None,
    ver_loc: str | None,
    downloads_30d: int,
    rank_fn: RankFn,
    pop_fn: PopFn,
) -> dict[str, Any]:
    """Assemble the Phase A JSON for one app. Pure: all IO delegated to `rank_fn`/`pop_fn`."""
    bundle_id = (app.get("core") or {}).get("bundleId") or ""
    platform_code = app_platform(app)
    platform = PLATFORM_LABEL.get(platform_code, platform_code)
    entity = PLATFORM_TO_ENTITY.get(platform_code, "software")

    # Pull metadata for the picked locales
    info_by_locale = {
        L.get("locale"): L
        for L in (app.get("appInfo") or {}).get("localizations", [])
    }
    ver_by_locale = {
        L.get("locale"): L
        for L in latest_version_localizations(app)
    }
    info = info_by_locale.get(info_loc) or {}
    ver = ver_by_locale.get(ver_loc) or {}

    title = info.get("name")
    subtitle = info.get("subtitle")
    keywords_raw = ver.get("keywords")

    # Tokens + rank + popularity
    tokens = collect_tokens(app, info_loc, ver_loc)
    keywords_to_rank = [t["keyword"] for t in tokens]
    pop_map = pop_fn(keywords_to_rank, market.lower()) if keywords_to_rank else {}

    enriched: list[dict[str, Any]] = []
    for t in tokens:
        kw = t["keyword"]
        rank = rank_fn(kw, market, entity, bundle_id)
        pop_data = pop_map.get(kw) or {}
        enriched.append({
            "keyword": kw,
            "source": t["source"],
            "rank": rank,
            "popularity": pop_data.get("popularity"),
            "difficulty": pop_data.get("difficulty"),
        })

    return {
        "app": (app.get("core") or {}).get("name"),
        "app_id": app.get("id"),
        "bundle_id": bundle_id,
        "platform": platform,
        "market": market,
        "locale": info_loc if info_loc == ver_loc else f"{info_loc or '—'} / {ver_loc or '—'}",
        "downloads_30d_in_market": downloads_30d,
        "current_metadata": {
            "title": title,
            "subtitle": subtitle,
            "keywords": keywords_raw,
        },
        "current_tokens": enriched,
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    """Write JSON with UTF-8 + ensure_ascii=False so CJK reads naturally."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_analyze(query: str) -> int:
    """Phase A: load app, find market, collect data, write phase_a_<slug>.json."""
    app = find_app(query)
    if not app:
        print(f"ERROR: no app matches {query!r}", file=sys.stderr)
        return 2

    reports = json.loads(SALES_CACHE.read_text())
    today = dt.date.today()
    name = (app.get("core") or {}).get("name") or ""
    top = find_top_market(name, reports, today)
    if not top:
        print(f"ERROR: no sales data for {name!r}", file=sys.stderr)
        return 3
    country, dl30 = top

    info_locales = {
        L.get("locale")
        for L in (app.get("appInfo") or {}).get("localizations", [])
    }
    ver_locales = {
        L.get("locale")
        for L in latest_version_localizations(app)
    }
    info_loc, ver_loc, _ = pick_locales_for_country(country, info_locales, ver_locales)

    rank_cache = load_rank_cache()

    def _rank(kw, ctry, entity, bid):
        r = itunes_rank(kw, ctry, entity, bid, rank_cache)
        return r

    def _pop(kws, store):
        return astro_client.lookup_popularity_batch(kws, store)

    print(f"[analyze] {name} · market={country} · locale={info_loc}/{ver_loc} · 30d={dl30}", flush=True)
    payload = build_phase_a(
        app=app,
        market=country,
        info_loc=info_loc,
        ver_loc=ver_loc,
        downloads_30d=dl30,
        rank_fn=_rank,
        pop_fn=_pop,
    )
    save_rank_cache(rank_cache)

    slug = slugify(name, country)
    out_path = appmate_config.data_path(f"phase_a_{slug}.json")
    write_json(out_path, payload)
    print(f"[saved] {out_path}  ({len(payload['current_tokens'])} tokens)", flush=True)
    return 0


MAX_CANDIDATES_PER_RUN = 30


def parse_candidates_arg(arg: str) -> list[str]:
    """Parse `--candidates kw1,kw2,kw3` into a deduped, capped list.

    Rules:
      - split on `,`
      - strip whitespace per item
      - drop empty
      - case-insensitive dedup (preserving first occurrence's casing)
      - cap at MAX_CANDIDATES_PER_RUN
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in (arg or "").split(","):
        kw = raw.strip()
        if not kw:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
        if len(out) >= MAX_CANDIDATES_PER_RUN:
            break
    return out


def build_phase_b(
    app: dict[str, Any],
    market: str,
    candidates: list[str],
    rank_fn: RankFn,
    pop_fn: PopFn,
) -> dict[str, Any]:
    """Assemble the Phase B JSON: each candidate annotated with rank + pop/diff."""
    bundle_id = (app.get("core") or {}).get("bundleId") or ""
    platform_code = app_platform(app)
    entity = PLATFORM_TO_ENTITY.get(platform_code, "software")

    pop_map = pop_fn(candidates, market.lower()) if candidates else {}

    rows: list[dict[str, Any]] = []
    for kw in candidates:
        rank = rank_fn(kw, market, entity, bundle_id)
        pop_data = pop_map.get(kw) or {}
        rows.append({
            "keyword": kw,
            "rank": rank,
            "popularity": pop_data.get("popularity"),
            "difficulty": pop_data.get("difficulty"),
        })

    return {
        "app": (app.get("core") or {}).get("name"),
        "app_id": app.get("id"),
        "bundle_id": bundle_id,
        "market": market,
        "candidates": rows,
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def cmd_validate(query: str, candidates_arg: str) -> int:
    """Phase B: validate user-supplied candidate keywords for the app's main market."""
    app = find_app(query)
    if not app:
        print(f"ERROR: no app matches {query!r}", file=sys.stderr)
        return 2

    candidates = parse_candidates_arg(candidates_arg)
    if not candidates:
        print("ERROR: no candidates parsed from --candidates", file=sys.stderr)
        return 4

    reports = json.loads(SALES_CACHE.read_text()) if SALES_CACHE.exists() else {}
    today = dt.date.today()
    name = (app.get("core") or {}).get("name") or ""
    top = find_top_market(name, reports, today)
    if not top:
        print(f"ERROR: no sales data for {name!r}", file=sys.stderr)
        return 3
    country, _ = top

    rank_cache = load_rank_cache()

    def _rank(kw, ctry, entity, bid):
        return itunes_rank(kw, ctry, entity, bid, rank_cache)

    def _pop(kws, store):
        return astro_client.lookup_popularity_batch(kws, store)

    print(f"[validate] {name} · market={country} · {len(candidates)} candidates", flush=True)
    payload = build_phase_b(
        app=app,
        market=country,
        candidates=candidates,
        rank_fn=_rank,
        pop_fn=_pop,
    )
    save_rank_cache(rank_cache)

    slug = slugify(name, country)
    out_path = appmate_config.data_path(f"phase_b_{slug}.json")
    write_json(out_path, payload)
    print(f"[saved] {out_path}", flush=True)
    return 0


def _show_phase(query: str, phase: str) -> int:
    """Shared logic for show-a/show-b. `phase` is 'a' or 'b'."""
    app = find_app(query)
    if not app:
        print(f"ERROR: no app matches {query!r}", file=sys.stderr)
        return 2

    name = (app.get("core") or {}).get("name") or ""
    # We don't know the market without re-running analyze, so scan for matching files
    bundle_first = re.search(r"[A-Za-z][A-Za-z0-9]*", name)
    prefix = (bundle_first.group(0).lower() if bundle_first else "app")
    pattern = f"phase_{phase}_{prefix}_*.json"
    candidates = sorted(appmate_config.DATA_DIR.glob(pattern))
    if not candidates:
        print(f"ERROR: no phase_{phase} file found matching {pattern!r}", file=sys.stderr)
        return 5

    # Filter by app_id to avoid prefix collisions (two apps sharing first ASCII word)
    target_id = app.get("id")
    matches: list[pathlib.Path] = []
    for p in candidates:
        try:
            payload = json.loads(p.read_text())
        except Exception:
            continue
        if payload.get("app_id") == target_id:
            matches.append(p)
    if not matches:
        print(f"ERROR: no phase_{phase} file for app_id={target_id!r}", file=sys.stderr)
        return 5

    # Use most recently modified
    path = max(matches, key=lambda p: p.stat().st_mtime)
    payload = json.loads(path.read_text())

    if phase == "a":
        _print_phase_a_summary(payload)
    else:
        _print_phase_b_summary(payload)
    return 0


def _print_phase_a_summary(p: dict[str, Any]) -> None:
    print(f"# Phase A · {p.get('app')}  ·  {p.get('market')} ({p.get('locale')})")
    print(f"  downloads_30d_in_market: {p.get('downloads_30d_in_market', 0):,}")
    meta = p.get("current_metadata") or {}
    print(f"  title:    {meta.get('title')!r}")
    print(f"  subtitle: {meta.get('subtitle')!r}")
    print(f"  keywords: {meta.get('keywords')!r}")
    print()
    print(f"  {len(p.get('current_tokens') or [])} current tokens:")
    print(f"  {'keyword':<28} {'src':<6} {'rank':>6} {'pop':>5} {'diff':>5}")
    print(f"  {'-'*28} {'-'*6} {'-'*6} {'-'*5} {'-'*5}")
    for t in (p.get("current_tokens") or []):
        kw = (t.get("keyword") or "")[:28]
        src = "".join(t.get("source") or [])[:6]
        rank = t.get("rank")
        pop = t.get("popularity")
        diff = t.get("difficulty")
        rank_s = str(rank) if rank is not None else "—"
        pop_s = str(pop) if pop is not None else "—"
        diff_s = str(diff) if diff is not None else "—"
        print(f"  {kw:<28} {src:<6} {rank_s:>6} {pop_s:>5} {diff_s:>5}")


def _print_phase_b_summary(p: dict[str, Any]) -> None:
    print(f"# Phase B · {p.get('app')}  ·  {p.get('market')}")
    cands = p.get("candidates") or []
    print(f"  {len(cands)} candidates")
    print(f"  {'keyword':<28} {'rank':>6} {'pop':>5} {'diff':>5}")
    print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*5}")
    for c in cands:
        kw = (c.get("keyword") or "")[:28]
        rank = c.get("rank")
        pop = c.get("popularity")
        diff = c.get("difficulty")
        rank_s = str(rank) if rank is not None else "—"
        pop_s = str(pop) if pop is not None else "—"
        diff_s = str(diff) if diff is not None else "—"
        print(f"  {kw:<28} {rank_s:>6} {pop_s:>5} {diff_s:>5}")


def cmd_show_a(query: str) -> int:
    return _show_phase(query, "a")


def cmd_show_b(query: str) -> int:
    return _show_phase(query, "b")


USAGE = """Usage:
  python3 aso_optimize_v2.py analyze <app>
  python3 aso_optimize_v2.py validate <app> --candidates kw1,kw2,kw3   (max 30, deduplicated)
  python3 aso_optimize_v2.py show-a <app>
  python3 aso_optimize_v2.py show-b <app>

<app> matches by App Store ID / bundle ID / SKU / fuzzy app name.
"""


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0

    cmd, *rest = argv

    if cmd == "analyze":
        if not rest:
            print("ERROR: analyze requires <app>", file=sys.stderr)
            return 2
        return cmd_analyze(rest[0])

    if cmd == "validate":
        if len(rest) < 3 or rest[1] != "--candidates":
            print("ERROR: validate requires <app> --candidates kw1,kw2,kw3", file=sys.stderr)
            return 2
        return cmd_validate(rest[0], rest[2])

    if cmd == "show-a":
        if not rest:
            print("ERROR: show-a requires <app>", file=sys.stderr)
            return 2
        return cmd_show_a(rest[0])

    if cmd == "show-b":
        if not rest:
            print("ERROR: show-b requires <app>", file=sys.stderr)
            return 2
        return cmd_show_b(rest[0])

    print(f"ERROR: unknown command {cmd!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
