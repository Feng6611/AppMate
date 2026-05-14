# `feature_ideate.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Step 1 aggregation script that ingests reviews/competitors/ASO blindspots for a given app and emits `phase_a_feature_<slug>.json` for the LLM ideation step.

**Architecture:** Single CLI script `feature_ideate.py` with pure helper functions for each pipeline stage (market pick / review bucketing / competitor fetch / ASO blindspot compute) plus a thin `main()` that wires them. Helpers take explicit data inputs (not paths) so they're unit-testable without filesystem fixtures.

**Tech Stack:** Python 3, stdlib (json, datetime, re, pathlib, argparse), pytest, existing project modules (`aso_optimize_v2.find_app/slugify`, `appmate_rag_client.search`).

**Spec:** `MyFeatures/FEATURE_IDEATION_WORKFLOW.md` (Step 1 section)

**Out of scope:** Step 2 (LLM ideation) and Step 3 (rendering) — those live in the workflow doc, not in code.

---

## File Structure

| File | Responsibility |
|---|---|
| `feature_ideate.py` (create) | CLI entry + helpers: `pick_primary_market` / `bucket_reviews` / `fetch_competitors` / `compute_aso_blindspots` / `build_phase_a` / `main` |
| `tests/test_feature_ideate.py` (create) | Unit tests for each helper using inline fixtures (no FS / network) |

Helpers are **pure**: take dicts/lists in, return dicts/lists out. The only I/O lives in `main()` and the `fetch_competitors` wrapper (the latter is patched in tests).

---

## Constants (defined at top of `feature_ideate.py`)

```python
REVIEW_AGE_DAYS = 90
REVIEW_BUCKET_CAP = 50
NEG_RATING_MAX = 3
POS_RATING_MIN = 4
WISH_TRIGGERS = ["希望", "能否", "建议", "求", "请加", "不能", "为什么没有",
                 "wish", "would love", "please add", "hope", "could you"]
MIN_BODY_LEN = 10
COMPETITOR_TOP_K = 10
COMPETITOR_MIN_REVIEWS = 50
BLINDSPOT_POP_MIN = 40
BLINDSPOT_RANK_BAD = 50  # rank > 50 counts as "not covered"
BLINDSPOT_TOP_N = 10
```

---

## Task 1: Skeleton + smoke test

**Files:**
- Create: `feature_ideate.py`
- Create: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_feature_ideate.py
"""Tests for feature_ideate."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def test_module_imports():
    import feature_ideate  # noqa: F401
```

- [ ] **Step 2: Run test, expect FAIL**

Run: `pytest tests/test_feature_ideate.py::test_module_imports -v`
Expected: `ModuleNotFoundError: No module named 'feature_ideate'`

- [ ] **Step 3: Create minimal module**

```python
# feature_ideate.py
"""Step 1 aggregator for the feature ideation workflow.

See MyFeatures/FEATURE_IDEATION_WORKFLOW.md for the methodology.
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
BLINDSPOT_POP_MIN = 40
BLINDSPOT_RANK_BAD = 50
BLINDSPOT_TOP_N = 10
```

- [ ] **Step 4: Run test, expect PASS**

Run: `pytest tests/test_feature_ideate.py::test_module_imports -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): module skeleton + smoke test"
```

---

## Task 2: `pick_primary_market(app, sales_cache)` — main-market resolver

Spec rule (1a): downloads-max → primaryLocale country → US fallback. Pure function: takes the app dict + parsed sales_cache dict, returns 2-letter country code uppercase.

**Files:**
- Modify: `feature_ideate.py` (add function)
- Modify: `tests/test_feature_ideate.py` (add test block)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_ideate.py — append

import datetime as dt


def _row(app_id: str, country: str, ptid: str = "1F", units: str = "1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def test_pick_primary_market_uses_max_downloads_in_window():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "en-US"}}
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-10": [_row("111", "CN"), _row("111", "CN"), _row("111", "US")],
        "2026-05-09": [_row("111", "CN"), _row("111", "JP")],
    }
    assert pick_primary_market(app, cache, today=today) == "CN"


def test_pick_primary_market_ignores_updates_and_other_apps():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "ja"}}
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-10": [
            _row("222", "CN", units="999"),  # other app
            _row("111", "JP", ptid="7"),     # update, not install
            _row("111", "US"),
        ],
    }
    assert pick_primary_market(app, cache, today=today) == "US"


def test_pick_primary_market_falls_back_to_primary_locale_country():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "zh-Hans"}}
    today = dt.date(2026, 5, 13)
    cache = {}  # no sales data
    assert pick_primary_market(app, cache, today=today) == "CN"


def test_pick_primary_market_locale_without_region_uses_known_map():
    from feature_ideate import pick_primary_market

    # 'ja' -> JP, 'ko' -> KR, etc.
    for locale, expected in [("ja", "JP"), ("ko", "KR"), ("de-DE", "DE")]:
        app = {"id": "111", "core": {"primaryLocale": locale}}
        assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == expected


def test_pick_primary_market_ultimate_fallback_is_us():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {}}  # no primaryLocale at all
    assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == "US"
```

- [ ] **Step 2: Run tests, expect 5 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k pick_primary_market`
Expected: 5 failures (`ImportError: cannot import name 'pick_primary_market'`)

- [ ] **Step 3: Implement `pick_primary_market`**

Append to `feature_ideate.py`:

```python
# Install-counting PTIDs (mirrors sales_report.py)
INSTALL_PTIDS = {"1", "1F", "1T", "1E", "1EP", "1EU", "F1", "FI1"}

# Locale -> default country (when locale has no region, e.g. 'ja', 'ko')
LOCALE_DEFAULT_COUNTRY = {
    "ja": "JP", "ko": "KR", "zh-Hans": "CN", "zh-Hant": "TW",
    "en": "US", "fr": "FR", "de": "DE", "it": "IT", "es": "ES",
    "pt": "BR", "ru": "RU", "ar": "SA",
}


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
            if ptid not in INSTALL_PTIDS:
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
```

- [ ] **Step 4: Run tests, expect 5 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k pick_primary_market`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): pick_primary_market with downloads -> locale -> US fallback"
```

---

## Task 3: `bucket_reviews(reviews, today)` — negative / wishlist split

Spec rule (1b). Each input review is the shape stored in `apps_full.json` (top-level keys: `id, rating, title, body, reviewerNickname, createdDate, territory`).

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_ideate.py — append

def _review(rating, body, days_ago, title="", territory="CHN"):
    today = dt.date(2026, 5, 13)
    created = today - dt.timedelta(days=days_ago)
    return {
        "id": f"r{rating}{days_ago}",
        "rating": rating,
        "title": title,
        "body": body,
        "territory": territory,
        "createdDate": created.isoformat() + "T00:00:00-07:00",
    }


def test_bucket_reviews_negative_includes_low_ratings_with_long_body():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(1, "极差极差极差极差极差", 10),  # 10 chars CJK
        _review(2, "ok", 10),                    # too short, skip
        _review(3, "this is decent description here", 20),
        _review(4, "this is decent description here", 20),  # too high
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 2
    assert all(r["rating"] <= 3 for r in out["negative"])
    assert all(len(r["body"]) >= 10 for r in out["negative"])


def test_bucket_reviews_wishlist_requires_trigger_word():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(5, "great app overall", 5),                 # no trigger
        _review(5, "希望加分组功能", 5),                     # trigger zh
        _review(4, "please add dark mode support", 5),      # trigger en
        _review(4, "love it ok ok ok", 5),                  # no trigger
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["wishlist"]) == 2
    bodies = {r["body"] for r in out["wishlist"]}
    assert "希望加分组功能" in bodies
    assert "please add dark mode support" in bodies


def test_bucket_reviews_drops_reviews_older_than_90_days():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(1, "old complaint that is long enough", 100),  # too old
        _review(1, "recent complaint that is long enough", 10),
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 1
    assert "recent" in out["negative"][0]["body"]


def test_bucket_reviews_caps_each_bucket_at_50():
    from feature_ideate import bucket_reviews

    reviews = [_review(1, f"complaint {i} body content here", 1) for i in range(80)]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 50


def test_bucket_reviews_records_keep_minimal_schema():
    from feature_ideate import bucket_reviews

    reviews = [_review(2, "this body has enough chars", 1, title="bad", territory="USA")]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    r = out["negative"][0]
    assert set(r.keys()) == {"rating", "title", "body", "locale", "created_at"}
    assert r["locale"] == "USA"
    assert r["title"] == "bad"
```

- [ ] **Step 2: Run tests, expect 5 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k bucket_reviews`
Expected: 5 failures (no `bucket_reviews`)

- [ ] **Step 3: Implement `bucket_reviews`**

Append to `feature_ideate.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect 5 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k bucket_reviews`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): bucket_reviews splits negative + wishlist with 90d / cap-50"
```

---

## Task 4: `pick_competitor_seed(app, snapshots, country)` — seed keyword for RAG

Spec rule (1c): use the ASO keyword where the app is rank ≤ 10 and pop is highest. Fallback to the longest "real word" in the app's title.

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_ideate.py — append

def test_pick_competitor_seed_uses_best_ranked_high_pop_keyword():
    from feature_ideate import pick_competitor_seed

    bid = "com.example.app"
    snaps_latest = {
        bid: {
            "CN": {
                "便签": 4,         # rank 4
                "memo": 4,
                "云笔记": 50,      # rank > 10, skip
                "便利贴": 8,
            }
        }
    }
    pop_cache = {
        "cn|便签": {"popularity": 48},
        "cn|memo": {"popularity": 44},
        "cn|便利贴": {"popularity": 37},
    }
    app = {"core": {"name": "Sticky"}, "appInfo": {"localizations": []}}
    seed = pick_competitor_seed(app, snaps_latest, pop_cache, bundle_id=bid, country="CN")
    # 便签 has rank 4 (≤10) and highest pop (48)
    assert seed == "便签"


def test_pick_competitor_seed_falls_back_to_title_longest_word_when_no_aso_hit():
    from feature_ideate import pick_competitor_seed

    app = {
        "core": {"name": "Sticky Note Pro: Post-it&Memo"},
        "appInfo": {
            "localizations": [
                {"locale": "en-US", "name": "Sticky Note Pro: Post-it&Memo"}
            ]
        },
    }
    # Empty snapshots / cache
    seed = pick_competitor_seed(app, {}, {}, bundle_id="com.x", country="CN")
    # Longest ASCII alpha word in name -> "Sticky" (6) vs "Note" (4) vs "Pro" (3) vs "Memo" (4)
    assert seed == "Sticky"


def test_pick_competitor_seed_uses_locale_name_when_available():
    from feature_ideate import pick_competitor_seed

    app = {
        "core": {"name": "X"},
        "appInfo": {
            "localizations": [
                {"locale": "zh-Hans", "name": "便签Pro:备忘录Memo便利贴"}
            ]
        },
    }
    seed = pick_competitor_seed(app, {}, {}, bundle_id="com.x", country="CN")
    # Longest ASCII word -> Memo (4) vs Pro (3) -> Memo
    assert seed == "Memo"


def test_pick_competitor_seed_returns_app_name_when_everything_fails():
    from feature_ideate import pick_competitor_seed

    app = {"core": {"name": ""}, "appInfo": {"localizations": []}}
    seed = pick_competitor_seed(app, {}, {}, bundle_id="com.x", country="CN")
    assert seed == "app"  # ultimate fallback
```

- [ ] **Step 2: Run tests, expect 4 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k pick_competitor_seed`
Expected: 4 failures

- [ ] **Step 3: Implement `pick_competitor_seed`**

Append to `feature_ideate.py`:

```python
def pick_competitor_seed(
    app: dict[str, Any],
    snapshots_latest: dict[str, dict[str, dict[str, int]]],
    pop_cache: dict[str, dict[str, Any]],
    bundle_id: str,
    country: str,
) -> str:
    """Choose the keyword to feed AppMate RAG as a competitor-search seed.

    Priority:
      1. ASO keyword where current app rank <= 10 AND highest popularity.
      2. Longest ASCII alpha word from a locale name (prefer country locale).
      3. Longest ASCII alpha word from core.name.
      4. Literal 'app'.
    """
    # 1. ASO hit
    app_kws = (snapshots_latest.get(bundle_id) or {}).get(country) or {}
    best: tuple[int, str] | None = None  # (popularity, keyword)
    store_key = country.lower()
    for kw, rank in app_kws.items():
        if not isinstance(rank, int) or rank > 10:
            continue
        entry = pop_cache.get(f"{store_key}|{kw}") or {}
        pop = entry.get("popularity") or 0
        if best is None or pop > best[0]:
            best = (pop, kw)
    if best:
        return best[1]

    # 2-3. Longest ASCII alpha word from names
    candidates: list[str] = []
    locs = (app.get("appInfo") or {}).get("localizations") or []
    for l in locs:
        n = l.get("name") or ""
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
```

- [ ] **Step 4: Run tests, expect 4 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k pick_competitor_seed`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): pick_competitor_seed (ASO best -> title longest -> 'app')"
```

---

## Task 5: `fetch_competitors(seed, country)` — RAG call wrapper

Wraps `appmate_rag_client.search(...)` with the spec's filter params and trims the response to the fields we store. Network call lives here so it can be patched in tests.

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_ideate.py — append

def test_fetch_competitors_calls_rag_with_spec_params(monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "name": "Notion",
                "rating": 4.7,
                "review_count": 9000,
                "description": "All-in-one workspace",
                "appmate_reason": "high engagement",
                "category_slug": "productivity",
                "extra_field": "drop me",
            }
        ]

    import feature_ideate
    monkeypatch.setattr(feature_ideate, "_rag_search", fake_search)

    out = feature_ideate.fetch_competitors("便签", country="CN")
    assert captured == {
        "query": "便签",
        "region": "cn",
        "top_k": 10,
        "min_review_count": 50,
        "sort_by": "S",
    }
    assert len(out) == 1
    assert set(out[0].keys()) == {"name", "rating", "review_count", "description", "appmate_reason"}
    assert out[0]["name"] == "Notion"


def test_fetch_competitors_returns_empty_on_exception(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("network down")

    import feature_ideate
    monkeypatch.setattr(feature_ideate, "_rag_search", boom)
    out = feature_ideate.fetch_competitors("便签", country="CN")
    assert out == []
```

- [ ] **Step 2: Run tests, expect 2 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k fetch_competitors`
Expected: 2 failures

- [ ] **Step 3: Implement `fetch_competitors`**

Append to `feature_ideate.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect 2 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k fetch_competitors`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): fetch_competitors wraps AppMate RAG with spec params"
```

---

## Task 6: `compute_aso_blindspots(snapshots_latest, pop_cache, bundle_id, country)`

Spec rule (1d): in the astro popularity cache, find keywords with `popularity ≥ 40` that the app is **not tracking** OR is tracking with `rank > 50`. Return top 10 by popularity desc.

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feature_ideate.py — append

def _pop_entry(keyword, pop, diff=50):
    return {"keyword": keyword, "popularity": pop, "difficulty": diff}


def test_compute_aso_blindspots_finds_untracked_high_pop_keywords():
    from feature_ideate import compute_aso_blindspots

    bid = "com.example"
    snapshots = {bid: {"CN": {"便签": 4}}}  # only tracks 便签
    pop_cache = {
        "cn|便签": _pop_entry("便签", 48),     # tracked, not blindspot
        "cn|备忘录": _pop_entry("备忘录", 75),  # blindspot (untracked, pop >= 40)
        "cn|笔记本": _pop_entry("笔记本", 49),  # blindspot
        "cn|快递": _pop_entry("快递", 70),      # blindspot (irrelevant but doesn't filter here)
        "cn|偏门": _pop_entry("偏门", 5),       # too low pop, drop
        "us|备忘录": _pop_entry("备忘录", 80),  # different store, drop
    }
    out = compute_aso_blindspots(snapshots, pop_cache, bundle_id=bid, country="CN")
    keywords = [k["keyword"] for k in out]
    assert "便签" not in keywords          # already covered
    assert "偏门" not in keywords          # pop < 40
    assert keywords[0] == "快递"           # pop 70 - actually 备忘录 75 > 快递 70
    # Re-check actual highest:
    pops = {k["keyword"]: k["popularity"] for k in out}
    assert pops == {"备忘录": 75, "快递": 70, "笔记本": 49}


def test_compute_aso_blindspots_includes_tracked_but_poorly_ranked():
    from feature_ideate import compute_aso_blindspots

    bid = "com.example"
    # App tracks 备忘录 but at rank 80 (worse than threshold 50)
    snapshots = {bid: {"CN": {"备忘录": 80}}}
    pop_cache = {"cn|备忘录": _pop_entry("备忘录", 75)}
    out = compute_aso_blindspots(snapshots, pop_cache, bundle_id=bid, country="CN")
    assert len(out) == 1
    assert out[0]["keyword"] == "备忘录"
    assert out[0]["current_rank"] == 80


def test_compute_aso_blindspots_records_current_rank_or_null():
    from feature_ideate import compute_aso_blindspots

    bid = "com.example"
    snapshots = {bid: {"CN": {"X": 80}}}
    pop_cache = {"cn|X": _pop_entry("X", 60), "cn|Y": _pop_entry("Y", 60)}
    out = compute_aso_blindspots(snapshots, pop_cache, bundle_id=bid, country="CN")
    by_kw = {r["keyword"]: r for r in out}
    assert by_kw["X"]["current_rank"] == 80
    assert by_kw["Y"]["current_rank"] is None


def test_compute_aso_blindspots_caps_at_10():
    from feature_ideate import compute_aso_blindspots

    bid = "com.example"
    snapshots = {bid: {"CN": {}}}
    pop_cache = {f"cn|kw{i}": _pop_entry(f"kw{i}", 40 + i) for i in range(20)}
    out = compute_aso_blindspots(snapshots, pop_cache, bundle_id=bid, country="CN")
    assert len(out) == 10
    # top one is kw19 (pop 59)
    assert out[0]["keyword"] == "kw19"
```

- [ ] **Step 2: Run tests, expect 4 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k compute_aso_blindspots`
Expected: 4 failures

- [ ] **Step 3: Implement `compute_aso_blindspots`**

Append to `feature_ideate.py`:

```python
def compute_aso_blindspots(
    snapshots_latest: dict[str, dict[str, dict[str, int]]],
    pop_cache: dict[str, dict[str, Any]],
    bundle_id: str,
    country: str,
) -> list[dict[str, Any]]:
    """Find high-popularity keywords the app is missing or poorly ranked on.

    Blindspot definition (spec §1d):
      keyword pop >= BLINDSPOT_POP_MIN
      AND (app does not track it OR app's rank > BLINDSPOT_RANK_BAD)
    Returns top BLINDSPOT_TOP_N by popularity desc.
    """
    app_kws = (snapshots_latest.get(bundle_id) or {}).get(country) or {}
    store_prefix = country.lower() + "|"

    out: list[dict[str, Any]] = []
    for cache_key, entry in pop_cache.items():
        if not cache_key.startswith(store_prefix):
            continue
        keyword = entry.get("keyword") or cache_key.split("|", 1)[1]
        pop = entry.get("popularity") or 0
        if pop < BLINDSPOT_POP_MIN:
            continue
        current_rank = app_kws.get(keyword)
        if current_rank is not None and current_rank <= BLINDSPOT_RANK_BAD:
            continue  # already covered well enough
        out.append({
            "keyword": keyword,
            "popularity": pop,
            "difficulty": entry.get("difficulty"),
            "current_rank": current_rank,  # int or None
        })

    out.sort(key=lambda x: -x["popularity"])
    return out[:BLINDSPOT_TOP_N]
```

- [ ] **Step 4: Run tests, expect 4 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k compute_aso_blindspots`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): compute_aso_blindspots (pop>=40 untracked or rank>50)"
```

---

## Task 7: `build_phase_a(...)` — assemble final dict + schema test

This is the schema gate: tests assert the exact top-level keys produced. All helpers feed into it.

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing schema test**

```python
# tests/test_feature_ideate.py — append

def test_build_phase_a_returns_full_schema(monkeypatch):
    from feature_ideate import build_phase_a

    app = {
        "id": "111",
        "core": {
            "name": "DemoApp",
            "bundleId": "com.demo",
            "primaryLocale": "zh-Hans",
        },
        "appInfo": {"localizations": []},
        "reviews": {
            "count": 3,
            "averageRating": 3.0,
            "reviews": [
                _review(1, "极差极差极差极差极差", 1),
                _review(5, "希望加分组功能", 1),
            ],
        },
    }
    sales_cache = {"2026-05-10": [_row("111", "CN")]}
    snapshots = {"2026-05-12": {"com.demo": {"CN": {"DemoApp": 3}}}}
    pop_cache = {"cn|DemoApp": {"keyword": "DemoApp", "popularity": 5},
                 "cn|备忘录": {"keyword": "备忘录", "popularity": 75}}

    monkeypatch.setattr("feature_ideate._rag_search",
                        lambda **kw: [{"name": "Notion", "rating": 4.7,
                                       "review_count": 9000,
                                       "description": "all in one",
                                       "appmate_reason": "broad"}])

    out = build_phase_a(app, sales_cache, snapshots, pop_cache,
                        today=dt.date(2026, 5, 13))
    assert set(out.keys()) >= {
        "app", "app_id", "bundle_id", "market", "downloads_30d_in_market",
        "generated_at", "reviews_negative", "reviews_wishlist",
        "competitors", "aso_blindspots",
    }
    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "CN"
    assert out["downloads_30d_in_market"] == 1
    assert len(out["reviews_negative"]) == 1
    assert len(out["reviews_wishlist"]) == 1
    assert out["competitors"][0]["name"] == "Notion"
    blindspot_kws = [b["keyword"] for b in out["aso_blindspots"]]
    assert "备忘录" in blindspot_kws


def test_build_phase_a_handles_missing_snapshot_day(monkeypatch):
    from feature_ideate import build_phase_a

    app = {"id": "111", "core": {"name": "X", "bundleId": "com.x",
           "primaryLocale": "en-US"},
           "appInfo": {"localizations": []},
           "reviews": {"count": 0, "averageRating": 0, "reviews": []}}
    monkeypatch.setattr("feature_ideate._rag_search", lambda **kw: [])
    out = build_phase_a(app, {}, {}, {}, today=dt.date(2026, 5, 13))
    assert out["market"] == "US"
    assert out["reviews_negative"] == []
    assert out["aso_blindspots"] == []
    assert out["competitors"] == []
```

- [ ] **Step 2: Run tests, expect 2 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k build_phase_a`
Expected: 2 failures (no `build_phase_a`)

- [ ] **Step 3: Implement `build_phase_a`**

Append to `feature_ideate.py`:

```python
def _latest_snapshot_day(snapshots: dict[str, Any]) -> dict[str, Any]:
    if not snapshots:
        return {}
    latest = max(snapshots.keys())
    return snapshots.get(latest) or {}


def _downloads_30d(app_id: str, sales_cache: dict[str, list[dict[str, str]]],
                   country: str, today: dt.date) -> int:
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
            if r.get("Product Type Identifier", "") not in INSTALL_PTIDS:
                continue
            try:
                total += int(r.get("Units", 0) or 0)
            except ValueError:
                pass
    return total


def build_phase_a(
    app: dict[str, Any],
    sales_cache: dict[str, list[dict[str, str]]],
    snapshots: dict[str, Any],
    pop_cache: dict[str, dict[str, Any]],
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Run the Step 1 pipeline end-to-end and return the phase_a dict."""
    today = today or dt.date.today()
    bid = (app.get("core") or {}).get("bundleId") or ""
    app_id = str(app.get("id") or "")
    market = pick_primary_market(app, sales_cache, today=today)

    reviews_list = ((app.get("reviews") or {}).get("reviews")) or []
    buckets = bucket_reviews(reviews_list, today=today)

    snaps_latest = _latest_snapshot_day(snapshots)
    seed = pick_competitor_seed(app, snaps_latest, pop_cache,
                                bundle_id=bid, country=market)
    competitors = fetch_competitors(seed, country=market)

    blindspots = compute_aso_blindspots(snaps_latest, pop_cache,
                                        bundle_id=bid, country=market)

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
        "aso_blindspots": blindspots,
    }
```

- [ ] **Step 4: Run tests, expect 2 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k build_phase_a`
Expected: 2 PASS

- [ ] **Step 5: Run full test file**

Run: `pytest tests/test_feature_ideate.py -v`
Expected: all tests added so far PASS (≈ 18 tests).

- [ ] **Step 6: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): build_phase_a wires the full Step 1 pipeline"
```

---

## Task 8: `main()` — CLI + file I/O

Loads JSON files, calls `build_phase_a`, writes `phase_a_feature_<slug>.json`.

**Files:**
- Modify: `feature_ideate.py`
- Modify: `tests/test_feature_ideate.py`

- [ ] **Step 1: Write failing test for argparse + file write**

```python
# tests/test_feature_ideate.py — append

def test_main_writes_phase_a_file(monkeypatch, tmp_path, capsys):
    """End-to-end: main() reads cache files, writes phase_a json."""
    import feature_ideate as fi

    # Stub all file paths to tmp_path so we don't touch the real project files.
    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"
    snaps = tmp_path / "aso_rank_snapshots.json"
    pop = tmp_path / "astro_popularity_cache.json"
    out_dir = tmp_path  # write phase_a here

    apps_full.write_text(json.dumps({"apps": [{
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }]}))
    sales.write_text("{}")
    snaps.write_text("{}")
    pop.write_text("{}")

    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(fi, "SNAPSHOTS_PATH", snaps)
    monkeypatch.setattr(fi, "POP_CACHE_PATH", pop)
    monkeypatch.setattr(fi, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(fi, "_rag_search", lambda **kw: [])

    rc = fi.main(["DemoApp"])
    assert rc == 0

    # Slug should be 'demoapp_us'
    expected = out_dir / "phase_a_feature_demoapp_us.json"
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["market"] == "US"


def test_main_returns_nonzero_when_app_not_found(monkeypatch, tmp_path):
    import feature_ideate as fi
    apps_full = tmp_path / "apps_full.json"
    apps_full.write_text(json.dumps({"apps": []}))
    for attr in ("SALES_CACHE_PATH", "SNAPSHOTS_PATH", "POP_CACHE_PATH"):
        p = tmp_path / attr.lower()
        p.write_text("{}")
        monkeypatch.setattr(fi, attr, p)
    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "OUTPUT_DIR", tmp_path)
    rc = fi.main(["NoSuchApp"])
    assert rc != 0
```

- [ ] **Step 2: Run tests, expect 2 FAIL**

Run: `pytest tests/test_feature_ideate.py -v -k test_main`
Expected: 2 failures (`main` not defined)

- [ ] **Step 3: Implement `main`**

Append to `feature_ideate.py`:

```python
# --- File paths (overridable in tests) ----------------------------------
APPS_FULL_PATH = PROJECT_ROOT / "apps_full.json"
SALES_CACHE_PATH = PROJECT_ROOT / "sales_cache.json"
SNAPSHOTS_PATH = PROJECT_ROOT / "aso_rank_snapshots.json"
POP_CACHE_PATH = PROJECT_ROOT / "astro_popularity_cache.json"
OUTPUT_DIR = PROJECT_ROOT


def _load_json(path: pathlib.Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate reviews + competitors + ASO blindspots for an app."
    )
    parser.add_argument("app", help="App Store ID / bundle ID / SKU / fuzzy name")
    args = parser.parse_args(argv)

    apps = (_load_json(APPS_FULL_PATH) or {}).get("apps") or []
    app = find_app(args.app, apps=apps)
    if not app:
        print(f"[feature-ideate] App not found: {args.app}", file=sys.stderr)
        return 1

    sales_cache = _load_json(SALES_CACHE_PATH) or {}
    snapshots = _load_json(SNAPSHOTS_PATH) or {}
    pop_cache = _load_json(POP_CACHE_PATH) or {}

    phase_a = build_phase_a(app, sales_cache, snapshots, pop_cache)
    slug = slugify(phase_a["app"], phase_a["market"])
    out = OUTPUT_DIR / f"phase_a_feature_{slug}.json"
    out.write_text(json.dumps(phase_a, ensure_ascii=False, indent=2))

    print(
        f"[feature-ideate] {phase_a['app']} · market={phase_a['market']} · "
        f"30d={phase_a['downloads_30d_in_market']} · "
        f"reviews(-/+wish)={len(phase_a['reviews_negative'])}/"
        f"{len(phase_a['reviews_wishlist'])} · "
        f"competitors={len(phase_a['competitors'])} · "
        f"blindspots={len(phase_a['aso_blindspots'])}"
    )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, expect 2 PASS**

Run: `pytest tests/test_feature_ideate.py -v -k test_main`
Expected: 2 PASS

- [ ] **Step 5: Run full file**

Run: `pytest tests/test_feature_ideate.py -v`
Expected: all 20 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add feature_ideate.py tests/test_feature_ideate.py
git commit -m "feat(feature-ideate): main() CLI loads caches and writes phase_a JSON"
```

---

## Task 9: Live smoke test on real Sticky Note Pro data

Verify the script runs end-to-end on actual project files, produces a non-empty `phase_a_feature_sticky_cn.json`, and the JSON validates against the schema we built.

**Files:**
- Modify: none (read-only verification)

- [ ] **Step 1: Run the CLI**

```bash
cd /Users/fengyq/Desktop/AppMateMax
python3 feature_ideate.py "Sticky Note Pro"
```

Expected: a line ending in `[saved] /Users/fengyq/Desktop/AppMateMax/phase_a_feature_sticky_cn.json` and an info line with non-zero `reviews(-/+wish)` (the app has 355 reviews in cache).

- [ ] **Step 2: Validate the output JSON**

```bash
python3 -c "
import json
d = json.load(open('phase_a_feature_sticky_cn.json'))
required = {'app','app_id','bundle_id','market','downloads_30d_in_market',
            'generated_at','reviews_negative','reviews_wishlist',
            'competitors','aso_blindspots'}
missing = required - set(d.keys())
print('missing keys:', missing)
print('market:', d['market'])
print('downloads_30d:', d['downloads_30d_in_market'])
print('neg/wish:', len(d['reviews_negative']), '/', len(d['reviews_wishlist']))
print('competitors:', len(d['competitors']))
print('blindspots:', len(d['aso_blindspots']))
assert not missing
print('OK')
"
```

Expected:
- `missing keys: set()`
- `market: CN`
- positive review counts (probably negative bucket > 0, wishlist may be small)
- competitor count: 0-10 depending on whether AppMate RAG is reachable
- blindspot count: 0-10
- Final line: `OK`

- [ ] **Step 3: Eyeball the negative bucket for sanity**

```bash
python3 -c "
import json
d = json.load(open('phase_a_feature_sticky_cn.json'))
for r in d['reviews_negative'][:3]:
    print(f\"  rating={r['rating']}  {r['body'][:80]}\")
"
```

Expected: prints up to 3 low-rating review snippets. They should clearly be negative.

- [ ] **Step 4: Commit only if a regression-free baseline is needed**

If the live smoke produced a useful baseline file, leave it un-committed (it's a runtime artifact). No commit needed for this task.

---

## Task 10: Update the workflow doc with the now-validated CLI

Spec already documents `python3 feature_ideate.py "<app>"`. Just sanity-check the doc against the actual `--help` output.

**Files:**
- Modify: `MyFeatures/FEATURE_IDEATION_WORKFLOW.md` (if mismatch found)

- [ ] **Step 1: Diff the doc against actual `--help`**

```bash
python3 feature_ideate.py --help
grep -A 6 "^## CLI" /Users/fengyq/Desktop/AppMateMax/MyFeatures/FEATURE_IDEATION_WORKFLOW.md
```

Expected: the help text matches the doc's described command. If not, update the doc.

- [ ] **Step 2: If a doc edit was needed, commit**

```bash
git add MyFeatures/FEATURE_IDEATION_WORKFLOW.md
git commit -m "docs(feature-ideate): align CLI section with implemented --help"
```

If no diff, skip the commit.

---

## Self-Review (done by plan author)

**Spec coverage check** against `MyFeatures/FEATURE_IDEATION_WORKFLOW.md` Step 1:

| Spec section | Implementing task |
|---|---|
| 1a App 锚定 (find_app reuse) | Task 8 main() (reuses existing find_app) |
| 1a 主市场 (downloads → primaryLocale → US) | Task 2 `pick_primary_market` |
| 1b 评价拆桶 negative | Task 3 `bucket_reviews` |
| 1b 评价拆桶 wishlist | Task 3 `bucket_reviews` |
| 1b 90 天 + cap 50 | Task 3 `bucket_reviews` |
| 1c competitor seed selection | Task 4 `pick_competitor_seed` |
| 1c AppMate RAG call w/ filters | Task 5 `fetch_competitors` |
| 1c competitor record schema | Task 5 (`COMPETITOR_FIELDS`) |
| 1d ASO blindspot definition | Task 6 `compute_aso_blindspots` |
| 1d top 10 by popularity | Task 6 |
| 1e phase_a JSON schema | Task 7 `build_phase_a` |
| CLI entrypoint | Task 8 `main` |

All Step 1 spec items have a corresponding task. Step 2 (LLM ideation) and Step 3 (rendering) are intentionally out of scope per the user's note.

**Placeholder scan**: every code step contains complete code; every test step has executable assertions; every commit step has a real message. No TBDs.

**Type consistency**: `pick_primary_market` returns uppercase 2-letter country (`"CN"`, `"US"`); `slugify` takes that + lowercases it internally; `_rag_search` accepts `region` lowercased before calling. `BLINDSPOT_RANK_BAD = 50` and `pick_competitor_seed`'s `rank > 10` filter are independent thresholds (spec confirms — seed uses ≤ 10, blindspot uses > 50). Verified consistent.

---

Plan complete and saved to [docs/superpowers/plans/2026-05-13-feature-ideate-script.md](docs/superpowers/plans/2026-05-13-feature-ideate-script.md). Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
