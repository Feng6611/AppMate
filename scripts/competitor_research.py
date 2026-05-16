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
