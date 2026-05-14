# ASO 优化 v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给定单个 app，分阶段产出当前 ASO 现状 (Phase A) 和候选词验证结果 (Phase B)，由对话层 (Claude) 完成 LLM 任务并合成新 metadata 建议 (Phase C)。

**Architecture:** 新建 `aso_optimize_v2.py` (CLI: `analyze` / `validate` / `show-a` / `show-b`)，**大量复用** 现有 `aso_optimize.py`/`aso_report.py`/`aso_daily.py`/`astro_client.py`。两个中间产物：`phase_a_<slug>.json` + `phase_b_<slug>.json`。

**Tech Stack:** Python 3.14 · pytest · 复用已有 requests/jwt 等。无新依赖（除测试框架）。

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `aso_optimize_v2.py` | 新 CLI 工具，4 个 subcommand | 新建 |
| `tests/__init__.py` | 测试包标记 | 新建 |
| `tests/test_aso_optimize_v2.py` | v2 工具的单元 + 集成测试 | 新建 |
| `aso_optimize.py` | 旧文件保留（被 v2 import） | 不动 |
| `aso_report.py` | 同上 | 不动 |
| `aso_daily.py` | 同上（v2 import `_good_token`） | 不动 |
| `astro_client.py` | 同上 | 不动 |

**v2 模块内部分层（all in `aso_optimize_v2.py`）：**

```
─ Lookups & helpers ─────────────────
  find_app(query)              # 按 id/bundle/sku/name 模糊匹配
  slugify(name, country)        # → "gbrowser_cn"

─ Phase A 数据收集 ──────────────────
  collect_tokens(app, locale)   # 拆词 + 过滤
  rank_tokens(...)              # iTunes Search 全量查
  pop_tokens(...)               # Astro 全量查
  build_phase_a(app, reports)   # 拼装最终 dict

─ Phase B 候选词验证 ────────────────
  parse_candidates_arg(s)       # "kw1,kw2" → list
  build_phase_b(app, candidates) # 同 Phase A 的拼装逻辑

─ I/O ─────────────────────────────
  write_json(path, data)        # 原子写 + ensure_ascii=False
  load_phase(path)              # 读 JSON

─ CLI ────────────────────────────
  cmd_analyze / cmd_validate / cmd_show_a / cmd_show_b
  main(argv)
```

---

## Task 1: Setup — pytest + scaffolding

**Files:**
- Create: `aso_optimize_v2.py`
- Create: `tests/__init__.py`
- Create: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Install pytest**

```bash
pip3 install --user --break-system-packages pytest
```

Expected: pytest installed (no errors).

- [ ] **Step 2: Verify pytest works**

```bash
python3 -m pytest --version
```

Expected: `pytest 8.x` (or whatever version).

- [ ] **Step 3: Create empty test package**

Create `/Users/fengyq/Desktop/AppMateMax/tests/__init__.py` (empty file).

- [ ] **Step 4: Create scaffold for v2 module**

Create `/Users/fengyq/Desktop/AppMateMax/aso_optimize_v2.py`:

```python
"""ASO Optimize v2 — on-demand single-app optimizer.

See docs/superpowers/specs/2026-05-13-aso-optimize-v2-design.md for the design.

CLI:
    python3 aso_optimize_v2.py analyze <app>
    python3 aso_optimize_v2.py validate <app> --candidates kw1,kw2,...
    python3 aso_optimize_v2.py show-a <app>
    python3 aso_optimize_v2.py show-b <app>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
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
import astro_client

PROJECT_ROOT = pathlib.Path(__file__).parent
APPS_FULL = PROJECT_ROOT / "apps_full.json"
SALES_CACHE = PROJECT_ROOT / "sales_cache.json"
```

- [ ] **Step 5: Create test scaffold**

Create `/Users/fengyq/Desktop/AppMateMax/tests/test_aso_optimize_v2.py`:

```python
"""Tests for aso_optimize_v2."""
from __future__ import annotations

import pathlib
import sys

# Ensure repo root is importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def test_module_imports():
    """Smoke: module imports without errors."""
    import aso_optimize_v2  # noqa: F401
```

- [ ] **Step 6: Run smoke test**

```bash
cd /Users/fengyq/Desktop/AppMateMax
python3 -m pytest tests/test_aso_optimize_v2.py::test_module_imports -v
```

Expected: 1 passed.

---

## Task 2: `find_app()` — fuzzy app lookup

**Files:**
- Modify: `aso_optimize_v2.py` (add function)
- Modify: `tests/test_aso_optimize_v2.py` (add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aso_optimize_v2.py`:

```python
import json


APP_FIXTURES = {
    "apps": [
        {
            "id": "6737885863",
            "core": {
                "name": "GBrowser:Choose Link Openly",
                "bundleId": "com.soloware.opnelink",
                "sku": "OpenLink",
            },
        },
        {
            "id": "1482080766",
            "core": {
                "name": "Sticky Note Pro: Post-it&Memo",
                "bundleId": "com.fengyiqi.PostItnoteForMac",
                "sku": "PostItNote",
            },
        },
    ]
}


def test_find_app_by_app_id():
    from aso_optimize_v2 import find_app
    app = find_app("6737885863", apps=APP_FIXTURES["apps"])
    assert app["id"] == "6737885863"


def test_find_app_by_bundle_id():
    from aso_optimize_v2 import find_app
    app = find_app("com.fengyiqi.PostItnoteForMac", apps=APP_FIXTURES["apps"])
    assert app["id"] == "1482080766"


def test_find_app_by_sku():
    from aso_optimize_v2 import find_app
    app = find_app("OpenLink", apps=APP_FIXTURES["apps"])
    assert app["id"] == "6737885863"


def test_find_app_by_name_substring_case_insensitive():
    from aso_optimize_v2 import find_app
    app = find_app("sticky note", apps=APP_FIXTURES["apps"])
    assert app["id"] == "1482080766"


def test_find_app_returns_none_for_no_match():
    from aso_optimize_v2 import find_app
    assert find_app("nonexistent app xyz", apps=APP_FIXTURES["apps"]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k find_app
```

Expected: 5 FAIL (function not defined / ImportError).

- [ ] **Step 3: Implement `find_app`**

Append to `aso_optimize_v2.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k find_app
```

Expected: 5 passed.

---

## Task 3: `slugify()` — filename slug

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_slugify_ascii_name():
    from aso_optimize_v2 import slugify
    assert slugify("GBrowser:Choose Link Openly", "CN") == "gbrowser_cn"


def test_slugify_cjk_name():
    """Pure CJK name → fall back to bundleId-style slug or 'app'."""
    from aso_optimize_v2 import slugify
    # When no ASCII word found, use 'app'
    assert slugify("锁屏头条", "CN") == "app_cn"


def test_slugify_mixed():
    from aso_optimize_v2 import slugify
    assert slugify("Sticky Note Pro: Post-it&Memo", "US") == "sticky_us"


def test_slugify_lowercases_country():
    from aso_optimize_v2 import slugify
    assert slugify("Mirror:Face Camera", "MX") == "mirror_mx"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k slugify
```

Expected: 4 FAIL.

- [ ] **Step 3: Implement `slugify`**

Append to `aso_optimize_v2.py`:

```python
def slugify(name: str, country: str) -> str:
    """Build a filesystem-safe slug from an app name + country code.

    Strategy: take the first ASCII word in the name, lowercase it.
    If no ASCII word exists, use 'app'. Append '_<country>' lowercased.
    """
    m = re.search(r"[A-Za-z][A-Za-z0-9]*", name or "")
    first_word = m.group(0).lower() if m else "app"
    return f"{first_word}_{country.lower()}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k slugify
```

Expected: 4 passed.

---

## Task 4: `collect_tokens()` — extract candidates from metadata

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aso_optimize_v2.py`:

```python
def _sample_app():
    return {
        "id": "6737885863",
        "core": {
            "name": "GBrowser:Choose Link Openly",
            "bundleId": "com.soloware.opnelink",
        },
        "appInfo": {
            "localizations": [
                {
                    "locale": "zh-Hans",
                    "name": "G浏览器",
                    "subtitle": "多浏览器一键切换",
                }
            ]
        },
        "versions": [
            {
                "attributes": {
                    "createdDate": "2026-04-01T00:00:00Z",
                    "platform": "MAC_OS",
                },
                "localizations": [
                    {
                        "locale": "zh-Hans",
                        "keywords": "谷歌浏览器,chrome,firefox,MacOS,app",
                    }
                ],
            }
        ],
    }


def test_collect_tokens_basic():
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    keys = {t["keyword"].lower() for t in tokens}
    # Should include chrome / firefox / 谷歌浏览器 / G浏览器 / 多浏览器一键切换 broken into parts
    assert "chrome" in keys
    assert "firefox" in keys
    assert "谷歌浏览器" in keys


def test_collect_tokens_filters_junk():
    """MacOS and 'app' should be filtered by _good_token (Latin stopword + 4-char tech words)."""
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    keys = {t["keyword"].lower() for t in tokens}
    # 'app' is a stopword; 'macos' has cjk=0 + len > 2 + lowercase + stopword check passes (5 chars)
    # But it's in our reject set (mac is in the stopword set, but MacOS won't match exactly)
    # We expect 'app' to be filtered
    assert "app" not in keys


def test_collect_tokens_has_source_tags():
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    chrome = next((t for t in tokens if t["keyword"].lower() == "chrome"), None)
    assert chrome is not None
    assert "K" in chrome["source"]  # came from keywords field
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k collect_tokens
```

Expected: 3 FAIL.

- [ ] **Step 3: Implement `collect_tokens`**

Append to `aso_optimize_v2.py`:

```python
def collect_tokens(
    app: dict[str, Any],
    info_loc: str | None,
    ver_loc: str | None,
) -> list[dict[str, Any]]:
    """Extract candidate tokens from title/subtitle/keywords for the given locales.

    Returns list of {keyword, source}. `source` is a sorted list of tags drawn
    from {T, S, K} (Title, Subtitle, Keywords).

    Filtering via `_good_token` (CJK ≥ 6 chars rejected, Latin stopwords rejected,
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k collect_tokens
```

Expected: 3 passed.

---

## Task 5: `build_phase_a()` — assemble Phase A dict (pure)

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_build_phase_a_shape():
    """build_phase_a accepts pre-resolved data and returns the documented JSON shape."""
    from aso_optimize_v2 import build_phase_a

    app = _sample_app()
    result = build_phase_a(
        app=app,
        market="CN",
        info_loc="zh-Hans",
        ver_loc="zh-Hans",
        downloads_30d=25147,
        rank_fn=lambda kw, country, entity, bid: {"chrome": 1, "firefox": 9, "谷歌浏览器": 1}.get(kw),
        pop_fn=lambda kws, store: {
            kw: {"popularity": 72, "difficulty": 79}
            for kw in kws
        },
    )

    # Top-level keys
    for k in ("app", "app_id", "bundle_id", "platform", "market", "locale",
              "downloads_30d_in_market", "current_metadata", "current_tokens",
              "generated_at"):
        assert k in result, f"missing key: {k}"

    # Identity
    assert result["app_id"] == "6737885863"
    assert result["market"] == "CN"
    assert result["downloads_30d_in_market"] == 25147

    # current_metadata
    assert result["current_metadata"]["title"] == "G浏览器"
    assert result["current_metadata"]["subtitle"] == "多浏览器一键切换"
    assert "chrome" in result["current_metadata"]["keywords"]

    # current_tokens schema
    chrome_row = next(t for t in result["current_tokens"] if t["keyword"] == "chrome")
    assert chrome_row["rank"] == 1
    assert chrome_row["popularity"] == 72
    assert chrome_row["difficulty"] == 79
    assert isinstance(chrome_row["source"], list)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k build_phase_a
```

Expected: FAIL (function not defined).

- [ ] **Step 3: Implement `build_phase_a`**

Append to `aso_optimize_v2.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k build_phase_a
```

Expected: 1 passed.

---

## Task 6: `write_json()` + `cmd_analyze()` — Phase A end-to-end

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_write_json_round_trip(tmp_path):
    """write_json writes UTF-8 with ensure_ascii=False, round-trips intact."""
    from aso_optimize_v2 import write_json

    p = tmp_path / "out.json"
    data = {"k": "谷歌浏览器", "n": 42}
    write_json(p, data)

    text = p.read_text()
    assert "谷歌浏览器" in text  # not escaped
    assert json.loads(text) == data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k write_json
```

Expected: FAIL.

- [ ] **Step 3: Implement `write_json`**

Append to `aso_optimize_v2.py`:

```python
def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    """Write JSON with UTF-8 + ensure_ascii=False so CJK reads naturally."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run write_json test**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k write_json
```

Expected: 1 passed.

- [ ] **Step 5: Add `cmd_analyze` integration test**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_cmd_analyze_writes_phase_a(tmp_path, monkeypatch):
    """Run cmd_analyze end-to-end with mocked network. File appears with correct shape."""
    import aso_optimize_v2 as v2

    # Point outputs at tmp_path
    monkeypatch.setattr(v2, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    monkeypatch.setattr(v2, "SALES_CACHE", tmp_path / "sales_cache.json")

    # Minimal fixtures
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))
    (tmp_path / "sales_cache.json").write_text(json.dumps({
        # One day of sales in CN for this app
        "2026-05-10": [{
            "Title": "GBrowser:Choose Link Openly",
            "Country Code": "CN",
            "Product Type Identifier": "F1",
            "Units": "1875",
        }] * 1
    }))

    # Mock the two IO functions
    monkeypatch.setattr(v2, "itunes_rank",
                        lambda kw, country, entity, bid, cache=None: 1 if kw == "chrome" else None)
    monkeypatch.setattr(astro_client, "lookup_popularity_batch",
                        lambda kws, store: {kw: {"popularity": 70, "difficulty": 50, "appsCount": 100} for kw in kws})

    # Also mock find_top_market to skip the 30-day rolling math
    monkeypatch.setattr(v2, "find_top_market",
                        lambda name, reports, today: ("CN", 25147))
    monkeypatch.setattr(v2, "pick_locales_for_country",
                        lambda country, infos, vers: ("zh-Hans", "zh-Hans", True))

    # Run the command
    exit_code = v2.cmd_analyze("6737885863")
    assert exit_code == 0

    out_path = tmp_path / "phase_a_gbrowser_cn.json"
    assert out_path.exists()

    payload = json.loads(out_path.read_text())
    assert payload["app_id"] == "6737885863"
    assert payload["market"] == "CN"
    assert payload["downloads_30d_in_market"] == 25147
    assert any(t["keyword"] == "chrome" and t["rank"] == 1 for t in payload["current_tokens"])
```

- [ ] **Step 6: Run cmd_analyze test to verify it fails**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_analyze
```

Expected: FAIL (function not defined).

- [ ] **Step 7: Implement `cmd_analyze`**

Append to `aso_optimize_v2.py`:

```python
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
    out_path = PROJECT_ROOT / f"phase_a_{slug}.json"
    write_json(out_path, payload)
    print(f"[saved] {out_path}  ({len(payload['current_tokens'])} tokens)", flush=True)
    return 0
```

- [ ] **Step 8: Run cmd_analyze test to verify it passes**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_analyze
```

Expected: 1 passed (+ all prior tests still passing).

---

## Task 7: `parse_candidates_arg()` + `build_phase_b()` — Phase B core

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_parse_candidates_arg_basic():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg("kw1,kw2,kw3") == ["kw1", "kw2", "kw3"]


def test_parse_candidates_arg_strips_whitespace():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg(" foo , bar , baz ") == ["foo", "bar", "baz"]


def test_parse_candidates_arg_dedup_preserves_first_seen():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg("a,b,A,c,b") == ["a", "b", "c"]


def test_parse_candidates_arg_caps_at_30():
    from aso_optimize_v2 import parse_candidates_arg
    big = ",".join(f"kw{i}" for i in range(50))
    assert len(parse_candidates_arg(big)) == 30


def test_build_phase_b_shape():
    from aso_optimize_v2 import build_phase_b

    app = _sample_app()
    result = build_phase_b(
        app=app,
        market="CN",
        candidates=["谷歌地图", "翻译"],
        rank_fn=lambda kw, c, e, b: 2 if kw == "谷歌地图" else None,
        pop_fn=lambda kws, store: {
            "谷歌地图": {"popularity": 74, "difficulty": 25},
            "翻译": {"popularity": 75, "difficulty": 76},
        },
    )

    assert result["app_id"] == "6737885863"
    assert result["market"] == "CN"
    assert len(result["candidates"]) == 2

    map_row = next(c for c in result["candidates"] if c["keyword"] == "谷歌地图")
    assert map_row["rank"] == 2
    assert map_row["popularity"] == 74
    assert map_row["difficulty"] == 25

    trans_row = next(c for c in result["candidates"] if c["keyword"] == "翻译")
    assert trans_row["rank"] is None
    assert trans_row["popularity"] == 75
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k "parse_candidates_arg or build_phase_b"
```

Expected: 5 FAIL.

- [ ] **Step 3: Implement `parse_candidates_arg` and `build_phase_b`**

Append to `aso_optimize_v2.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k "parse_candidates_arg or build_phase_b"
```

Expected: 5 passed.

---

## Task 8: `cmd_validate()` — Phase B CLI wiring

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_cmd_validate_writes_phase_b(tmp_path, monkeypatch):
    import aso_optimize_v2 as v2

    monkeypatch.setattr(v2, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    monkeypatch.setattr(v2, "SALES_CACHE", tmp_path / "sales_cache.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))
    (tmp_path / "sales_cache.json").write_text(json.dumps({}))

    monkeypatch.setattr(v2, "itunes_rank",
                        lambda kw, country, entity, bid, cache=None: 2 if kw == "谷歌地图" else None)
    monkeypatch.setattr(astro_client, "lookup_popularity_batch",
                        lambda kws, store: {kw: {"popularity": 74, "difficulty": 25} for kw in kws})

    # find_top_market needs to return a market without real sales
    monkeypatch.setattr(v2, "find_top_market",
                        lambda name, reports, today: ("CN", 0))

    exit_code = v2.cmd_validate("6737885863", "谷歌地图,翻译")
    assert exit_code == 0

    out_path = tmp_path / "phase_b_gbrowser_cn.json"
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["keyword"] == "谷歌地图"
    assert payload["candidates"][0]["rank"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_validate
```

Expected: FAIL.

- [ ] **Step 3: Implement `cmd_validate`**

Append to `aso_optimize_v2.py`:

```python
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
    out_path = PROJECT_ROOT / f"phase_b_{slug}.json"
    write_json(out_path, payload)
    print(f"[saved] {out_path}", flush=True)
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_validate
```

Expected: 1 passed (all prior also pass).

---

## Task 9: `cmd_show_a()` + `cmd_show_b()` — summary printers

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_cmd_show_a_prints_summary(tmp_path, monkeypatch, capsys):
    import aso_optimize_v2 as v2
    monkeypatch.setattr(v2, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))

    # Fake a phase_a file
    phase_a = {
        "app": "GBrowser:Choose Link Openly",
        "app_id": "6737885863",
        "market": "CN",
        "locale": "zh-Hans",
        "downloads_30d_in_market": 25147,
        "current_metadata": {"title": "G浏览器", "subtitle": "...", "keywords": "..."},
        "current_tokens": [
            {"keyword": "chrome", "source": ["K"], "rank": 1, "popularity": 72, "difficulty": 79},
            {"keyword": "junk", "source": ["K"], "rank": None, "popularity": 5, "difficulty": 80},
        ],
        "generated_at": "2026-05-13T00:00:00+08:00",
    }
    (tmp_path / "phase_a_gbrowser_cn.json").write_text(json.dumps(phase_a, ensure_ascii=False))

    exit_code = v2.cmd_show_a("6737885863")
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "GBrowser" in out
    assert "CN" in out
    assert "chrome" in out
    assert "25,147" in out or "25147" in out


def test_cmd_show_a_handles_missing_file(tmp_path, monkeypatch, capsys):
    import aso_optimize_v2 as v2
    monkeypatch.setattr(v2, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))

    exit_code = v2.cmd_show_a("6737885863")
    assert exit_code != 0  # exit non-zero because no phase_a file
    out = capsys.readouterr()
    assert "no phase_a" in (out.err + out.out).lower() or "not found" in (out.err + out.out).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_show_a
```

Expected: 2 FAIL.

- [ ] **Step 3: Implement `cmd_show_a` and `cmd_show_b`**

Append to `aso_optimize_v2.py`:

```python
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
    matches = sorted(PROJECT_ROOT.glob(pattern))
    if not matches:
        print(f"ERROR: no phase_{phase} file found matching {pattern!r}", file=sys.stderr)
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
        print(f"  {kw:<28} {str(rank or '—'):>6} {str(pop or '—'):>5} {str(diff or '—'):>5}")


def cmd_show_a(query: str) -> int:
    return _show_phase(query, "a")


def cmd_show_b(query: str) -> int:
    return _show_phase(query, "b")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k cmd_show_a
```

Expected: 2 passed.

---

## Task 10: `main()` — CLI dispatcher + full test sweep

**Files:**
- Modify: `aso_optimize_v2.py`
- Modify: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_aso_optimize_v2.py`:

```python
def test_main_dispatches_analyze(tmp_path, monkeypatch):
    """main(['analyze', '<app>']) routes to cmd_analyze."""
    import aso_optimize_v2 as v2

    called = {}
    def fake_analyze(query):
        called["analyze"] = query
        return 0
    monkeypatch.setattr(v2, "cmd_analyze", fake_analyze)

    exit_code = v2.main(["analyze", "GBrowser"])
    assert exit_code == 0
    assert called.get("analyze") == "GBrowser"


def test_main_dispatches_validate(monkeypatch):
    import aso_optimize_v2 as v2
    called = {}
    def fake_validate(query, candidates):
        called["validate"] = (query, candidates)
        return 0
    monkeypatch.setattr(v2, "cmd_validate", fake_validate)

    exit_code = v2.main(["validate", "GBrowser", "--candidates", "a,b,c"])
    assert exit_code == 0
    assert called["validate"] == ("GBrowser", "a,b,c")


def test_main_help_returns_zero(capsys):
    import aso_optimize_v2 as v2
    exit_code = v2.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "analyze" in out
    assert "validate" in out


def test_main_unknown_command_returns_nonzero(capsys):
    import aso_optimize_v2 as v2
    exit_code = v2.main(["bogus"])
    assert exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v -k main
```

Expected: 4 FAIL.

- [ ] **Step 3: Implement `main`**

Append to `aso_optimize_v2.py`:

```python
USAGE = """Usage:
  python3 aso_optimize_v2.py analyze <app>
  python3 aso_optimize_v2.py validate <app> --candidates kw1,kw2,kw3
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
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/test_aso_optimize_v2.py -v
```

Expected: ALL tests pass (full sweep — Task 1 through 10).

---

## Task 11: Live smoke test against real data

**No new code — verifies the implementation against real app + Astro + iTunes.**

- [ ] **Step 1: Run Phase A on GBrowser**

```bash
cd /Users/fengyq/Desktop/AppMateMax
python3 aso_optimize_v2.py analyze GBrowser
```

Expected:
- Console shows `[analyze] GBrowser:Choose Link Openly · market=CN · locale=... · 30d=...`
- File `phase_a_gbrowser_cn.json` appears
- `[saved]` message with token count

- [ ] **Step 2: Inspect Phase A output**

```bash
python3 aso_optimize_v2.py show-a GBrowser
```

Expected: table with tokens like `chrome / 谷歌浏览器 / firefox` showing rank, pop, diff.

- [ ] **Step 3: Verify Phase A JSON shape**

```bash
python3 -c "
import json
p = json.load(open('phase_a_gbrowser_cn.json'))
required = ['app', 'app_id', 'bundle_id', 'platform', 'market', 'locale',
            'downloads_30d_in_market', 'current_metadata', 'current_tokens',
            'generated_at']
missing = [k for k in required if k not in p]
print('missing keys:', missing or 'none')
print('token count:', len(p['current_tokens']))
print('sample token:', p['current_tokens'][0])
"
```

Expected: `missing keys: none`, sample token has all 5 fields (keyword/source/rank/popularity/difficulty).

- [ ] **Step 4: Run Phase B on hand-picked candidates**

```bash
python3 aso_optimize_v2.py validate GBrowser --candidates 谷歌地图,谷歌翻译,翻译
```

Expected:
- File `phase_b_gbrowser_cn.json` appears
- All 3 candidates resolved with rank + pop + diff

- [ ] **Step 5: Inspect Phase B output**

```bash
python3 aso_optimize_v2.py show-b GBrowser
```

Expected: 3 rows. `谷歌地图` rank ≈ #2, popularity ~74.

- [ ] **Step 6: Edge case — app not found**

```bash
python3 aso_optimize_v2.py analyze "nonexistent_app_xyz"
```

Expected: non-zero exit code, stderr message about no match.

- [ ] **Step 7: Edge case — Sticky Note Pro (second app, validates code isn't GBrowser-specific)**

```bash
python3 aso_optimize_v2.py analyze "sticky note"
```

Expected: success; file `phase_a_sticky_cn.json` appears.

---

## Self-Review Notes

Cross-checked against spec:

| Spec § | Coverage in plan |
|---|---|
| § 2 Goal — 生成可粘贴 metadata | Phase A/B produce data; Phase C done in conversation (out of scope for code) ✓ |
| § 4 Phase A 8 步骤 | Task 4-6 collectively implement them ✓ |
| § 4 JSON shape | Task 5/6 tests assert the shape ✓ |
| § 5 Phase B 验证 | Task 7-8 ✓ |
| § 5 JSON shape | Task 7 test asserts ✓ |
| § 6 Phase C | Intentionally out of scope (in conversation) ✓ |
| § 7 文件输出 | `phase_a_<slug>.json` / `phase_b_<slug>.json` via Task 5/8 ✓ |
| § 8 CLI 4 子命令 | Task 10 main() dispatches all 4 ✓ |
| § 9 复用现有代码 | Task 1 sets up imports ✓ |
| § 11 非目标 | Not in plan — correctly excluded ✓ |
| § 12 Testing | Tasks 4-10 implement unit tests; Task 11 is end-to-end ✓ |

**Type consistency check:**
- `RankFn` / `PopFn` typedefs introduced in Task 5, reused in Task 7 ✓
- `build_phase_a` / `build_phase_b` both accept `rank_fn` / `pop_fn` with same signature ✓
- `cmd_analyze` / `cmd_validate` both write via `write_json` from Task 6 ✓
- `slugify` used identically in Task 6 and Task 8 ✓

**Placeholder scan:** No TBD / TODO / "add error handling" / "similar to Task N" — all code blocks complete.
