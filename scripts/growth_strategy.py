"""Step 1 aggregator for the growth strategy workflow.

See skills/growth-strategy/SKILL.md for the methodology.

Pipeline:
  1a. App fuzzy match (reuse aso_optimize_v2.find_app)
  1b. Sales trend: D30 / D30_prev / slope / market_concentration
  1c. Stage detection — one of "冷启动" / "衰退" / "早期增长" / "平台期"
      (cold start / decline / early growth / plateau)
  1d. ASO snapshot: current_locales / primary_market_top10_keywords /
      missing_locales_in_top_markets
  1e. Reviews summary: rating_avg / negative_count_90d / wishlist_count_90d /
      top_negative_themes
  1f. Competitors via AppMate RAG (top_k=8)
  1g. phase_a JSON output
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import appmate_config  # noqa: E402
from aso_optimize_v2 import find_app, slugify  # noqa: E402
from feature_ideate import (  # noqa: E402
    bucket_reviews,
    pick_competitor_seed,
    pick_primary_market,
    _is_install_ptid,
)

# --- Constants (workflow §1c / §1d / §1e / §1f) ------------------------
COMPETITOR_TOP_K = 8
COMPETITOR_MIN_REVIEWS = 50

STAGE_COLD_REVIEWS_THRESHOLD = 20
STAGE_COLD_D30_THRESHOLD = 100
STAGE_DECLINE_SLOPE = 0.8
STAGE_GROWTH_SLOPE = 1.2

ASO_TOP_RANK_CEILING = 10
MISSING_LOCALES_TOP_MARKETS_N = 3

NEG_THEME_DUMP_CAP = 10

# Country → required locale prefix for missing-locale detection.
# If the required value contains '-', use it as-is; otherwise the output
# becomes f"{required}-{country}" (e.g., 'es' + 'MX' → 'es-MX').
COUNTRY_REQUIRED_LOCALE_PREFIX = {
    "CN": "zh-Hans",
    "TW": "zh-Hant", "HK": "zh-Hant",
    "JP": "ja", "KR": "ko",
    "US": "en", "CA": "en", "GB": "en", "AU": "en", "NZ": "en", "IE": "en",
    "MX": "es", "ES": "es", "AR": "es", "CL": "es", "CO": "es", "PE": "es",
    "BR": "pt", "PT": "pt",
    "FR": "fr",
    "DE": "de", "AT": "de", "CH": "de",
    "IT": "it", "RU": "ru",
    "SA": "ar", "AE": "ar",
    "TR": "tr", "ID": "id", "TH": "th", "VN": "vi", "PL": "pl", "NL": "nl",
}


# --- Sales rollup -------------------------------------------------------

def _downloads_in_window(
    app_id: str,
    sales_cache: dict[str, list[dict[str, str]]],
    country: str | None,
    start: dt.date,
    end: dt.date,
) -> int:
    """Sum installs for `app_id` between [start, end] inclusive.

    If `country` is None, sum across all countries.
    """
    total = 0
    for date_str, rows in sales_cache.items():
        if not isinstance(rows, list):
            continue
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < start or d > end:
            continue
        for r in rows:
            if r.get("Apple Identifier") != app_id:
                continue
            if country is not None and r.get("Country Code") != country:
                continue
            if not _is_install_ptid(r.get("Product Type Identifier", "")):
                continue
            try:
                total += int(r.get("Units", 0) or 0)
            except ValueError:
                pass
    return total


def _per_country_downloads(
    app_id: str,
    sales_cache: dict[str, list[dict[str, str]]],
    start: dt.date,
    end: dt.date,
) -> dict[str, int]:
    """Return {country: total_installs} for app_id in [start, end]."""
    tally: dict[str, int] = {}
    for date_str, rows in sales_cache.items():
        if not isinstance(rows, list):
            continue
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < start or d > end:
            continue
        for r in rows:
            if r.get("Apple Identifier") != app_id:
                continue
            if not _is_install_ptid(r.get("Product Type Identifier", "")):
                continue
            country = r.get("Country Code") or ""
            if not country:
                continue
            try:
                u = int(r.get("Units", 0) or 0)
            except ValueError:
                u = 0
            tally[country] = tally.get(country, 0) + u
    return tally


def compute_sales_trend(
    app_id: str,
    sales_cache: dict[str, list[dict[str, str]]],
    market: str,
    today: dt.date,
) -> dict[str, Any]:
    """D30 in main market + D30_prev + slope + market_concentration.

    d30 window:      [today-29, today]   (30 days inclusive)
    d30_prev window: [today-59, today-30] (30 days inclusive, non-overlapping)
    """
    d30_end = today
    d30_start = today - dt.timedelta(days=29)
    d30_prev_end = today - dt.timedelta(days=30)
    d30_prev_start = today - dt.timedelta(days=59)

    d30 = _downloads_in_window(app_id, sales_cache, market, d30_start, d30_end)
    d30_prev = _downloads_in_window(app_id, sales_cache, market, d30_prev_start, d30_prev_end)
    slope = round(d30 / max(d30_prev, 1), 2)

    total_d30 = _downloads_in_window(app_id, sales_cache, None, d30_start, d30_end)
    market_concentration = round(d30 / total_d30, 2) if total_d30 else 0.0

    return {
        "D30": d30,
        "D30_prev": d30_prev,
        "slope": slope,
        "market_concentration": market_concentration,
    }


# --- Stage detection ---------------------------------------------------

def determine_stage(sales: dict[str, Any], total_reviews: int) -> tuple[str, list[str]]:
    """Apply the 4-stage detection per the workflow §1c.

    Returned stage values stay in Chinese because they key the methodology
    cheat-sheet and appear verbatim in the generated report.

    Priority (top to bottom):
      1. "冷启动" (cold start): total_reviews < 20 OR D30 < 100
      2. "衰退" (decline): slope < 0.8
      3. "早期增长" (early growth): slope > 1.2
      4. "平台期" (plateau): 0.8 <= slope <= 1.2 (fallback)
    """
    d30 = sales["D30"]
    d30_prev = sales["D30_prev"]
    slope = sales["slope"]

    if total_reviews < STAGE_COLD_REVIEWS_THRESHOLD or d30 < STAGE_COLD_D30_THRESHOLD:
        ev: list[str] = []
        if d30 < STAGE_COLD_D30_THRESHOLD:
            ev.append(f"D30={d30} < {STAGE_COLD_D30_THRESHOLD}")
        if total_reviews < STAGE_COLD_REVIEWS_THRESHOLD:
            ev.append(f"评价总数 {total_reviews} < {STAGE_COLD_REVIEWS_THRESHOLD}")
        ev.append(f"评价总数 {total_reviews}")
        return "冷启动", ev

    if slope < STAGE_DECLINE_SLOPE:
        pct = round((slope - 1) * 100)
        return "衰退", [
            f"D30={d30} (上 30 日 {d30_prev} → 近 30 日 {d30})",
            f"slope={slope} → 环比跌 {abs(pct)}%",
            f"评价总数 {total_reviews}，已过冷启动门槛",
        ]

    if slope > STAGE_GROWTH_SLOPE:
        pct = round((slope - 1) * 100)
        return "早期增长", [
            f"D30={d30} (上 30 日 {d30_prev} → 近 30 日 {d30})",
            f"slope={slope} → 环比涨 {pct}%",
            f"评价总数 {total_reviews}，已过冷启动门槛",
        ]

    return "平台期", [
        f"D30={d30} (上 30 日 {d30_prev} → 近 30 日 {d30})",
        f"slope={slope} → 环比波动在 ±20% 内",
        f"评价总数 {total_reviews}",
    ]


# --- ASO snapshot extraction -------------------------------------------

def extract_aso_state(
    app: dict[str, Any],
    snapshots: dict[str, Any],
    sales_cache: dict[str, list[dict[str, str]]],
    market: str,
    today: dt.date,
) -> dict[str, Any]:
    """Pull current locales, top-10 keyword count in main market, and
    high-volume countries that lack a matching locale.
    """
    locs = (app.get("appInfo") or {}).get("localizations") or []
    current_locales = sorted({(loc.get("locale") or "") for loc in locs if loc.get("locale")})

    bundle_id = (app.get("core") or {}).get("bundleId") or ""
    app_id = str(app.get("id") or "")

    top10 = 0
    if snapshots and bundle_id:
        for d_str in sorted(snapshots.keys(), reverse=True):
            day = snapshots.get(d_str) or {}
            bundle_day = day.get(bundle_id) or {}
            country_day = bundle_day.get(market) or {}
            if country_day:
                for _kw, rank in country_day.items():
                    try:
                        if int(rank) <= ASO_TOP_RANK_CEILING:
                            top10 += 1
                    except (TypeError, ValueError):
                        pass
                break

    d30_end = today
    d30_start = today - dt.timedelta(days=29)
    per_country = _per_country_downloads(app_id, sales_cache, d30_start, d30_end)
    top_countries = sorted(per_country.items(), key=lambda kv: kv[1], reverse=True)
    top_countries = top_countries[:MISSING_LOCALES_TOP_MARKETS_N]

    missing: list[str] = []
    for country, _units in top_countries:
        required = COUNTRY_REQUIRED_LOCALE_PREFIX.get(country)
        if not required:
            continue
        matched = any(loc.startswith(required) for loc in current_locales)
        if not matched:
            locale_code = required if "-" in required else f"{required}-{country}"
            missing.append(locale_code)

    return {
        "current_locales": current_locales,
        "primary_market_top10_keywords": top10,
        "missing_locales_in_top_markets": missing,
    }


# --- Reviews summary ---------------------------------------------------

def summarize_reviews(
    reviews: list[dict[str, Any]],
    today: dt.date,
) -> dict[str, Any]:
    """rating_avg + negative/wishlist counts + dump of top negative bodies."""
    total = len(reviews)
    ratings = [r.get("rating") for r in reviews if isinstance(r.get("rating"), (int, float))]
    rating_avg = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    buckets = bucket_reviews(reviews, today=today)
    negs = buckets["negative"]
    wishes = buckets["wishlist"]
    top_themes = [r["body"] for r in negs[:NEG_THEME_DUMP_CAP]]

    return {
        "total": total,
        "rating_avg": rating_avg,
        "negative_count_90d": len(negs),
        "wishlist_count_90d": len(wishes),
        "top_negative_themes": top_themes,
    }


# --- Competitors via AppMate RAG ---------------------------------------

# Wrapper so tests can monkeypatch.
def _rag_search(**kwargs: Any) -> list[dict[str, Any]]:
    from appmate_rag_client import search as _search
    return _search(**kwargs)


COMPETITOR_FIELDS = ("name", "rating", "review_count", "description", "appmate_reason")


def fetch_competitors(seed: str, country: str) -> list[dict[str, Any]]:
    """Top-N competitors for a seed via AppMate RAG.

    On any RAG exception returns []. Downstream LLM degrades gracefully
    (reviews + ASO snapshot still drive the strategy).
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
    return [{k: r.get(k) for k in COMPETITOR_FIELDS} for r in (rows or [])]


# --- Top-level pipeline ------------------------------------------------

def build_phase_a(
    app: dict[str, Any],
    sales_cache: dict[str, list[dict[str, str]]],
    snapshots: dict[str, Any] | None = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Step 1 pipeline end-to-end. Returns the phase_a dict per workflow §1g."""
    today = today or dt.date.today()
    snapshots = snapshots or {}

    bid = (app.get("core") or {}).get("bundleId") or ""
    app_id = str(app.get("id") or "")
    market = pick_primary_market(app, sales_cache, today=today)

    sales = compute_sales_trend(app_id, sales_cache, market, today)

    reviews_list = ((app.get("reviews") or {}).get("reviews")) or []
    reviews_summary = summarize_reviews(reviews_list, today)

    stage, stage_evidence = determine_stage(sales, reviews_summary["total"])

    aso = extract_aso_state(app, snapshots, sales_cache, market, today)

    seed = pick_competitor_seed(app)
    competitors = fetch_competitors(seed, country=market)

    return {
        "app": (app.get("core") or {}).get("name") or "",
        "app_id": app_id,
        "bundle_id": bid,
        "market": market,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sales": sales,
        "stage": stage,
        "stage_evidence": stage_evidence,
        "aso": aso,
        "reviews": reviews_summary,
        "competitor_seed": seed,
        "competitors": competitors,
    }


# --- File paths (overridable in tests) ---------------------------------
APPS_FULL_PATH = appmate_config.data_path("apps_full.json")
SALES_CACHE_PATH = appmate_config.data_path("sales_cache.json")
ASO_SNAPSHOTS_PATH = appmate_config.data_path("aso_rank_snapshots.json")
OUTPUT_DIR = appmate_config.DATA_DIR


def _load_json(path: pathlib.Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Step 1 aggregator for the growth strategy workflow."
    )
    parser.add_argument("app", help="App Store ID / bundle ID / SKU / fuzzy name")
    args = parser.parse_args(argv)

    apps = (_load_json(APPS_FULL_PATH) or {}).get("apps") or []
    app = find_app(args.app, apps=apps)
    if not app:
        print(f"[growth-strategy] App not found: {args.app}", file=sys.stderr)
        return 1

    sales_cache = _load_json(SALES_CACHE_PATH) or {}
    snapshots = _load_json(ASO_SNAPSHOTS_PATH) or {}

    phase_a = build_phase_a(app, sales_cache, snapshots)
    slug = slugify(phase_a["app"], phase_a["market"])
    out = OUTPUT_DIR / f"phase_a_growth_{slug}.json"
    out.write_text(json.dumps(phase_a, ensure_ascii=False, indent=2))

    s = phase_a["sales"]
    r = phase_a["reviews"]
    print(
        f"[growth-strategy] {phase_a['app']} · market={phase_a['market']} · "
        f"stage={phase_a['stage']} · D30={s['D30']} (slope={s['slope']}) · "
        f"reviews(-/+wish/total)={r['negative_count_90d']}/"
        f"{r['wishlist_count_90d']}/{r['total']} · "
        f"competitors={len(phase_a['competitors'])}"
    )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
