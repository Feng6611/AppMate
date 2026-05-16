"""Identify the top rivals outranking a single app on its own core keywords.

Pure-SERP approach: tokenize the app's title/subtitle/keywords (LLM in
conversation layer), query iTunes Search top-200 per token, collect all rivals
ranked higher than self, aggregate across tokens, score by
popularity-weighted position differential, hard-filter on genre + density,
then let Claude do a batched LLM relevance pass on name + description.

See docs/superpowers/specs/2026-05-16-competitor-research-design.md.
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
    for attempt in range(SERP_RETRIES):
        try:
            r = requests.get(ITUNES_LOOKUP_URL, params=params, timeout=SERP_TIMEOUT_S)
            if r.status_code in (429, 502, 503, 504):
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
    raise RuntimeError(f"iTunes Lookup failed after {SERP_RETRIES} retries: {last_exc}")


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


def _country_to_locale(country: str, app: dict[str, Any]) -> str:
    """Pick a locale string. Prefer the app's primaryLocale; otherwise the first
    locale that exists in appInfo.localizations; final fallback 'en-US'."""
    primary = (app.get("core") or {}).get("primaryLocale") or ""
    if primary:
        return primary
    locs = (app.get("appInfo") or {}).get("localizations") or []
    if locs:
        return locs[0].get("locale", "en-US")
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
