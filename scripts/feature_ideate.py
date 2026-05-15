"""Step 1 aggregator for the feature ideation workflow.

See skills/feature-ideation/SKILL.md for the methodology.
Pipeline: app fuzzy match -> primary market -> review bucketing ->
competitor fetch -> ASO blindspots -> phase_a JSON.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
from typing import Any

# Project root + sibling modules
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import appmate_config  # noqa: E402
from aso_optimize_v2 import find_app, slugify  # noqa: E402

# --- Constants ----------------------------------------------------------
REVIEW_AGE_DAYS = 90
REVIEW_BUCKET_CAP = 50
NEG_RATING_MAX = 3
POS_RATING_MIN = 4
WISH_TRIGGERS = ["希望", "能否", "建议", "求", "请加", "不能", "为什么没有",
                 "wish", "would love", "please add", "hope", "could you"]
MIN_BODY_LEN = 10
COMPETITOR_TOP_K = 10
COMPETITOR_MIN_REVIEWS = 50

# Locale -> default country (when locale has no region, e.g. 'ja', 'ko')
LOCALE_DEFAULT_COUNTRY = {
    "ja": "JP", "ko": "KR", "zh-Hans": "CN", "zh-Hant": "TW",
    "en": "US", "fr": "FR", "de": "DE", "it": "IT", "es": "ES",
    "pt": "BR", "ru": "RU", "ar": "SA",
}


def _is_install_ptid(ptid: str) -> bool:
    """True if this Product Type Identifier counts as an app install.

    Mirrors sales_report.is_download_ptid: open-ended exclusion of IAP / IAP-trial / updates.
    """
    if not ptid:
        return False
    if ptid.startswith("IA") or ptid.startswith("ITA"):
        return False  # IAP
    if ptid.startswith("7"):
        return False  # update
    return True


def pick_primary_market(
    app: dict[str, Any],
    sales_cache: dict[str, list[dict[str, str]]],
    today: dt.date | None = None,
    window_days: int = 30,
) -> str:
    """Return the 2-letter country code for the app's primary market.

    1. Pick country with max installs in the last `window_days`.
    2. Fall back to the country derived from app.core.primaryLocale.
    3. Final fallback: 'US'.
    """
    today = today or dt.date.today()
    app_id = str(app.get("id") or "")
    cutoff = today - dt.timedelta(days=window_days)

    tally: dict[str, int] = {}
    for date_str, rows in sales_cache.items():
        if not isinstance(rows, list):
            continue
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < cutoff or d > today:
            continue
        for r in rows:
            if r.get("Apple Identifier") != app_id:
                continue
            ptid = r.get("Product Type Identifier", "")
            if not _is_install_ptid(ptid):
                continue
            country = r.get("Country Code", "")
            if not country:
                continue
            try:
                units = int(r.get("Units", 0) or 0)
            except ValueError:
                units = 0
            tally[country] = tally.get(country, 0) + units

    if tally:
        return max(tally.items(), key=lambda kv: kv[1])[0]

    locale = (app.get("core") or {}).get("primaryLocale") or ""
    # Try full locale, then language-only key
    if "-" in locale:
        region = locale.split("-")[1]
        if region.isalpha() and len(region) == 2:
            return region.upper()
    if locale in LOCALE_DEFAULT_COUNTRY:
        return LOCALE_DEFAULT_COUNTRY[locale]
    lang = locale.split("-")[0] if locale else ""
    if lang in LOCALE_DEFAULT_COUNTRY:
        return LOCALE_DEFAULT_COUNTRY[lang]
    return "US"


def _parse_review_date(created: str) -> dt.date | None:
    """Parse an Apple review createdDate like '2026-05-05T03:58:44-07:00'."""
    if not created or not isinstance(created, str):
        return None
    head = created.split("T", 1)[0]
    try:
        return dt.date.fromisoformat(head)
    except ValueError:
        return None


def _has_wish_trigger(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    for trig in WISH_TRIGGERS:
        if trig.lower() in low:
            return True
    return False


def _slim_review(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "rating": r.get("rating"),
        "title": r.get("title") or "",
        "body": r.get("body") or "",
        "locale": r.get("territory") or "",
        "created_at": r.get("createdDate") or "",
    }


def bucket_reviews(
    reviews: list[dict[str, Any]],
    today: dt.date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Split reviews into 'negative' and 'wishlist' buckets per spec §1b.

    - negative: rating <= 3 AND len(body) >= 10
    - wishlist: rating >= 4 AND body contains a trigger word
    Both: createdDate within last 90 days. Each bucket capped at 50 entries,
    newest first.
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=REVIEW_AGE_DAYS)

    negative: list[tuple[dt.date, dict[str, Any]]] = []
    wishlist: list[tuple[dt.date, dict[str, Any]]] = []
    for r in reviews or []:
        body = r.get("body") or ""
        rating = r.get("rating")
        d = _parse_review_date(r.get("createdDate", ""))
        if d is None or d < cutoff:
            continue
        if isinstance(rating, int) and rating <= NEG_RATING_MAX and len(body) >= MIN_BODY_LEN:
            negative.append((d, _slim_review(r)))
        elif isinstance(rating, int) and rating >= POS_RATING_MIN and _has_wish_trigger(body):
            wishlist.append((d, _slim_review(r)))

    negative.sort(key=lambda x: x[0], reverse=True)
    wishlist.sort(key=lambda x: x[0], reverse=True)
    return {
        "negative": [r for _, r in negative[:REVIEW_BUCKET_CAP]],
        "wishlist": [r for _, r in wishlist[:REVIEW_BUCKET_CAP]],
    }


def pick_competitor_seed(app: dict[str, Any]) -> str:
    """Choose the keyword to feed AppMate RAG as a competitor-search seed.

    Priority:
      1. Longest ASCII alpha word from a locale name (prefer country locale).
      2. Longest ASCII alpha word from core.name.
      3. Literal 'app'.

    v2: removed the "ASO best ranked keyword" path — see workflow doc §1c
    for rationale (ASO data sources removed entirely from this workflow).
    """
    candidates: list[str] = []
    locs = (app.get("appInfo") or {}).get("localizations") or []
    for loc in locs:
        n = loc.get("name") or ""
        if n:
            candidates.append(n)
    core_name = (app.get("core") or {}).get("name") or ""
    if core_name:
        candidates.append(core_name)

    best_word = ""
    for name in candidates:
        for m in re.finditer(r"[A-Za-z]{3,}", name):
            w = m.group(0)
            if len(w) > len(best_word):
                best_word = w
    return best_word or "app"


# Wrap appmate_rag_client.search so tests can monkeypatch _rag_search.
def _rag_search(**kwargs: Any) -> list[dict[str, Any]]:
    from appmate_rag_client import search as _search  # local import for testability
    return _search(**kwargs)


COMPETITOR_FIELDS = ("name", "rating", "review_count", "description", "appmate_reason")


def fetch_competitors(seed: str, country: str) -> list[dict[str, Any]]:
    """Pull top-N similar apps for a seed keyword via AppMate RAG.

    Returns a list of dicts with only the COMPETITOR_FIELDS keys.
    On any RAG exception returns an empty list (the caller treats no-competitors
    as a soft failure: phase_a still emits, downstream LLM falls back to
    reviews + ASO blindspots).
    """
    try:
        rows = _rag_search(
            query=seed,
            region=country.lower(),
            top_k=COMPETITOR_TOP_K,
            min_review_count=COMPETITOR_MIN_REVIEWS,
            sort_by="S",
        )
    except Exception:
        return []
    out = []
    for r in rows or []:
        out.append({k: r.get(k) for k in COMPETITOR_FIELDS})
    return out


def _downloads_30d(app_id: str, sales_cache: dict[str, list[dict[str, str]]],
                   country: str, today: dt.date) -> int:
    """Count installs for app_id in country within last 30 days."""
    cutoff = today - dt.timedelta(days=30)
    total = 0
    for date_str, rows in sales_cache.items():
        if not isinstance(rows, list):
            continue
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < cutoff or d > today:
            continue
        for r in rows:
            if r.get("Apple Identifier") != app_id:
                continue
            if r.get("Country Code") != country:
                continue
            if not _is_install_ptid(r.get("Product Type Identifier", "")):
                continue
            try:
                total += int(r.get("Units", 0) or 0)
            except ValueError:
                pass
    return total


def build_phase_a(
    app: dict[str, Any],
    sales_cache: dict[str, list[dict[str, str]]],
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Run the Step 1 pipeline end-to-end and return the phase_a dict.

    v2: removed snapshots/pop_cache parameters — ASO blindspot data source
    deleted (see workflow doc §1c v1 → v2 note).
    """
    today = today or dt.date.today()
    bid = (app.get("core") or {}).get("bundleId") or ""
    app_id = str(app.get("id") or "")
    market = pick_primary_market(app, sales_cache, today=today)

    reviews_list = ((app.get("reviews") or {}).get("reviews")) or []
    buckets = bucket_reviews(reviews_list, today=today)

    seed = pick_competitor_seed(app)
    competitors = fetch_competitors(seed, country=market)

    return {
        "app": (app.get("core") or {}).get("name") or "",
        "app_id": app_id,
        "bundle_id": bid,
        "market": market,
        "downloads_30d_in_market": _downloads_30d(app_id, sales_cache, market, today),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "competitor_seed": seed,
        "reviews_negative": buckets["negative"],
        "reviews_wishlist": buckets["wishlist"],
        "competitors": competitors,
    }


# --- File paths (overridable in tests) ----------------------------------
APPS_FULL_PATH = appmate_config.data_path("apps_full.json")
SALES_CACHE_PATH = appmate_config.data_path("sales_cache.json")
OUTPUT_DIR = appmate_config.DATA_DIR


def _load_json(path: pathlib.Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate reviews + competitors for an app."
    )
    parser.add_argument("app", help="App Store ID / bundle ID / SKU / fuzzy name")
    args = parser.parse_args(argv)

    import key_safety
    key_safety.require_safe_key_or_exit()

    apps = (_load_json(APPS_FULL_PATH) or {}).get("apps") or []
    app = find_app(args.app, apps=apps)
    if not app:
        print(f"[feature-ideate] App not found: {args.app}", file=sys.stderr)
        return 1

    sales_cache = _load_json(SALES_CACHE_PATH) or {}

    phase_a = build_phase_a(app, sales_cache)
    slug = slugify(phase_a["app"], phase_a["market"])
    out = OUTPUT_DIR / f"phase_a_feature_{slug}.json"
    out.write_text(json.dumps(phase_a, ensure_ascii=False, indent=2))

    print(
        f"[feature-ideate] {phase_a['app']} · market={phase_a['market']} · "
        f"30d={phase_a['downloads_30d_in_market']} · "
        f"reviews(-/+wish)={len(phase_a['reviews_negative'])}/"
        f"{len(phase_a['reviews_wishlist'])} · "
        f"competitors={len(phase_a['competitors'])}"
    )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
