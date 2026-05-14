# AppMate Plugin Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repackage the `AppMateMax` folder in place into a GitHub-deployable Claude Code plugin named "AppMate" — standard plugin layout, gitignored secrets/caches, English source + docs, 6 skills + 6 commands.

**Architecture:** In-place restructure (`git init` already done). All 16 Python scripts move to `scripts/` and read paths/credentials through one new `appmate_config.py`. Six Chinese workflow docs become six English `skills/*/SKILL.md`, each with a thin `/appmate-*` command. Secrets → gitignored `config/`; caches + run outputs → gitignored `data/`. Workflow logic is untouched (Approach B); generated report output stays Chinese.

**Tech Stack:** Python 3 (PyJWT, requests, cryptography), pytest, Claude Code plugin format (`.claude-plugin/plugin.json`, `skills/`, `commands/`).

**Reference:** `docs/superpowers/specs/2026-05-14-appmate-plugin-packaging-design.md`

---

## Task 1: Scaffold directory structure, move files, add .gitignore

Create the plugin skeleton and relocate every existing file. `.gitignore` is created first so secrets and caches are never stageable.

**Files:**
- Create: `.gitignore`, `scripts/` `skills/` `commands/` `config/` `data/` `docs/` directories
- Move: 16 `*.py` → `scripts/`; secrets → `config/`; caches + outputs → `data/`

- [ ] **Step 1: Create the `.gitignore`**

Create `.gitignore` at repo root:
```
# Secrets — never commit
config/*
!config/credentials.example.txt
!config/README.md

# Caches, snapshots, run outputs
data/*
!data/.gitkeep

# Python / OS cruft
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
.appmate_rag_cache/
```

- [ ] **Step 2: Create directories**

Run:
```bash
mkdir -p scripts skills/appmate-setup skills/sales-daily-report \
  skills/aso-optimize/references skills/aso-daily-report \
  skills/feature-ideation skills/growth-strategy \
  commands config data docs
touch data/.gitkeep
```

- [ ] **Step 3: Move the 16 Python scripts into `scripts/`**

Run:
```bash
mv app_analytics.py appmate_rag_client.py asc_client.py aso_astro.py \
   aso_daily.py aso_optimize.py aso_optimize_v2.py aso_report.py astro_client.py \
   feature_ideate.py fetch_full.py fetch_icons.py fetch_metadata.py \
   growth_strategy.py sales_report.py search_ads_client.py scripts/
```

- [ ] **Step 4: Move secrets into `config/`**

Run:
```bash
mv credentials.txt AuthKey_M5JXS72F29.p8 searchads_private.p8 \
   searchads_public.pem search_ads_credentials.txt .search_ads_token.json config/
```

- [ ] **Step 5: Move caches, snapshots, and run outputs into `data/`**

Run:
```bash
mv apps_full.json apps_metadata.json app_icons.json sales_cache.json \
   aso_rank_cache.json aso_rank_snapshots.json astro_popularity_cache.json \
   aso_popularity_cache.json aso_hints_cache.json perf_metrics.json \
   data/ 2>/dev/null
mv phase_a_*.json phase_b_*.json data/ 2>/dev/null
mv report.md aso_daily.md aso_report.md aso_astro.md aso_optimize.md \
   aso_optimize_sticky_cn.md growth_strategy_onesearch_cn.md \
   feature_ideas_onesearch_cn.md report_template.md aso_daily_template.md \
   data/ 2>/dev/null
mv .appmate_rag_cache data/ 2>/dev/null
true
```

- [ ] **Step 6: Update `config/credentials.txt` so the existing setup keeps working**

The moved `config/credentials.txt` still has the old absolute `private_key_path` and lacks `vendor_number`. Edit `config/credentials.txt` to:
- change `private_key_path` to `config/AuthKey_M5JXS72F29.p8` (relative — `appmate_config` resolves it against `APPMATE_HOME`)
- add a line `vendor_number = 87558752` (the value currently hardcoded in `asc_client.py`)

Final `config/credentials.txt` content:
```
issuer_id        = 69a6de92-f8ed-47e3-e053-5b8c7c11a4d1
key_id           = M5JXS72F29
private_key_path = config/AuthKey_M5JXS72F29.p8
vendor_number    = 87558752
```

- [ ] **Step 7: Remove Python/OS cruft**

Run:
```bash
rm -rf __pycache__ .pytest_cache tests/__pycache__ .DS_Store docs/.DS_Store ToolChain/.DS_Store
```

- [ ] **Step 8: Verify structure and that git sees no secrets**

Run:
```bash
ls scripts | wc -l          # expect 16
git add -A --dry-run | grep -E "config/(credentials\.txt|.*\.p8)|data/" && echo "LEAK" || echo "clean"
```
Expected: `16`, then `clean` (no secrets/caches stageable).

- [ ] **Step 9: Commit**

```bash
git add .gitignore data/.gitkeep
git commit -m "chore: scaffold plugin directory layout, move files, add .gitignore"
```

---

## Task 2: Create `appmate_config.py` (TDD) + pytest path config

The single source of truth for paths + credentials. Path resolution is eager; credential loading is lazy and graceful so a credential-less checkout still imports cleanly.

**Files:**
- Create: `scripts/appmate_config.py`
- Create: `tests/test_appmate_config.py`
- Create: `pyproject.toml`

- [ ] **Step 1: Add pytest path config so tests can import from `scripts/`**

Create `pyproject.toml` at repo root:
```toml
[tool.pytest.ini_options]
pythonpath = ["scripts"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_appmate_config.py`:
```python
import importlib
import pathlib

import appmate_config


def _fresh(monkeypatch, home: pathlib.Path):
    monkeypatch.setenv("APPMATE_HOME", str(home))
    mod = importlib.reload(appmate_config)
    return mod


def test_paths_resolve_under_appmate_home(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg.DATA_DIR == tmp_path / "data"
    assert cfg.CONFIG_DIR == tmp_path / "config"


def test_data_path_creates_data_dir(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    p = cfg.data_path("x.json")
    assert p == tmp_path / "data" / "x.json"
    assert (tmp_path / "data").is_dir()


def test_load_config_missing_file_returns_empty(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg._load_config() == {}


def test_load_config_parses_and_skips_comments(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text(
        "# comment\nissuer_id = abc\n\nvendor_number = 123\n"
    )
    parsed = cfg._load_config()
    assert parsed == {"issuer_id": "abc", "vendor_number": "123"}


def test_url_accessors_have_defaults(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg.rag_base_url() == "https://appmate.000ooo.ooo"
    assert cfg.astro_endpoint() == "http://127.0.0.1:8089/mcp"


def test_require_raises_pointing_to_setup(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    try:
        cfg.asc_issuer_id()
    except RuntimeError as e:
        assert "appmate-setup" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_accessors_return_values_when_present(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text(
        "issuer_id=i\nkey_id=k\nvendor_number=v\nprivate_key_path=config/key.p8\n"
    )
    assert cfg.asc_issuer_id() == "i"
    assert cfg.asc_key_id() == "k"
    assert cfg.asc_vendor_number() == "v"
    assert cfg.asc_private_key_path() == tmp_path / "config" / "key.p8"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_appmate_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'appmate_config'`.

- [ ] **Step 4: Write `scripts/appmate_config.py`**

```python
"""Shared configuration and path resolution for AppMate scripts.

Single source of truth for:
  - where data/caches and config/secrets live (DATA_DIR / CONFIG_DIR)
  - App Store Connect credentials + account constants

Path resolution is eager and never fails. Credential loading is lazy and
graceful: a missing config/credentials.txt does not break imports — an error
is raised only when a required secret is actually used, pointing at /appmate-setup.
"""
from __future__ import annotations

import os
import pathlib

# --- Path resolution (eager, pure pathlib, never fails) --------------------
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
APPMATE_HOME = pathlib.Path(os.environ.get("APPMATE_HOME", PLUGIN_ROOT)).resolve()
DATA_DIR = APPMATE_HOME / "data"
CONFIG_DIR = APPMATE_HOME / "config"


def data_path(name: str) -> pathlib.Path:
    """Path to a file under data/. Ensures data/ exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def config_path(name: str) -> pathlib.Path:
    """Path to a file under config/."""
    return CONFIG_DIR / name


# --- Credential loading (lazy, graceful — re-read each call, file is tiny) --
def _load_config() -> dict[str, str]:
    """Parse config/credentials.txt into a dict. Missing file -> empty dict."""
    path = CONFIG_DIR / "credentials.txt"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _require(key: str) -> str:
    val = (_load_config().get(key) or "").strip()
    if not val:
        raise RuntimeError(
            f"AppMate config missing '{key}'. "
            f"Run /appmate-setup or edit {CONFIG_DIR / 'credentials.txt'}."
        )
    return val


def asc_issuer_id() -> str:
    return _require("issuer_id")


def asc_key_id() -> str:
    return _require("key_id")


def asc_vendor_number() -> str:
    return _require("vendor_number")


def asc_private_key_path() -> pathlib.Path:
    p = pathlib.Path(_require("private_key_path"))
    return p if p.is_absolute() else APPMATE_HOME / p


def rag_base_url() -> str:
    return _load_config().get("rag_base_url") or "https://appmate.000ooo.ooo"


def astro_endpoint() -> str:
    return _load_config().get("astro_endpoint") or "http://127.0.0.1:8089/mcp"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_appmate_config.py -q`
Expected: PASS — 7 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/appmate_config.py tests/test_appmate_config.py pyproject.toml
git commit -m "feat: add appmate_config — central paths + lazy credential loading"
```

---

## Task 3: Refactor `asc_client.py` + `search_ads_client.py` to use appmate_config

Both load credentials at module import today, which crashes a credential-less checkout. Make loading lazy via `appmate_config`.

**Files:**
- Modify: `scripts/asc_client.py`
- Modify: `scripts/search_ads_client.py`

- [ ] **Step 1: Refactor `scripts/asc_client.py`**

Replace the credential block. Delete `CRED_PATH`, `_load_credentials()`, `_CREDS`, `ISSUER_ID`, `KEY_ID`, `PRIVATE_KEY`, `VENDOR_NUMBER` (module-level). Add `import appmate_config`. Then:

In `make_token()`, replace the body's identifiers:
```python
def make_token(audience: str = "appstoreconnect-v1", lifetime_seconds: int = 1200) -> str:
    """Generate a short-lived ES256 JWT for App Store Connect."""
    now = int(time.time())
    headers = {"alg": "ES256", "kid": appmate_config.asc_key_id(), "typ": "JWT"}
    payload = {
        "iss": appmate_config.asc_issuer_id(),
        "iat": now,
        "exp": now + lifetime_seconds,
        "aud": audience,
    }
    private_key = appmate_config.asc_private_key_path().read_text()
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
```

In `sales_report()` and `finance_report()`, replace `"filter[vendorNumber]": VENDOR_NUMBER` with `"filter[vendorNumber]": appmate_config.asc_vendor_number()`.

- [ ] **Step 2: Refactor `scripts/search_ads_client.py`**

Add `import appmate_config`. Delete module-level `CREDS = _load_creds()`. Change `CREDS_PATH` and `TOKEN_CACHE`:
```python
def _creds_path():
    return appmate_config.config_path("search_ads_credentials.txt")

def _token_cache():
    return appmate_config.data_path(".search_ads_token.json")
```
Update `_load_creds()` to read `_creds_path()`. Replace every module-level `CREDS[...]` reference inside `make_client_assertion()` / `_headers()` with `_load_creds()[...]` (call it locally). Replace `TOKEN_CACHE` references in `_load_cached_token()` / `_save_cached_token()` with `_token_cache()`.

- [ ] **Step 3: Verify imports succeed without credentials**

Run:
```bash
APPMATE_HOME=$(mktemp -d) python3 -c "import sys; sys.path.insert(0,'scripts'); import asc_client, search_ads_client; print('ok')"
```
Expected: `ok` (no crash — lazy loading works).

- [ ] **Step 4: Commit**

```bash
git add scripts/asc_client.py scripts/search_ads_client.py
git commit -m "refactor: asc_client + search_ads_client read config via appmate_config (lazy)"
```

---

## Task 4: Refactor `astro_client.py` + `appmate_rag_client.py`

**Files:**
- Modify: `scripts/astro_client.py`
- Modify: `scripts/appmate_rag_client.py`

- [ ] **Step 1: Refactor `scripts/astro_client.py`**

Add `import appmate_config`. Replace:
```python
ENDPOINT = "http://127.0.0.1:8089/mcp"
```
with:
```python
ENDPOINT = appmate_config.astro_endpoint()
```
Replace:
```python
POP_CACHE_PATH = pathlib.Path(__file__).with_name("astro_popularity_cache.json")
```
with:
```python
POP_CACHE_PATH = appmate_config.data_path("astro_popularity_cache.json")
```

- [ ] **Step 2: Refactor `scripts/appmate_rag_client.py`**

Add `import appmate_config`. Replace:
```python
BASE_URL = "https://appmate.000ooo.ooo"
```
with:
```python
BASE_URL = appmate_config.rag_base_url()
```

- [ ] **Step 3: Verify imports**

Run:
```bash
APPMATE_HOME=$(mktemp -d) python3 -c "import sys; sys.path.insert(0,'scripts'); import astro_client, appmate_rag_client; print(astro_client.ENDPOINT, appmate_rag_client.BASE_URL)"
```
Expected: `http://127.0.0.1:8089/mcp https://appmate.000ooo.ooo`

- [ ] **Step 4: Commit**

```bash
git add scripts/astro_client.py scripts/appmate_rag_client.py
git commit -m "refactor: astro_client + appmate_rag_client read endpoints via appmate_config"
```

---

## Task 5: Refactor the 5 ASO scripts' path constants

`aso_optimize.py`, `aso_report.py`, `aso_daily.py`, `aso_astro.py`, `aso_optimize_v2.py` each define data/cache/output paths via `pathlib.Path(__file__).with_name(...)` or `PROJECT_ROOT / ...`. Redirect them through `appmate_config`. No logic changes.

**Files:**
- Modify: `scripts/aso_optimize.py`, `scripts/aso_report.py`, `scripts/aso_daily.py`, `scripts/aso_astro.py`, `scripts/aso_optimize_v2.py`
- Test: `tests/test_aso_optimize_v2.py`

- [ ] **Step 1: Refactor `scripts/aso_report.py`**

Add `import appmate_config`. Replace the path constants:
```python
APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
OUT = appmate_config.data_path("aso_report.md")
RANK_CACHE = appmate_config.data_path("aso_rank_cache.json")
POP_CACHE = appmate_config.data_path("aso_popularity_cache.json")
SEARCH_ADS_CREDS = appmate_config.config_path("search_ads_credentials.txt")
```

- [ ] **Step 2: Refactor `scripts/aso_optimize.py`**

Add `import appmate_config`. Replace:
```python
APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
HINTS_CACHE = appmate_config.data_path("aso_hints_cache.json")
OUT = appmate_config.data_path("aso_optimize.md")
```

- [ ] **Step 3: Refactor `scripts/aso_daily.py`**

Add `import appmate_config`. Replace:
```python
APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
RANK_SNAPSHOTS = appmate_config.data_path("aso_rank_snapshots.json")
OUT = appmate_config.data_path("aso_daily.md")
```

- [ ] **Step 4: Refactor `scripts/aso_astro.py`**

Add `import appmate_config`. Replace:
```python
APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
OUT = appmate_config.data_path("aso_astro.md")
```

- [ ] **Step 5: Refactor `scripts/aso_optimize_v2.py`**

Add `import appmate_config`. Replace:
```python
PROJECT_ROOT = pathlib.Path(__file__).parent
APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
```
Then update the two `show_*` helpers and `cmd_analyze`/`cmd_validate`: anywhere a `phase_a_*.json` / `phase_b_*.json` output path is built as `PROJECT_ROOT / f"phase_a_{slug}.json"`, change to `appmate_config.data_path(f"phase_a_{slug}.json")` (and the `phase_b_` equivalent). The `PROJECT_ROOT.glob(pattern)` calls in `_show_phase` become `appmate_config.DATA_DIR.glob(pattern)`.

- [ ] **Step 6: Run the ASO test suite**

Run: `python3 -m pytest tests/test_aso_optimize_v2.py -q`
Expected: PASS (same count as before the refactor — function signatures unchanged).

- [ ] **Step 7: Commit**

```bash
git add scripts/aso_optimize.py scripts/aso_report.py scripts/aso_daily.py scripts/aso_astro.py scripts/aso_optimize_v2.py
git commit -m "refactor: ASO scripts resolve data/cache paths via appmate_config"
```

---

## Task 6: Refactor `sales_report.py`, `feature_ideate.py`, `growth_strategy.py`

**Files:**
- Modify: `scripts/sales_report.py`, `scripts/feature_ideate.py`, `scripts/growth_strategy.py`
- Test: `tests/test_feature_ideate.py`, `tests/test_growth_strategy.py`

- [ ] **Step 1: Refactor `scripts/sales_report.py`**

Add `import appmate_config`. Replace `CACHE_PATH = pathlib.Path(__file__).with_name("sales_cache.json")` with `CACHE_PATH = appmate_config.data_path("sales_cache.json")`. In `build_parent_lookup()`, `load_live_apps()`, `load_icon_map()`: replace `pathlib.Path(__file__).with_name("apps_full.json")` with `appmate_config.data_path("apps_full.json")` and `with_name("app_icons.json")` with `appmate_config.data_path("app_icons.json")`. In `render()`, replace `pathlib.Path(__file__).with_name("report.md")` with `appmate_config.data_path("report.md")`.

- [ ] **Step 2: Refactor `scripts/feature_ideate.py`**

Add `import appmate_config`. Keep the existing `PROJECT_ROOT` + `sys.path.insert` lines (they make sibling imports robust). Replace:
```python
APPS_FULL_PATH = appmate_config.data_path("apps_full.json")
SALES_CACHE_PATH = appmate_config.data_path("sales_cache.json")
OUTPUT_DIR = appmate_config.DATA_DIR
```

- [ ] **Step 3: Refactor `scripts/growth_strategy.py`**

Add `import appmate_config`. Keep `PROJECT_ROOT` + `sys.path.insert`. Replace:
```python
APPS_FULL_PATH = appmate_config.data_path("apps_full.json")
SALES_CACHE_PATH = appmate_config.data_path("sales_cache.json")
ASO_SNAPSHOTS_PATH = appmate_config.data_path("aso_rank_snapshots.json")
OUTPUT_DIR = appmate_config.DATA_DIR
```

- [ ] **Step 4: Run the affected test suites**

Run: `python3 -m pytest tests/test_feature_ideate.py tests/test_growth_strategy.py -q`
Expected: PASS (function signatures unchanged; tests pass explicit data + monkeypatch `_rag_search`).

- [ ] **Step 5: Commit**

```bash
git add scripts/sales_report.py scripts/feature_ideate.py scripts/growth_strategy.py
git commit -m "refactor: sales/feature/growth scripts resolve paths via appmate_config"
```

---

## Task 7: Refactor `fetch_full.py`, `fetch_metadata.py`, `fetch_icons.py`, `app_analytics.py`

These write snapshot/output JSON next to `__file__` today.

**Files:**
- Modify: `scripts/fetch_full.py`, `scripts/fetch_metadata.py`, `scripts/fetch_icons.py`, `scripts/app_analytics.py`

- [ ] **Step 1: Refactor each output path**

In each file add `import appmate_config` and redirect output/input path constants:
- `fetch_full.py`: `OUT_PATH = appmate_config.data_path("apps_full.json")`
- `fetch_metadata.py`: its output constant → `appmate_config.data_path("apps_metadata.json")` (check the file for the exact constant name; redirect any `apps_metadata.json` / input `apps_full.json` path).
- `fetch_icons.py`: output → `appmate_config.data_path("app_icons.json")`; any input `apps_full.json` → `appmate_config.data_path("apps_full.json")`.
- `app_analytics.py`: `OUT_PERF = appmate_config.data_path("perf_metrics.json")`, `OUT_ANALYTICS = appmate_config.data_path("app_analytics.json")`, `APPS_FULL = appmate_config.data_path("apps_full.json")`.

- [ ] **Step 2: Verify imports**

Run:
```bash
APPMATE_HOME=$(mktemp -d) python3 -c "import sys; sys.path.insert(0,'scripts'); import fetch_full, fetch_metadata, fetch_icons, app_analytics; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch_full.py scripts/fetch_metadata.py scripts/fetch_icons.py scripts/app_analytics.py
git commit -m "refactor: fetch_* + app_analytics resolve output paths via appmate_config"
```

---

## Task 8: Verification gate — full pytest + fresh-checkout import smoke

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest -q`
Expected: all tests PASS (4 test files: appmate_config + the 3 originals).

- [ ] **Step 2: Fresh-checkout import smoke test (no credentials present)**

Run:
```bash
APPMATE_HOME=$(mktemp -d) python3 -c "
import sys; sys.path.insert(0,'scripts')
import appmate_config, asc_client, search_ads_client, astro_client, appmate_rag_client
import aso_optimize, aso_report, aso_daily, aso_astro, aso_optimize_v2
import sales_report, feature_ideate, growth_strategy
import fetch_full, fetch_metadata, fetch_icons, app_analytics
print('all 17 modules import clean without credentials')
"
```
Expected: `all 17 modules import clean without credentials`

- [ ] **Step 3: Confirm no stray `/Users/fengyq` paths remain in scripts**

Run: `grep -rn "/Users/fengyq" scripts/ || echo "clean"`
Expected: `clean`

- [ ] **Step 4: Commit (only if Steps 1-3 required fixes; otherwise skip)**

```bash
git add -A scripts tests
git commit -m "fix: address issues found in verification gate"
```

---

## Task 9: Translate Chinese comments/docstrings/diagnostics in scripts to English

Per the spec translation rule: translate comments, docstrings, `print()`/log/CLI strings to English. **Do NOT change** functional Chinese literals (e.g. `WISH_TRIGGERS` review-trigger words, locale/country tables) or report-output strings (rendered markdown like `## 🧮 总和`, `DIM_LABELS_CN`, table headers).

**Files:**
- Modify: any of the 16 `scripts/*.py` containing Chinese comments/docstrings/diagnostics. Known: `aso_daily.py` (module docstring), `aso_report.py` (docstring + inline comments), `aso_optimize.py`, `aso_optimize_v2.py`, `astro_client.py`, `feature_ideate.py`, `growth_strategy.py`. Scan all 16.

- [ ] **Step 1: Scan for Chinese in scripts**

Run: `grep -rlnP '[\x{4e00}-\x{9fff}]' scripts/`
This lists every script with CJK characters. For each, inspect the matches.

- [ ] **Step 2: Translate, applying the rule**

For each match decide:
- comment / docstring / `print(...)` diagnostic / CLI usage text / log message → translate to English
- string appended to a `lines` list that becomes report markdown, dict like `DIM_LABELS_CN`, label maps rendered to the user, detection keyword lists, locale tables → **leave unchanged**

Edit accordingly. Keep changes confined to wording — no logic edits.

- [ ] **Step 3: Verify nothing functional broke**

Run: `python3 -m pytest -q`
Expected: all PASS.

Run: `grep -rlnP '[\x{4e00}-\x{9fff}]' scripts/`
Expected: only files that legitimately retain functional Chinese literals / report-output strings (e.g. `sales_report.py`, `aso_daily.py`, `feature_ideate.py`). No file should retain Chinese *comments or docstrings*.

- [ ] **Step 4: Commit**

```bash
git add scripts/
git commit -m "docs: translate script comments/docstrings/diagnostics to English"
```

---

## Task 10: Skill — `appmate-setup`

Translate `MyFeatures/ASC_API_SETUP.md` into an English setup skill. Reframe it as a walkthrough: it now describes 3 data sources (ASC API, Astro MCP, AppMate RAG) and the `config/` mechanism.

**Files:**
- Create: `skills/appmate-setup/SKILL.md`
- Source: `MyFeatures/ASC_API_SETUP.md`

- [ ] **Step 1: Write `skills/appmate-setup/SKILL.md`**

Frontmatter:
```markdown
---
name: appmate-setup
description: Set up AppMate plugin credentials and config. Use when the user wants to install, configure, or troubleshoot AppMate, set up App Store Connect API access, or run the AppMate self-check.
---
```
Body (English): adapt `ASC_API_SETUP.md`. Required changes vs. the source:
- 3 data sources, not 4 (SoloMax already removed; keep the existing removal note).
- Replace the credentials description with the `config/` model: copy `config/credentials.example.txt` → `config/credentials.txt`, fill in `issuer_id` / `key_id` / `private_key_path` / `vendor_number`, drop the `.p8` key into `config/`.
- Replace all `cd /Users/fengyq/Desktop/AppMateMax` and root-relative script paths with plugin-relative `python3 scripts/<name>.py` (run from the plugin repo root, or `${CLAUDE_PLUGIN_ROOT}/scripts/...`).
- Keep the 4-point self-check (ASC token, ASC live call, Astro probe, AppMate RAG health) — drop the old 5th SoloMax check.
- All prose in English.

---

## Task 11: Skill — `sales-daily-report`

**Files:**
- Create: `skills/sales-daily-report/SKILL.md`
- Source: `MyFeatures/SALES_DAILY_WORKFLOW.md`

- [ ] **Step 1: Write `skills/sales-daily-report/SKILL.md`**

Frontmatter:
```markdown
---
name: sales-daily-report
description: Generate the App Store sales & downloads daily report for all live apps. Use when the user asks for a sales report, revenue/downloads summary, or "跑日报"/daily numbers across their apps.
---
```
Body: faithful English translation of `SALES_DAILY_WORKFLOW.md`. Required changes:
- Replace `cd /Users/fengyq/Desktop/AppMateMax` + `python3 sales_report.py` with `python3 scripts/sales_report.py` (run from plugin root).
- Keep the report **template and the 10 formatting rules describing the Chinese output verbatim** — the prose is English, but the literal report strings/section names it instructs to emit stay Chinese (e.g. `## 🧮 总和`, emoji set).
- Preserve the "must paste full markdown back into the conversation" rule.

---

## Task 12: Skill — `aso-optimize` + translate the ASO methodology

The largest task: translate `MyFeatures/ASO_WORKFLOW.md` (446 lines) into an English skill, and translate the 1116-line methodology reference.

**Files:**
- Create: `skills/aso-optimize/SKILL.md`
- Create: `skills/aso-optimize/references/aso-methodology.md`
- Source: `MyFeatures/ASO_WORKFLOW.md`, `ToolChain/ASODatas.txt` (== `ASO_methodology.txt`, duplicates)

- [ ] **Step 1: Translate the methodology reference**

Translate `ToolChain/ASODatas.txt` in full to English into `skills/aso-optimize/references/aso-methodology.md`. Requirements:
- Preserve the section structure and numbering exactly (`§1`–`§12` and all sub-sections like `§10.1`, `§7.3`) — the skill cites these by number.
- Preserve all tables, thresholds, numeric values, examples.
- Translate prose to English. Where the methodology discusses Chinese-language ASO specifics (CJK tokenization, Chinese keyword examples), keep the Chinese example terms but explain them in English.
- This is long; translate in contiguous section batches, verifying section numbers line up after each batch.

- [ ] **Step 2: Write `skills/aso-optimize/SKILL.md`**

Frontmatter:
```markdown
---
name: aso-optimize
description: Deep ASO optimization for a single app — produce new App Store title, subtitle, and keyword strings. Use when the user wants to optimize/rewrite an app's ASO metadata, improve keyword rankings, or "跑 ASO 优化" for a specific app.
---
```
Body: faithful English translation of `ASO_WORKFLOW.md`. Required changes:
- Replace command-line references (`python3 aso_optimize_v2.py analyze <app>`, etc.) with `python3 scripts/aso_optimize_v2.py ...`.
- Update the methodology pointer: it now lives at `references/aso-methodology.md` (was `Prompts/ASODatas.txt`); keep the `§` citations.
- `phase_a_*.json` / `phase_b_*.json` / `aso_optimize_<slug>.md` artifacts now land under `data/`.
- Keep the output-format rules that mandate Chinese deliverable wording (e.g. "主标题/副标题/关键词", the no-`T/S/K` rule) verbatim — these govern the Chinese deliverable; the surrounding instructions are English.

---

## Task 13: Skill — `aso-daily-report`

**Files:**
- Create: `skills/aso-daily-report/SKILL.md`
- Source: `MyFeatures/ASO_DAILY_WORKFLOW.md`

- [ ] **Step 1: Write `skills/aso-daily-report/SKILL.md`**

Frontmatter:
```markdown
---
name: aso-daily-report
description: Generate the ASO keyword-ranking daily report for the top-3 apps by downloads. Use when the user asks for an ASO daily/monitoring report, keyword rank changes, or "跑 ASO 日报".
---
```
Body: English translation of `ASO_DAILY_WORKFLOW.md`. Required changes:
- Replace `cd /Users/fengyq/Desktop/AppMateMax` + script paths with `python3 scripts/aso_daily.py` / `python3 scripts/aso_optimize_v2.py analyze ...`.
- `aso_daily.md` / `aso_rank_snapshots.json` now under `data/`.
- Keep the Chinese report template + 8 formatting rules verbatim (English prose around them).

---

## Task 14: Skill — `feature-ideation`

**Files:**
- Create: `skills/feature-ideation/SKILL.md`
- Source: `MyFeatures/FEATURE_IDEATION_WORKFLOW.md`

- [ ] **Step 1: Write `skills/feature-ideation/SKILL.md`**

Frontmatter:
```markdown
---
name: feature-ideation
description: Generate prioritized feature recommendations for an app from reviews + competitor evidence. Use when the user wants feature ideas, a product roadmap input, or "跑功能策划" for a specific app.
---
```
Body: English translation of `FEATURE_IDEATION_WORKFLOW.md`. Required changes:
- `python3 feature_ideate.py "<app>"` → `python3 scripts/feature_ideate.py "<app>"`.
- `phase_a_feature_<slug>.json` / `feature_ideas_<slug>.md` now under `data/`.
- Keep the Chinese output template + 6 formatting rules verbatim (English prose around them); keep the "paste full markdown back" rule.

---

## Task 15: Skill — `growth-strategy`

The methodology cheat-sheet inside this doc is large and must be translated too.

**Files:**
- Create: `skills/growth-strategy/SKILL.md`
- Source: `MyFeatures/GROWTH_STRATEGY_WORKFLOW.md`

- [ ] **Step 1: Write `skills/growth-strategy/SKILL.md`**

Frontmatter:
```markdown
---
name: growth-strategy
description: Generate a stage-diagnosed growth strategy for an app — phase diagnosis plus 3-5 actionable strategies. Use when the user wants a growth plan, growth strategy, or "跑增长策略" for a specific app.
---
```
Body: English translation of `GROWTH_STRATEGY_WORKFLOW.md`, including the full "方法论小抄" (methodology cheat-sheet) section — translate all four stage playbooks to English, preserving the stage thresholds and the per-item `适用` / `来源` attributions. Required changes:
- `python3 growth_strategy.py "<app>"` → `python3 scripts/growth_strategy.py "<app>"`.
- `phase_a_growth_<slug>.json` / `growth_strategy_<slug>.md` now under `data/`.
- Cross-references to other workflow docs become references to the sibling skills (`aso-optimize`, `feature-ideation`, `aso-daily-report`).
- Keep the Chinese output template + 8 layout rules verbatim (English prose around them).

---

## Task 16: Create the 6 slash commands

Thin entry points, one per skill.

**Files:**
- Create: `commands/appmate-setup.md`, `commands/appmate-sales.md`, `commands/appmate-aso-optimize.md`, `commands/appmate-aso-daily.md`, `commands/appmate-feature-ideas.md`, `commands/appmate-growth.md`

- [ ] **Step 1: Write the 6 command files**

Each file is a thin wrapper. Pattern (example `commands/appmate-sales.md`):
```markdown
---
description: Generate the App Store sales & downloads daily report for all live apps.
---

Run the AppMate sales daily report workflow. Invoke the `sales-daily-report` skill and follow it end-to-end: run `python3 scripts/sales_report.py` from the plugin root, then paste the full Chinese markdown report back into the conversation.
```
Apply the same pattern to the other five, each pointing at its skill:
- `appmate-setup.md` → `appmate-setup` skill ("Set up or troubleshoot AppMate credentials and config.")
- `appmate-aso-optimize.md` → `aso-optimize` skill, taking an `$ARGUMENTS` app identifier
- `appmate-aso-daily.md` → `aso-daily-report` skill
- `appmate-feature-ideas.md` → `feature-ideation` skill, taking an `$ARGUMENTS` app identifier
- `appmate-growth.md` → `growth-strategy` skill, taking an `$ARGUMENTS` app identifier

- [ ] **Step 2: Commit (Tasks 10-16 together)**

```bash
git add skills/ commands/
git commit -m "feat: add 6 AppMate skills (English) + slash commands"
```

---

## Task 17: Create `plugin.json` + `marketplace.json`

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Confirm the current plugin manifest schema**

Use the `claude-code-guide` agent (or WebFetch the Claude Code plugin docs) to confirm the exact required/optional fields for `plugin.json` and `marketplace.json` in the current Claude Code version. Adjust Steps 2-3 to match.

- [ ] **Step 2: Write `.claude-plugin/plugin.json`**

```json
{
  "name": "appmate",
  "version": "0.1.0",
  "description": "App Store Connect operations toolkit for indie developers: sales reporting, ASO optimization, ASO daily monitoring, feature ideation, and growth strategy.",
  "author": { "name": "fengyiqi" }
}
```
(Adjust keys to the schema confirmed in Step 1.)

- [ ] **Step 3: Write `.claude-plugin/marketplace.json`**

A single-plugin marketplace pointing at this repo so it installs via `claude plugin marketplace add <github-url>`:
```json
{
  "name": "appmate",
  "owner": { "name": "fengyiqi" },
  "plugins": [
    {
      "name": "appmate",
      "source": "./",
      "description": "App Store Connect operations toolkit: sales, ASO, feature ideation, growth strategy."
    }
  ]
}
```
(Adjust keys to the schema confirmed in Step 1.)

- [ ] **Step 4: Validate JSON**

Run: `python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/
git commit -m "feat: add plugin.json + marketplace.json manifests"
```

---

## Task 18: Create `config/credentials.example.txt` + `config/README.md`

**Files:**
- Create: `config/credentials.example.txt`
- Create: `config/README.md`

- [ ] **Step 1: Write `config/credentials.example.txt`**

```
# AppMate config — copy this file to config/credentials.txt and fill in.
# config/credentials.txt and all .p8/.pem keys in config/ are gitignored.

# --- App Store Connect API (required) ---
issuer_id        =
key_id           =
private_key_path = config/AuthKey_XXXXXXXX.p8
vendor_number    =

# --- AppMate RAG API (optional; defaults to public BETA endpoint) ---
rag_base_url     = https://appmate.000ooo.ooo

# --- Astro MCP endpoint (optional; defaults to local Astro desktop app) ---
astro_endpoint   = http://127.0.0.1:8089/mcp
```

- [ ] **Step 2: Write `config/README.md`**

English. Explain: copy `credentials.example.txt` → `credentials.txt`; where to get `issuer_id` + `key_id` + the `.p8` file (App Store Connect → Users and Access → Integrations → App Store Connect API); where to find `vendor_number` (App Store Connect → Payments and Financial Reports); that the `.p8` file goes in `config/` and `private_key_path` may be repo-relative; that `rag_base_url` / `astro_endpoint` are optional. Note Astro requires the Astro desktop app running locally.

- [ ] **Step 3: Commit**

```bash
git add config/credentials.example.txt config/README.md
git commit -m "feat: add config template + setup README"
```

---

## Task 19: Create `docs/ASC_API_REFERENCE.md` + `docs/APPMATE_RAG_API.md`

Translate the two ToolChain reference docs to English. (`ASC_API_REFERENCE.md` is the API-reference portion of the old `ASC_API_SETUP.md` — the setup walkthrough already became the `appmate-setup` skill, so this doc keeps just the endpoint/auth reference material.)

**Files:**
- Create: `docs/ASC_API_REFERENCE.md` (from the API-reference sections of `MyFeatures/ASC_API_SETUP.md`)
- Create: `docs/APPMATE_RAG_API.md` (from `ToolChain/AppMate_RAG_API.md`)

- [ ] **Step 1: Write `docs/APPMATE_RAG_API.md`**

Full English translation of `ToolChain/AppMate_RAG_API.md` — preserve endpoints, request/response schemas, field tables, cURL examples.

- [ ] **Step 2: Write `docs/ASC_API_REFERENCE.md`**

English reference distilled from `MyFeatures/ASC_API_SETUP.md`: the ASC auth flow (ES256 JWT), common endpoints, the Astro MCP tool list, the AppMate RAG contract, and known API limitations. Exclude the step-by-step setup walkthrough (that lives in the `appmate-setup` skill).

- [ ] **Step 3: Commit**

```bash
git add docs/ASC_API_REFERENCE.md docs/APPMATE_RAG_API.md
git commit -m "docs: add English ASC API + AppMate RAG reference docs"
```

---

## Task 20: Create `requirements.txt` + `README.md`

**Files:**
- Create: `requirements.txt`
- Create: `README.md`

- [ ] **Step 1: Write `requirements.txt`**

```
PyJWT>=2.0
requests>=2.25
cryptography>=3.4
```
(`cryptography` is required by PyJWT for ES256. `pytest` is dev-only — note it in the README rather than shipping it as a runtime dep.)

- [ ] **Step 2: Write `README.md`**

English. Sections:
- **What is AppMate** — a Claude Code plugin: an App Store Connect operations toolkit for indie developers.
- **Workflows** — one line each for the 5 workflows + the setup flow, with their `/appmate-*` commands.
- **Data sources** — ASC API, Astro MCP, AppMate RAG.
- **Install** — `claude plugin marketplace add <github-url>` then enable the `appmate` plugin; `pip install -r requirements.txt`.
- **Setup** — run `/appmate-setup` (or copy `config/credentials.example.txt` → `config/credentials.txt` and fill it in).
- **Usage** — example: `/appmate-sales`, `/appmate-aso-optimize <app>`.
- **Layout** — brief tree (`skills/`, `commands/`, `scripts/`, `config/`, `data/`).
- **Note** — generated reports are in Chinese by design; source and docs are English.
- **Dev** — `pip install pytest && python3 -m pytest`.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt README.md
git commit -m "docs: add requirements.txt + README"
```

---

## Task 21: Remove source folders, final cleanup, final verification

`MyFeatures/` and `ToolChain/` content has been fully absorbed; the duplicate root methodology file is no longer needed.

**Files:**
- Delete: `MyFeatures/`, `ToolChain/`, `ASO_methodology.txt`

- [ ] **Step 1: Remove absorbed source folders**

Run:
```bash
rm -rf MyFeatures ToolChain ASO_methodology.txt
```

- [ ] **Step 2: Final structure check**

Run:
```bash
find . -path ./.git -prune -o -type f -print | grep -vE '^\./(data|config)/' | sort
```
Expected: matches the spec §3 tree — `.claude-plugin/`, `skills/` (6 SKILL.md + 1 references file), `commands/` (6), `scripts/` (17 .py), `tests/` (4 + `__init__.py`), `docs/`, `.gitignore`, `pyproject.toml`, `requirements.txt`, `README.md`. No `MyFeatures/` or `ToolChain/`.

- [ ] **Step 3: Full verification**

Run: `python3 -m pytest -q` — expect all PASS.
Run: `grep -rn "/Users/fengyq" --include="*.py" --include="*.md" . | grep -v docs/superpowers` — expect no output (no hardcoded paths in shipped files; the superpowers specs/plans may mention the path historically and are exempt).
Run: `git status --short` — confirm no secrets or `data/` files staged.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: remove absorbed MyFeatures/ + ToolChain/ source folders"
```

---

## Self-Review Notes

- **Spec coverage:** §3 structure → Tasks 1,10-21. §4 config model → Task 2. §5 script changes → Tasks 3-7,9. §6 skills/commands → Tasks 10-16. §7 deployment artifacts → Tasks 17,18,20. §8 verification → Tasks 8,21. §9 out-of-scope respected (no deep refactor, no output translation, no auto-push).
- **Translation rule** is stated in Task 9 and echoed in each skill task (keep Chinese report-output strings, translate prose).
- **Type/name consistency:** `appmate_config` accessor names (`asc_issuer_id`, `asc_key_id`, `asc_vendor_number`, `asc_private_key_path`, `rag_base_url`, `astro_endpoint`, `data_path`, `config_path`, `DATA_DIR`, `CONFIG_DIR`) defined in Task 2 are used consistently in Tasks 3-7.
- **Known soft spots:** exact `plugin.json`/`marketplace.json` schema is verified live in Task 17 Step 1 (Claude Code plugin format evolves). `fetch_metadata.py`'s exact output-constant name is confirmed by reading the file in Task 7.
