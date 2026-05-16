# Competitor Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new AppMate skill `competitor-research` that, given a single live app, identifies the top 5–10 rivals who are outranking it on its own core keywords, using only iTunes Search SERP data (zero RAG).

**Architecture:** Single CLI script `scripts/competitor_research.py` with pure helper functions (genre lookup / market pick / SERP fetch / aggregate / score / filter / build Phase A & B). Claude does keyword tokenization and batched LLM relevance filter in conversation (per `skills/competitor-research/SKILL.md`). Markdown report rendered by Claude, JSON contracts written by the script for downstream consumers.

**Tech Stack:** Python 3, stdlib (json, datetime, pathlib, argparse, statistics), `requests` (already a dependency via existing scripts), pytest, existing project modules (`aso_optimize_v2.find_app/slugify`, `aso_report.ITUNES_BASE`, `keyword_local.lookup_popularity`, `feature_ideate.pick_primary_market`, `appmate_config`).

**Spec:** [docs/superpowers/specs/2026-05-16-competitor-research-design.md](../specs/2026-05-16-competitor-research-design.md)

**Out of scope:** Downstream wiring (making `feature-ideation` / `growth-strategy` / `aso-optimize` consume `competitors_<slug>.json`); continuous monitoring; multi-market consolidated view. See spec §15.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/competitor_research.py` (create) | CLI entry + pipeline helpers: `fetch_primary_genre_id` / `pick_main_market` (delegates to `feature_ideate.pick_primary_market`) / `build_phase_a` / `rank_keyword_with_details` / `collect_outrankers_for_token` / `aggregate_rivals` / `score_threat` / `filter_by_genre_and_density` / `build_phase_b` / `cmd_analyze` / `cmd_rank` / `cmd_show_a` / `cmd_show_b` / `main` |
| `tests/test_competitor_research.py` (create) | Unit tests for each pure helper + integration tests for `main()` dispatch using monkeypatch'd network/IO |
| `skills/competitor-research/SKILL.md` (create) | Claude-side process doc: tokenize prompt, batched relevance-filter prompt, markdown template, checklist |
| `commands/appmate-competitors.md` (create) | Slash command definition (`/appmate-competitors <app>`) |
| `README.md` (modify) | "6 workflows" → "7 workflows"; add a row to the workflows table |

Helpers are **pure where possible**: take dicts/lists in, return dicts/lists out. The only I/O lives in `cmd_*` functions, `fetch_primary_genre_id` (HTTP wrapped with cache), and `rank_keyword_with_details` (HTTP wrapped with cache). Both HTTP wrappers are monkeypatched in tests.

---

## Constants (defined at top of `scripts/competitor_research.py`)

```python
# --- Network / SERP ---
SERP_LIMIT = 200                       # iTunes Search top-N per token
SERP_TIMEOUT_S = 20
SERP_RETRIES = 4

# --- Filtering ---
MIN_OUTRANK_COUNT = 3                  # rival must outrank on >= this many tokens
MAX_CANDIDATES_BEFORE_LLM = 25         # Phase B truncates to top-N by threat before LLM filter

# --- LLM input ---
DESCRIPTION_TRUNCATE = 200             # chars of description shown to LLM per candidate

# --- Reporting ---
TOP_N_RIVALS = 10                      # max rivals in final report
MIN_RIVALS_FOR_REPORT = 3              # below this, markdown shows evidence-thin warning
TOP_K_KEYWORDS_PER_CARD = 3            # rivals' outranked_keywords shown per markdown card

# --- Scoring ---
SELF_NORANK_CEILING = 200              # when self is not in top-200, treat rank as this
```

---

## Task 1: Skeleton + smoke test

**Files:**
- Create: `scripts/competitor_research.py`
- Create: `tests/test_competitor_research.py`

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_competitor_research.py
"""Tests for competitor_research."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))


def test_module_imports():
    import competitor_research  # noqa: F401


def test_constants_match_spec():
    import competitor_research as cr
    assert cr.SERP_LIMIT == 200
    assert cr.MIN_OUTRANK_COUNT == 3
    assert cr.MAX_CANDIDATES_BEFORE_LLM == 25
    assert cr.DESCRIPTION_TRUNCATE == 200
    assert cr.TOP_N_RIVALS == 10
    assert cr.MIN_RIVALS_FOR_REPORT == 3
    assert cr.TOP_K_KEYWORDS_PER_CARD == 3
    assert cr.SELF_NORANK_CEILING == 200
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: `ModuleNotFoundError: No module named 'competitor_research'`

- [ ] **Step 3: Create minimal module with constants**

```python
# scripts/competitor_research.py
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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): module skeleton + constants

Empty module with all spec-defined constants and import path setup.
Tests verify constants match spec values.
"
```

---

## Task 2: `fetch_primary_genre_id` with cache

The app's `primary_genre_id` is needed for the genre hard filter. It is not in `apps_full.json` (verified), so we fetch via iTunes Lookup and cache indefinitely.

**Files:**
- Modify: `scripts/competitor_research.py` (add function)
- Modify: `tests/test_competitor_research.py` (add tests)

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def test_fetch_primary_genre_id_hits_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    cache_path.write_text(json.dumps({
        "1482080766|us": {"primaryGenreId": 6007, "fetched_at": "2026-05-16T00:00:00Z"}
    }))
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    def fail_get(*args, **kwargs):
        raise AssertionError("should not call network when cached")
    monkeypatch.setattr(cr.requests, "get", fail_get)

    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007


def test_fetch_primary_genre_id_calls_lookup_and_caches(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    class FakeResp:
        status_code = 200
        ok = True
        def json(self):
            return {"resultCount": 1, "results": [{"primaryGenreId": 6007}]}
        def raise_for_status(self):
            pass

    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResp()
    monkeypatch.setattr(cr.requests, "get", fake_get)

    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007
    assert len(calls) == 1
    assert "lookup" in calls[0][0]
    assert calls[0][1] == {"id": "1482080766", "country": "US"}

    # Second call hits cache, not network
    calls.clear()
    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007
    assert calls == []

    # Persisted to disk
    on_disk = json.loads(cache_path.read_text())
    assert on_disk["1482080766|us"]["primaryGenreId"] == 6007


def test_fetch_primary_genre_id_raises_when_lookup_empty(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    class FakeResp:
        status_code = 200
        ok = True
        def json(self):
            return {"resultCount": 0, "results": []}
        def raise_for_status(self):
            pass

    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: FakeResp())

    import pytest
    with pytest.raises(RuntimeError, match="iTunes Lookup returned no result"):
        cr.fetch_primary_genre_id("9999999999", "US")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_fetch_primary_genre_id_hits_cache -v`
Expected: `AttributeError: module 'competitor_research' has no attribute 'fetch_primary_genre_id'`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): fetch_primary_genre_id with persistent cache

iTunes Lookup wrapper, indefinite cache by (itunes_id, country).
Hard-fails on empty result so genre filter cannot silently skip.
"
```

---

## Task 3: `build_phase_a` + `cmd_analyze`

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def _stub_app(itunes_id="111", bundle_id="com.demo", name="Demo",
              primary_locale="en-US", title="Demo App", subtitle="Demo sub",
              keywords="alpha,beta,gamma") -> dict:
    return {
        "id": itunes_id,
        "core": {"name": name, "bundleId": bundle_id, "primaryLocale": primary_locale},
        "appInfo": {
            "localizations": [
                {"locale": primary_locale, "name": title, "subtitle": subtitle},
            ],
        },
        "versions": [{
            "attributes": {"createdDate": "2026-05-01T00:00:00Z", "platform": "IOS"},
            "localizations": [
                {"locale": primary_locale, "keywords": keywords,
                 "name": title, "subtitle": subtitle},
            ],
        }],
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }


def _row(app_id, country, ptid="1F", units="1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def test_build_phase_a_returns_full_schema(monkeypatch):
    import competitor_research as cr

    monkeypatch.setattr(cr, "fetch_primary_genre_id", lambda iid, c: 6007)

    app = _stub_app()
    sales_cache = {"2026-05-10": [_row("111", "US"), _row("111", "US")]}
    out = cr.build_phase_a(app, sales_cache, today=dt.date(2026, 5, 13))

    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "platform", "market",
        "primary_genre_id", "locale", "downloads_30d_in_market",
        "generated_at", "raw",
    }
    assert out["app"] == "Demo"
    assert out["app_id"] == "111"
    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "US"
    assert out["primary_genre_id"] == 6007
    assert out["locale"] == "en-US"
    assert out["downloads_30d_in_market"] == 2
    assert out["raw"]["title"] == "Demo App"
    assert out["raw"]["subtitle"] == "Demo sub"
    assert out["raw"]["keywords"] == "alpha,beta,gamma"


def test_cmd_analyze_writes_phase_a_file(monkeypatch, tmp_path):
    import competitor_research as cr

    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"
    apps_full.write_text(json.dumps({"apps": [_stub_app(name="Demo")]}))
    sales.write_text("{}")

    monkeypatch.setattr(cr, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(cr, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cr, "fetch_primary_genre_id", lambda iid, c: 6007)

    rc = cr.cmd_analyze("Demo")
    assert rc == 0

    out_path = tmp_path / "phase_a_competitors_demo_us.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["primary_genre_id"] == 6007


def test_cmd_analyze_returns_2_when_app_not_found(monkeypatch, tmp_path):
    import competitor_research as cr

    apps_full = tmp_path / "apps_full.json"
    apps_full.write_text(json.dumps({"apps": []}))
    sales = tmp_path / "sales_cache.json"
    sales.write_text("{}")
    monkeypatch.setattr(cr, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(cr, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)

    assert cr.cmd_analyze("NoSuchApp") == 2
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_build_phase_a_returns_full_schema -v`
Expected: `AttributeError: module 'competitor_research' has no attribute 'build_phase_a'`

- [ ] **Step 3: Implement helpers + cmd_analyze**

```python
# Append to scripts/competitor_research.py

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
```

`count_downloads_in_window` is defined locally in the code block above (not imported) because the equivalent counting logic in `feature_ideate.py` is private to `pick_primary_market`. The local definition mirrors that same install filter for consistency.

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: all passing (8 total)

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): build_phase_a + cmd_analyze

Resolves app via aso_optimize_v2.find_app, picks main market via
feature_ideate.pick_primary_market, fetches primary_genre_id via Lookup,
writes phase_a_competitors_<slug>.json.
"
```

---

## Task 4: `rank_keyword_with_details` (SERP fetch with full metadata + cache)

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def _fake_serp_response(entries):
    """entries: list of (track_id, bundle_id, name, genre_id, rating, count, desc)"""
    class FakeResp:
        status_code = 200
        ok = True
        def __init__(self, results):
            self._results = results
        def json(self):
            return {"resultCount": len(self._results), "results": self._results}
        def raise_for_status(self):
            pass
    results = []
    for tid, bid, name, gid, rating, rcount, desc in entries:
        results.append({
            "trackId": tid, "bundleId": bid, "trackName": name,
            "primaryGenreId": gid, "averageUserRating": rating,
            "userRatingCount": rcount, "description": desc,
        })
    return FakeResp(results)


def test_rank_keyword_with_details_parses_serp(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: _fake_serp_response([
        (100, "com.a", "App A", 6007, 4.5, 1000, "desc A here"),
        (101, "com.b", "App B", 6007, 4.7, 5000, "desc B here"),
    ]))

    out = cr.rank_keyword_with_details("便签", country="CN", entity="software")
    assert len(out) == 2
    assert out[0] == {
        "itunes_id": "100", "bundle_id": "com.a", "name": "App A",
        "primary_genre_id": 6007, "rating": 4.5, "review_count": 1000,
        "description": "desc A here", "rank_in_serp": 1,
    }
    assert out[1]["rank_in_serp"] == 2


def test_rank_keyword_with_details_uses_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    cache_path.write_text(json.dumps({
        "software|cn|便签": {
            "fetched_at": "2026-05-16T00:00:00Z",
            "entries": [{
                "itunes_id": "100", "bundle_id": "com.a", "name": "App A",
                "primary_genre_id": 6007, "rating": 4.5, "review_count": 1000,
                "description": "desc", "rank_in_serp": 1,
            }],
        },
    }))
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)

    def fail_get(*a, **kw):
        raise AssertionError("must not call network when cached")
    monkeypatch.setattr(cr.requests, "get", fail_get)

    out = cr.rank_keyword_with_details("便签", country="CN", entity="software")
    assert len(out) == 1
    assert out[0]["itunes_id"] == "100"


def test_rank_keyword_with_details_persists_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: _fake_serp_response([
        (100, "com.a", "App A", 6007, 4.5, 1000, "desc"),
    ]))

    cr.rank_keyword_with_details("便签", country="CN", entity="software")
    on_disk = json.loads(cache_path.read_text())
    assert "software|cn|便签" in on_disk
    assert on_disk["software|cn|便签"]["entries"][0]["itunes_id"] == "100"
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_rank_keyword_with_details_parses_serp -v`
Expected: `AttributeError`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

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
    if key in cache and "entries" in cache[key]:
        return cache[key]["entries"]

    params = {"term": keyword, "country": country.upper(),
              "entity": entity, "limit": SERP_LIMIT}
    last_exc: Exception | None = None
    for attempt in range(SERP_RETRIES):
        try:
            r = requests.get(ITUNES_BASE, params=params, timeout=SERP_TIMEOUT_S)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            if not r.ok:
                cache[key] = {"_error": r.status_code, "entries": []}
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
    cache[key] = {"_error": f"{type(last_exc).__name__}", "entries": []}
    _save_json_cache(SERP_DETAILS_CACHE_PATH, cache)
    return []
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): rank_keyword_with_details with SERP cache

iTunes Search top-200 wrapper preserving full per-entry metadata.
Persists to data/serp_details_cache.json. Returns [] on error so
downstream aggregation can skip the failed keyword.
"
```

---

## Task 5: `collect_outrankers_for_token` + `aggregate_rivals`

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def _serp_entry(tid, bid, name, rank, genre=6007, rating=4.0, rcount=100, desc="d"):
    return {
        "itunes_id": str(tid), "bundle_id": bid, "name": name,
        "primary_genre_id": genre, "rating": rating, "review_count": rcount,
        "description": desc, "rank_in_serp": rank,
    }


def test_collect_outrankers_when_self_ranked():
    import competitor_research as cr
    serp = [
        _serp_entry(10, "com.rivalA", "Rival A", rank=1),
        _serp_entry(11, "com.rivalB", "Rival B", rank=2),
        _serp_entry(99, "com.self",   "Self",   rank=5),
        _serp_entry(12, "com.below",  "Below",  rank=6),
    ]
    out = cr.collect_outrankers_for_token(serp, self_bundle_id="com.self")
    assert out["self_rank"] == 5
    assert {r["bundle_id"] for r in out["outrankers"]} == {"com.rivalA", "com.rivalB"}


def test_collect_outrankers_when_self_unranked():
    import competitor_research as cr
    serp = [
        _serp_entry(10, "com.a", "A", rank=1),
        _serp_entry(11, "com.b", "B", rank=2),
    ]
    out = cr.collect_outrankers_for_token(serp, self_bundle_id="com.missing")
    assert out["self_rank"] is None
    assert len(out["outrankers"]) == 2  # both higher than ceiling 200


def test_collect_outrankers_returns_empty_for_empty_serp():
    import competitor_research as cr
    out = cr.collect_outrankers_for_token([], self_bundle_id="com.self")
    assert out == {"self_rank": None, "outrankers": []}


def test_aggregate_rivals_combines_across_tokens():
    import competitor_research as cr

    per_token = {
        "便签": {
            "self_rank": 10,
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=3),
                _serp_entry(101, "com.b", "App B", rank=5),
            ],
            "popularity": 80,
        },
        "桌面便签": {
            "self_rank": None,  # self unranked -> ceiling 200
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=2),
            ],
            "popularity": 60,
        },
    }

    rivals = cr.aggregate_rivals(per_token)
    by_id = {r["itunes_id"]: r for r in rivals}

    a = by_id["100"]
    assert a["name"] == "App A"
    assert a["outrank_count"] == 2
    assert sorted([k["keyword"] for k in a["outranked_keywords"]]) == ["便签", "桌面便签"]
    # 便签: self=10, rival=3, diff=7, pop=80
    # 桌面便签: self=200, rival=2, diff=198, pop=60
    assert a["threat_score"] == 80 * 7 + 60 * 198
    # avg diff = (7 + 198) / 2
    assert a["avg_rank_diff"] == statistics.mean([7, 198])

    b = by_id["101"]
    assert b["outrank_count"] == 1
    assert b["outranked_keywords"][0]["self_rank"] == 10
    assert b["outranked_keywords"][0]["rival_rank"] == 5


def test_aggregate_rivals_truncates_description_to_200_chars():
    import competitor_research as cr
    long_desc = "x" * 500
    per_token = {
        "k": {
            "self_rank": 10,
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=3, desc=long_desc),
            ],
            "popularity": 50,
        }
    }
    rivals = cr.aggregate_rivals(per_token)
    assert len(rivals[0]["description_short"]) == 200
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_collect_outrankers_when_self_ranked -v`
Expected: `AttributeError`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): collect_outrankers + aggregate_rivals

Per-keyword extraction of rivals ranked strictly above self (treats
unranked-self as ceiling 200). Cross-token aggregation builds the
per-rival record with outranked_keywords, threat_score, avg_rank_diff.
"
```

---

## Task 6: `filter_by_genre_and_density` + isolated `score_threat` test

`threat_score` is already computed inside `aggregate_rivals`, but a separate test pins the formula independently so future refactors cannot silently change it.

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def test_threat_score_formula_pin():
    """Pin the formula: sum(popularity * diff) over outranked_keywords."""
    import competitor_research as cr
    rival = {
        "outranked_keywords": [
            {"popularity": 76, "diff": 197},   # unranked self vs rival #3
            {"popularity": 64, "diff": 10},    # self #15 vs rival #5
            {"popularity": 53, "diff": 6},     # self #8 vs rival #2
        ],
    }
    expected = 76 * 197 + 64 * 10 + 53 * 6
    assert cr.score_threat(rival) == expected


def _rival(itunes_id, genre, outrank_count, threat=100):
    return {
        "itunes_id": str(itunes_id),
        "name": f"R{itunes_id}",
        "primary_genre_id": genre,
        "outrank_count": outrank_count,
        "threat_score": threat,
        "outranked_keywords": [{"keyword": "k", "popularity": 1, "diff": 1,
                                "self_rank": 200, "rival_rank": 1}
                               for _ in range(outrank_count)],
    }


def test_filter_drops_cross_genre():
    import competitor_research as cr
    rivals = [
        _rival(1, genre=6007, outrank_count=5),
        _rival(2, genre=6014, outrank_count=5),  # games
    ]
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert [r["itunes_id"] for r in out] == ["1"]


def test_filter_drops_below_density_threshold():
    import competitor_research as cr
    rivals = [
        _rival(1, genre=6007, outrank_count=2),  # below 3
        _rival(2, genre=6007, outrank_count=3),  # exactly 3
        _rival(3, genre=6007, outrank_count=10),
    ]
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert {r["itunes_id"] for r in out} == {"2", "3"}


def test_filter_sorts_by_threat_desc_and_truncates_to_max_candidates():
    import competitor_research as cr
    rivals = [_rival(i, genre=6007, outrank_count=3, threat=i * 10)
              for i in range(1, 31)]  # 30 rivals
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert len(out) == cr.MAX_CANDIDATES_BEFORE_LLM  # 25
    # Sorted desc by threat
    threats = [r["threat_score"] for r in out]
    assert threats == sorted(threats, reverse=True)
    # The top should be itunes_id "30" (highest threat)
    assert out[0]["itunes_id"] == "30"
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_threat_score_formula_pin -v`
Expected: `AttributeError`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): score_threat + hard filters

Pinned threat-score formula test. Genre + density filters with
deterministic truncation to MAX_CANDIDATES_BEFORE_LLM.
"
```

---

## Task 7: `build_phase_b` + `cmd_rank`

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def test_build_phase_b_happy_path(monkeypatch):
    import competitor_research as cr

    phase_a = {
        "app": "Demo", "app_id": "111", "bundle_id": "com.self",
        "market": "CN", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }
    tokens = ["便签", "桌面便签", "记事本"]

    serps = {
        "便签": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=1, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=2, genre=6007),
            _serp_entry(99, "com.self",   "Self",   rank=10, genre=6007),
            _serp_entry(12, "com.gameX",  "GameX",  rank=3, genre=6014),  # cross-genre
        ],
        "桌面便签": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=1, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=3, genre=6007),
            _serp_entry(13, "com.rivalC", "Rival C", rank=5, genre=6007),
            # self not present
        ],
        "记事本": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=2, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=4, genre=6007),
            _serp_entry(99, "com.self",   "Self",   rank=8, genre=6007),
        ],
    }
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": serps[k])
    monkeypatch.setattr(cr, "_lookup_popularity",
                        lambda kw, region: 50)

    out = cr.build_phase_b(phase_a, tokens)
    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "market", "primary_genre_id",
        "generated_at", "tokens", "self_ranks", "candidates",
    }
    assert out["tokens"] == tokens
    assert out["self_ranks"] == {"便签": 10, "桌面便签": None, "记事本": 8}
    cand_by_id = {c["itunes_id"]: c for c in out["candidates"]}
    # Rival A outranks self on both tokens (rank 1 < 10, rank 1 < 200)
    assert "10" in cand_by_id
    # Rival B outranks self on both (rank 2 < 10, rank 3 < 200)
    assert "11" in cand_by_id
    # Rival C only outranks on 桌面便签 (count=1, below MIN_OUTRANK_COUNT=3) -> dropped
    assert "13" not in cand_by_id
    # GameX is cross-genre -> dropped
    assert "12" not in cand_by_id


def test_build_phase_b_empty_when_no_rivals_pass_filters(monkeypatch):
    """Spec §13 edge case: an app whose SERPs yield no qualifying rivals.
    Result is an empty candidates list — Claude will render the
    'evidence-thin' warning. The script does not crash."""
    import competitor_research as cr
    phase_a = {
        "app": "Lonely", "app_id": "111", "bundle_id": "com.lonely",
        "market": "US", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": [])
    monkeypatch.setattr(cr, "_lookup_popularity", lambda kw, region: 50)
    out = cr.build_phase_b(phase_a, tokens=["a", "b"])
    assert out["candidates"] == []
    assert out["self_ranks"] == {"a": None, "b": None}


def test_cmd_rank_writes_phase_b(monkeypatch, tmp_path):
    import competitor_research as cr

    phase_a_path = tmp_path / "phase_a_competitors_demo_us.json"
    phase_a_path.write_text(json.dumps({
        "app": "Demo", "app_id": "111", "bundle_id": "com.self",
        "market": "US", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }))
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": [
                            _serp_entry(10, "com.r", "R", rank=1, genre=6007),
                            _serp_entry(99, "com.self", "Self", rank=20, genre=6007),
                        ])
    monkeypatch.setattr(cr, "_lookup_popularity", lambda kw, region: 50)

    rc = cr.cmd_rank("Demo", tokens=["a", "b", "c"])
    assert rc == 0
    out = tmp_path / "phase_b_competitors_demo_us.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["tokens"] == ["a", "b", "c"]
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["itunes_id"] == "10"
    assert data["candidates"][0]["outrank_count"] == 3
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_build_phase_b_happy_path -v`
Expected: `AttributeError`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

from keyword_local import lookup_popularity as _kw_lookup_popularity  # noqa: E402


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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 23 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): build_phase_b + cmd_rank

End-to-end Phase B: fetches SERP per token, collects outrankers,
aggregates, filters, writes phase_b_competitors_<slug>.json.
cmd_rank locates the matching phase_a by query.
"
```

---

## Task 8: `main()` dispatch + show-a/show-b debug commands

**Files:**
- Modify: `scripts/competitor_research.py`
- Modify: `tests/test_competitor_research.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_competitor_research.py

def test_main_dispatches_analyze(monkeypatch):
    import competitor_research as cr
    captured = {}
    monkeypatch.setattr(cr, "cmd_analyze",
                        lambda q: captured.setdefault("analyze", q) or 0)
    rc = cr.main(["analyze", "Demo"])
    assert rc == 0
    assert captured["analyze"] == "Demo"


def test_main_dispatches_rank_with_tokens(monkeypatch):
    import competitor_research as cr
    captured = {}
    def fake_rank(q, tokens):
        captured["q"] = q
        captured["tokens"] = tokens
        return 0
    monkeypatch.setattr(cr, "cmd_rank", fake_rank)
    rc = cr.main(["rank", "Demo", "--tokens", "便签,桌面便签,memo"])
    assert rc == 0
    assert captured["q"] == "Demo"
    assert captured["tokens"] == ["便签", "桌面便签", "memo"]


def test_main_help_when_no_args(capsys):
    import competitor_research as cr
    rc = cr.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Usage" in captured.out or "Usage" in captured.err


def test_show_a_prints_summary(monkeypatch, tmp_path, capsys):
    import competitor_research as cr
    phase_a_path = tmp_path / "phase_a_competitors_demo_us.json"
    phase_a_path.write_text(json.dumps({
        "app": "Demo", "market": "US", "primary_genre_id": 6007,
        "raw": {"title": "Demo App", "subtitle": "sub", "keywords": "a,b,c"},
    }))
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    rc = cr.cmd_show_a("Demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Demo" in out
    assert "6007" in out
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python3 -m pytest tests/test_competitor_research.py::test_main_dispatches_analyze -v`
Expected: `AttributeError: module 'competitor_research' has no attribute 'main'`

- [ ] **Step 3: Implement**

```python
# Append to scripts/competitor_research.py

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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 -m pytest tests/test_competitor_research.py -v`
Expected: 27 passed

- [ ] **Step 5: Smoke-check the full pytest suite still green**

Run: `python3 -m pytest`
Expected: previously-passing 86 + new 27 = 113 passed (no regressions)

- [ ] **Step 6: Commit**

```bash
git add scripts/competitor_research.py tests/test_competitor_research.py
git commit -m "feat(competitor-research): main dispatch + show-a/show-b debug

argparse subcommands: analyze, rank, show-a, show-b. Help-on-no-args
exits 2. show-a/show-b print a single-line summary for quick inspection.
"
```

---

## Task 9: Skill documentation (`skills/competitor-research/SKILL.md`)

This is the Claude-side process doc — no code, but it is the single source of truth for how Claude conducts the conversation flow (tokenize prompt, relevance filter prompt, markdown rendering rules).

**Files:**
- Create: `skills/competitor-research/SKILL.md`

- [ ] **Step 1: Create the skill directory and file**

```bash
mkdir -p skills/competitor-research
```

- [ ] **Step 2: Write the SKILL.md**

```markdown
---
name: competitor-research
description: Identify the top 5-10 rivals outranking a single app on its own core keywords. Use when the user asks for competitor research, "找竞品" / "找对手" / "跑竞争对手分析", or runs /appmate-competitors.
---

# Competitor Research Workflow

> Single authoritative reference. Re-read before every run. Pure-SERP approach: zero RAG, zero AppMate semantic search. The script holds all the data-layer logic; Claude does keyword tokenization and a single batched LLM relevance pass.

## Step 0 — Prerequisites

Run before anything else:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and direct them to `/appmate-setup`. Do not invoke any other step of this skill.

## One-line summary

Single app → script writes phase_a (raw metadata + primary_genre_id) → **LLM tokenizes keywords** → script fetches iTunes Search top-200 per token, collects rivals outranking self, aggregates, scores, hard-filters by genre+density, writes phase_b → **LLM does batched relevance pass on name + description[:200]** → script writes final JSON, Claude renders Chinese markdown, pastes back into conversation.

## Difference from existing skills

| | `competitor-research` (this skill) | `feature-ideation` / `growth-strategy` |
|---|---|---|
| Signal | iTunes Search SERP overlap, strict outrank | AppMate RAG semantic similarity |
| Output role | the deliverable itself | transient input evidence |
| Persistence | `data/competitors_<slug>.json` | not cached |
| RAG dependency | **none** | required |

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | user says "find competitors for `<app>`" / "跑 `<app>` 的竞品" / runs `/appmate-competitors <app>` |
| **Input** | `data/apps_full.json` + `data/sales_cache.json` |
| **Output** | `data/phase_a_competitors_<slug>.json`, `data/phase_b_competitors_<slug>.json`, `data/competitors_<slug>.json`, `data/competitors_<slug>.md` + **Claude pastes the full markdown back into the conversation** |
| **User intervention** | 2 (trigger + LLM tokenize&filter, both in the same Claude turn) |

## Workflow (3 stages)

### Stage 1 — Script: phase_a

```bash
python3 scripts/competitor_research.py analyze "<app>"
```

App argument: App Store ID / bundle ID / SKU / fuzzy name. Resolves via the same `find_app` used by other skills.

Writes `data/phase_a_competitors_<slug>.json`. If credentials are missing or app is not found, exits 2 with a clear message — do not proceed.

### Stage 2 — Claude: tokenize keywords

Read `data/phase_a_competitors_<slug>.json`. Look at `raw.title`, `raw.subtitle`, `raw.keywords` for the main-market locale.

**Tokenization rules** (identical to `aso-daily-report` Step 2):
- Cut real ASO words with Chinese semantics.
- Recognize compound words (`桌面便签`, `云便签`).
- Reject CJK runs ≥ 6 characters (almost always invalid mashed runs).
- Recognize brand variants, typos, and English-Chinese fusions.
- De-duplicate case-insensitively.

Output a comma-separated token list and pass it to the script:

```bash
python3 scripts/competitor_research.py rank "<app>" --tokens "tok1,tok2,tok3,..."
```

This writes `data/phase_b_competitors_<slug>.json` with up to 25 candidates that survived the genre + density hard filters.

### Stage 3 — Claude: batched relevance filter + render

Read `data/phase_b_competitors_<slug>.json`. For each candidate, look at `name`, `description_short`, and `outranked_keywords[:3]`.

**One batched judgement call.** For ALL candidates in one pass, decide for each:

- `keep: true` + one Chinese sentence reason explaining why the rival's target users overlap with the app's
- `keep: false` + one Chinese sentence reason explaining why they do not

Example reasons:
- keep: `「XX便签」描述同样主打桌面快速记事,目标用户重叠`
- drop: `描述显示是情绪打卡 app,跟便签场景不重叠`

**Compose the final JSON** `data/competitors_<slug>.json`:

```json
{
  "app": "...",
  "app_id": "...",
  "bundle_id": "...",
  "market": "CN",
  "primary_genre_id": 6007,
  "generated_at": "...",
  "tokens": ["..."],
  "self_ranks": {"...": ...},
  "filtered": [
    {... full candidate fields from phase_b ...,
     "relevance_keep": true,
     "relevance_reason": "..."}
  ],
  "dropped_by_relevance": [
    {"itunes_id": "...", "name": "...", "threat_score": ...,
     "drop_reason": "..."}
  ]
}
```

`filtered` is sorted by `threat_score` desc, truncated to 10. `dropped_by_relevance` is diagnostic only — **never rendered in markdown**.

If fewer than 3 candidates pass relevance, the markdown shows an evidence-thin warning at the top.

## Markdown report template (v1 — follow exactly)

Rendered in **Chinese** by design.

```markdown
# 🎯 <App 名> · 最值得研究的竞品

> ⚠️ <evidence-thin warning — only when kept < 3>

**主市场**: <flag> <country>  ·  **30 天下载**: <N>  ·  **检索核心词**: <X> 个

---

## 1. <对手名> · ★<rating> (<review_count> 评)

在你 **<outrank_count> 个词**上排名高过你,平均高 **<round avg_rank_diff> 名**

| 关键词 | 你 | 他 | 高你 | 词热度 |
|---|:-:|:-:|:-:|:-:|
| `<kw1>` | <#N 或 未上榜> | **#<n>** | <diff> | <pop> <🔥 if ≥50> |
| `<kw2>` | ... | ... | ... | ... |
| `<kw3>` | ... | ... | ... | ... |

> **为什么是他**: <relevance_reason 一句中文>

---

## 2. <对手名> · ...
... (5–10 rivals total, top 3 keywords each) ...

---

**重点 <N> 个**: #X / #Y / #Z — <one-sentence summary of each top rival's core threat>

要详细看哪个的关键词布局?告诉我编号,我可以用 /appmate-aso-optimize 拉出他的元数据对照。
```

## 9 inviolable rules

1. Each rival is its own `H2 (##)` block — low-density layout.
2. Keywords wrapped in backticks `` `桌面便签` ``.
3. Column headers are full Chinese words. **Never** use single-letter abbreviations `T/S/K/X`.
4. "为什么是他" uses a `>` blockquote.
5. The keywords table shows **exactly top 3** outranked keywords per rival — full list is in JSON.
6. **`dropped_by_relevance` never appears in markdown.** JSON only.
7. Sort rivals by `threat_score` descending.
8. Closing "重点 N 个" + "详细看哪个" guidance is required.
9. **Paste the full markdown back into the conversation.** "Saved to data/competitors_<slug>.md" alone is not allowed.

## Data source conventions

| Dimension | Source |
|---|---|
| Pick app | `data/apps_full.json` via `aso_optimize_v2.find_app` |
| Main market | the country with the largest 30-day downloads in `sales_cache.json` |
| primary_genre_id | iTunes Lookup, cached in `data/itunes_lookup_cache.json` (no TTL) |
| SERP top-200 per token | iTunes Search API (`https://itunes.apple.com/search`), cached in `data/serp_details_cache.json` |
| Keyword popularity | `keyword_local.lookup_popularity` (static `keyword_reference_<region>.json`) |
| Tokenization | **LLM semantic split** (not regex / jieba) |
| Relevance filter | **LLM batched call** over name + description[:200] |

## Key parameters

| Parameter | Value | Note |
|---|---|---|
| `SERP_LIMIT` | 200 | top-N per iTunes Search call |
| `MIN_OUTRANK_COUNT` | 3 | candidate must outrank on ≥ this many tokens |
| `MAX_CANDIDATES_BEFORE_LLM` | 25 | phase_b truncates to this |
| `DESCRIPTION_TRUNCATE` | 200 | chars shown to LLM per candidate |
| `TOP_N_RIVALS` | 10 | upper bound on `filtered` |
| `MIN_RIVALS_FOR_REPORT` | 3 | below this, ⚠️ evidence-thin warning |
| `TOP_K_KEYWORDS_PER_CARD` | 3 | per-card keyword table size in markdown |

## CLI

```bash
python3 scripts/competitor_research.py analyze "Sticky Note Pro"
python3 scripts/competitor_research.py rank    "Sticky Note Pro" --tokens "便签,桌面便签,sticky note,memo"
python3 scripts/competitor_research.py show-a  "Sticky Note Pro"
python3 scripts/competitor_research.py show-b  "Sticky Note Pro"
```

## Connection to existing workflows

- An `aso-daily-report` run that finds an app dropping out of top 20 on its own keyword → trigger this skill to see who took the slot.
- Use the resulting "重点 N 个" rivals to seed a follow-up `/appmate-aso-optimize <app>` run for keyword reshuffling.
- **No downstream skill consumes `competitors_<slug>.json` yet** — wiring `feature-ideation` / `growth-strategy` is a separate task (see spec §15).

## Known limits

- LLM tokenization cannot run unattended (cron-incompatible).
- SERP changes hourly; the 7-day rank cache may be stale on borderline rivals.
- An app with ≤ 2 distinct tokens cannot reach `MIN_OUTRANK_COUNT = 3` → empty result.
- Drop reasons in `dropped_by_relevance` vary across runs on borderline cases (audit via the JSON).

## Checklist (must pass before pasting back)

### Content
- [ ] Main list of 5–10 rivals (≥3 to skip warning, else show ⚠️)
- [ ] Each card shows exactly top 3 keywords
- [ ] Sorted by `threat_score` descending

### Language
- [ ] Chinese throughout the rendered output
- [ ] **No** single-letter abbreviations `T/S/K/X`
- [ ] No technical jargon (no "SERP" / "RAG" / "outrank" in user-visible text)
- [ ] Keywords wrapped in backticks

### Structure
- [ ] Each rival uses `## N. <名>`
- [ ] "为什么是他" uses `>` blockquote
- [ ] `dropped_by_relevance` NOT rendered
- [ ] Closing "重点 N 个" + "详细看哪个" line present

### Delivery
- [ ] `data/competitors_<slug>.json` written
- [ ] `data/competitors_<slug>.md` written
- [ ] **Full markdown pasted back into the conversation** (not just "saved")
```

- [ ] **Step 3: Commit**

```bash
git add skills/competitor-research/SKILL.md
git commit -m "docs(competitor-research): SKILL.md process documentation

Single authoritative reference for the Claude-side conversation flow:
tokenize prompt, batched relevance filter prompt, markdown template,
9 inviolable rules, checklist.
"
```

---

## Task 10: Slash command + README

**Files:**
- Create: `commands/appmate-competitors.md`
- Modify: `README.md`

- [ ] **Step 1: Look at an existing slash command for the format**

Run: `cat commands/appmate-feature-ideas.md`
Use it as the structural template.

- [ ] **Step 2: Create the slash command**

```markdown
# commands/appmate-competitors.md
---
description: Find the most valuable competitors for an app — rivals who outrank you on your own keywords.
---

Run the `competitor-research` skill for the app specified as an argument.

**Argument**: `$ARGUMENTS` — App Store ID / bundle ID / SKU / fuzzy app name (one app).

**Process**:

1. Verify credentials by running `python3 scripts/appmate_config.py check`. If exit code ≠ 0, stop and instruct the user to run `/appmate-setup`.
2. Run `python3 scripts/competitor_research.py analyze "$ARGUMENTS"` to write `data/phase_a_competitors_<slug>.json`.
3. Read phase_a, perform LLM keyword tokenization per `skills/competitor-research/SKILL.md` Stage 2 rules.
4. Run `python3 scripts/competitor_research.py rank "$ARGUMENTS" --tokens "<comma-separated tokens>"` to write `data/phase_b_competitors_<slug>.json`.
5. Read phase_b, perform the batched LLM relevance filter per Stage 3 rules.
6. Write `data/competitors_<slug>.json` and render `data/competitors_<slug>.md` per the markdown template.
7. **Paste the full markdown back into the conversation.** Do not say "saved" alone.

Refer to `skills/competitor-research/SKILL.md` for the full rules, prompts, and checklist.
```

- [ ] **Step 3: Update README — change "6 workflows" to "7 workflows" and add a row**

Open `README.md`. Locate the line:

```markdown
## The 6 workflows
```

Change it to:

```markdown
## The 7 workflows
```

Locate the workflows table (the one with the `Command | What it does | Typical runtime` header). After the `/appmate-feature-ideas` row, insert a new row:

```markdown
| `/appmate-competitors <app>` | Find the top 5-10 rivals outranking one app on its own core keywords. Pure iTunes Search SERP overlap, hard-filtered by category + outrank density, LLM relevance pass on name+description. Outputs a Chinese markdown report + a stable JSON (`data/competitors_<slug>.json`) for future downstream skills to consume. | ~1 min |
```

Then in the "Concrete usage" code block, add an example:

```
/appmate-competitors Sticky Note Pro
```

- [ ] **Step 4: Verify formatting**

Run: `grep -n "7 workflows\|appmate-competitors" README.md`
Expected: at least three matches (heading, table row, usage example).

- [ ] **Step 5: Final smoke test of full suite**

Run: `python3 -m pytest`
Expected: 86 + 26 = 112 passed (no regressions).

Run: `python3 scripts/competitor_research.py`
Expected: usage help text, exit code 2.

- [ ] **Step 6: Commit**

```bash
git add commands/appmate-competitors.md README.md
git commit -m "feat(competitor-research): /appmate-competitors slash command + README

Adds the slash command that wires the skill, and promotes the README
workflows table from 6 to 7 entries.
"
```

---

## Verification before declaring done

After all 10 tasks are committed, verify the spec coverage by running:

- [ ] `python3 -m pytest` → 113+ passed, no regressions
- [ ] `ls skills/competitor-research/SKILL.md commands/appmate-competitors.md scripts/competitor_research.py tests/test_competitor_research.py` → all exist
- [ ] `grep -c "7 workflows\|appmate-competitors" README.md` → ≥ 3
- [ ] `python3 scripts/competitor_research.py analyze "<a real app>"` end-to-end on a real credentialed install (manual smoke, not automated)

Do not run `/plugin install` to re-deploy — the user installs from GitHub master, so the test is "did the worktree changes pass and look correct," not "is the local install updated." Per the user's memory `单人 repo 直推 master`, when shipping push directly to `origin master`.
