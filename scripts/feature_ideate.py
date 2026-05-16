"""Step 1 aggregator for the feature ideation workflow.

See skills/feature-ideation/SKILL.md for the methodology.
Pipeline: app fuzzy match -> primary market -> raw reviews collector ->
load competitors_<slug>.json (produced by /appmate-competitors) -> phase_a JSON.

v3 (current): no review bucketing, no RAG. The downstream LLM classifies
each review on its own (complaint / suggestion / praise) and competitors
come from the /appmate-competitors output, not AppMate RAG.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any

# Project root + sibling modules
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import appmate_config  # noqa: E402
from aso_optimize_v2 import find_app, slugify  # noqa: E402

# --- Constants ----------------------------------------------------------
REVIEW_AGE_DAYS = 90
RAW_REVIEW_CAP = 150

# Locale -> default country (when locale has no region, e.g. 'ja', 'ko')
LOCALE_DEFAULT_COUNTRY = {
    "ja": "JP", "ko": "KR", "zh-Hans": "CN", "zh-Hant": "TW",
    "en": "US", "fr": "FR", "de": "DE", "it": "IT", "es": "ES",
    "pt": "BR", "ru": "RU", "ar": "SA",
}

# Fields we copy from each entry of competitors_<slug>.json :: filtered[].
COMPETITOR_FIELDS = (
    "name", "description_short", "outranked_keywords",
    "relevance_reason", "threat_score", "rating", "review_count",
)


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


def _slim_review(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "rating": r.get("rating"),
        "title": r.get("title") or "",
        "body": r.get("body") or "",
        "locale": r.get("territory") or "",
        "created_at": r.get("createdDate") or "",
    }


def collect_raw_reviews(
    reviews: list[dict[str, Any]],
    today: dt.date | None = None,
    cap: int = RAW_REVIEW_CAP,
) -> list[dict[str, Any]]:
    """Return last-90-days reviews, newest first, capped at `cap`.

    No rating filter, no trigger-word filter — the downstream LLM reads each
    body and classifies it (complaint / suggestion / praise) on its own.
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=REVIEW_AGE_DAYS)

    dated: list[tuple[dt.date, dict[str, Any]]] = []
    for r in reviews or []:
        d = _parse_review_date(r.get("createdDate", ""))
        if d is None or d < cutoff:
            continue
        dated.append((d, _slim_review(r)))

    dated.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in dated[:cap]]


def load_competitors(
    app_name: str,
    market: str,
    data_dir: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    """Load data/competitors_<slug>.json produced by /appmate-competitors.

    Returns a dict with `source_path`, `generated_at`, `entries` (slim list of
    competitors derived from the `filtered` array) — OR None if the file is
    missing. The caller treats `None` as a hard error and tells the user to
    run /appmate-competitors first.
    """
    d = data_dir if data_dir is not None else OUTPUT_DIR
    slug = slugify(app_name, market)
    path = d / f"competitors_{slug}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    filtered = payload.get("filtered") or []
    entries = [{k: c.get(k) for k in COMPETITOR_FIELDS} for c in filtered]
    return {
        "source_path": str(path),
        "generated_at": payload.get("generated_at") or "",
        "entries": entries,
    }


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
    data_dir: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    """Run the Step 1 pipeline end-to-end.

    Returns the phase_a dict, or None if data/competitors_<slug>.json is
    missing (the caller prints a helpful message and exits 2).
    """
    today = today or dt.date.today()
    bid = (app.get("core") or {}).get("bundleId") or ""
    app_id = str(app.get("id") or "")
    app_name = (app.get("core") or {}).get("name") or ""
    market = pick_primary_market(app, sales_cache, today=today)

    competitors_block = load_competitors(app_name, market, data_dir=data_dir)
    if competitors_block is None:
        return None

    reviews_list = ((app.get("reviews") or {}).get("reviews")) or []
    raw_reviews = collect_raw_reviews(reviews_list, today=today)

    return {
        "app": app_name,
        "app_id": app_id,
        "bundle_id": bid,
        "market": market,
        "downloads_30d_in_market": _downloads_30d(app_id, sales_cache, market, today),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reviews": raw_reviews,
        "competitors_source": competitors_block["source_path"],
        "competitors_generated_at": competitors_block["generated_at"],
        "competitors": competitors_block["entries"],
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
        description="Aggregate raw reviews + competitors for an app."
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
    if phase_a is None:
        app_name = (app.get("core") or {}).get("name") or ""
        market = pick_primary_market(app, sales_cache)
        expected = OUTPUT_DIR / f"competitors_{slugify(app_name, market)}.json"
        print(
            f"[feature-ideate] ERROR: competitors JSON not found at {expected}\n"
            f"Run /appmate-competitors \"{args.app}\" first, then re-run this command.",
            file=sys.stderr,
        )
        return 2

    slug = slugify(phase_a["app"], phase_a["market"])
    out = OUTPUT_DIR / f"phase_a_feature_{slug}.json"
    out.write_text(json.dumps(phase_a, ensure_ascii=False, indent=2))

    print(
        f"[feature-ideate] {phase_a['app']} · market={phase_a['market']} · "
        f"30d={phase_a['downloads_30d_in_market']} · "
        f"reviews={len(phase_a['reviews'])} · "
        f"competitors={len(phase_a['competitors'])}"
    )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
