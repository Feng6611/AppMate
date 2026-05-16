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
