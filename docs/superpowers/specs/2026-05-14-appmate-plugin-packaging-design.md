# AppMate Plugin Packaging — Design Spec

**Date**: 2026-05-14
**Status**: Approved (user approved structure and directed direct execution)
**Topic**: Package the AppMateMax folder into a GitHub-deployable Claude Code plugin named "AppMate"

---

## 1. Background & Goal

The `AppMateMax` folder is a working toolkit for an indie App Store developer: Python
data-layer scripts plus six Chinese workflow docs that drive LLM behavior across five
operational workflows (sales reporting, ASO optimization, ASO daily monitoring, feature
ideation, growth strategy) and one setup procedure.

**Goal**: turn this folder into a clean, GitHub-deployable **Claude Code plugin** named
**AppMate**, where every workflow that has a process doc is clearly, explicitly, and
stably usable. Restructure happens **in place** (`git init` in `/Users/fengyq/Desktop/AppMateMax`).

## 2. Decisions (locked during brainstorming)

| # | Decision |
|---|---|
| 1 | "PlugIn" = a Claude Code plugin: `.claude-plugin/plugin.json`, `skills/`, `commands/`, bundled `scripts/`. |
| 2 | **English scope = source + docs only.** All code comments/docstrings/diagnostic logs, all `SKILL.md` / command / repo markdown become English. **Generated report output stays Chinese** (preserves established report formatting). |
| 3 | **Restructure in place** — `git init` in the existing folder; secrets + caches move into gitignored subdirs. |
| 4 | **Config = gitignored `config/` dir + `/appmate-setup` skill.** Secrets and account constants live in `config/`; a shared `appmate_config.py` module is the single read point. |
| 5 | **Entry points = skills + slash commands.** 5 workflow skills + 1 setup skill, plus 6 `/appmate-*` commands. |
| 6 | **ASO methodology translated fully to English** (the 1116-line `§1–§12` reference). |
| 7 | **Approach B — repackage + light refactor.** Centralize paths + account constants into `appmate_config.py`; otherwise leave workflow logic untouched. |
| 8 | SoloMax RAG MCP already removed from the project (prior task). |

## 3. Repo Structure

```
AppMateMax/                          ← repo root = the plugin
├── .claude-plugin/
│   ├── plugin.json                  ← plugin manifest
│   └── marketplace.json             ← single-plugin marketplace (installable by git URL)
├── skills/
│   ├── appmate-setup/SKILL.md
│   ├── sales-daily-report/SKILL.md
│   ├── aso-optimize/
│   │   ├── SKILL.md
│   │   └── references/aso-methodology.md   ← translated 1116-line methodology
│   ├── aso-daily-report/SKILL.md
│   ├── feature-ideation/SKILL.md
│   └── growth-strategy/SKILL.md
├── commands/
│   ├── appmate-setup.md
│   ├── appmate-sales.md
│   ├── appmate-aso-optimize.md
│   ├── appmate-aso-daily.md
│   ├── appmate-feature-ideas.md
│   └── appmate-growth.md
├── scripts/                         ← 15 existing Python scripts + NEW appmate_config.py
├── tests/                           ← existing 3 test files (kept)
├── docs/
│   ├── ASC_API_REFERENCE.md         ← from MyFeatures/ASC_API_SETUP.md, translated + trimmed
│   ├── APPMATE_RAG_API.md           ← from ToolChain/AppMate_RAG_API.md, translated
│   └── superpowers/                 ← existing specs/plans, kept (including this file)
├── config/                          ← GITIGNORED. ships only credentials.example.txt + README.md
├── data/                            ← GITIGNORED. all caches + run outputs land here (.gitkeep)
├── .gitignore
├── requirements.txt
└── README.md                        ← English: what it is, install, /appmate-setup, usage
```

**File moves:**
- 15 Python scripts → `scripts/`
- 6 `MyFeatures/*.md` → 6 `skills/*/SKILL.md` (translated to English)
- Secrets (`credentials.txt`, `AuthKey_*.p8`, `searchads_private.p8`, `searchads_public.pem`,
  `search_ads_credentials.txt`, `.search_ads_token.json`) → `config/` (gitignored)
- Caches/snapshots/outputs (`apps_full.json`, `apps_metadata.json`, `app_icons.json`,
  `sales_cache.json`, `aso_rank_cache.json`, `aso_rank_snapshots.json`,
  `astro_popularity_cache.json`, `aso_popularity_cache.json`, `aso_hints_cache.json`,
  `perf_metrics.json`, `.appmate_rag_cache/`, `phase_*.json`, `report.md`, `aso_daily.md`,
  `aso_report.md`, `aso_astro.md`, `aso_optimize.md`, `*_cn.md`,
  `report_template.md`, `aso_daily_template.md`) → `data/` (gitignored)
- `ASO_methodology.txt` + `ToolChain/ASODatas.txt` are duplicates → deduped, translated into one
  `skills/aso-optimize/references/aso-methodology.md`
- `MyFeatures/` and `ToolChain/` folders are removed (contents absorbed above)
- `__pycache__/`, `.pytest_cache/`, `.DS_Store` deleted; covered by `.gitignore`

## 4. Config & Secrets Model

New module `scripts/appmate_config.py` is the single source of truth for paths and
account-specific values. Every other script imports it instead of hardcoding.

**Path resolution (eager — pure pathlib, never fails):**
- `PLUGIN_ROOT` = parent of `scripts/` (resolved from `__file__`)
- `APPMATE_HOME` = env var `APPMATE_HOME` if set, else `PLUGIN_ROOT`
  (lets installed-plugin users keep data outside the plugin cache dir)
- `DATA_DIR` = `APPMATE_HOME/data`, `CONFIG_DIR` = `APPMATE_HOME/config`
- helpers: `data_path(name)`, `config_path(name)` (create `DATA_DIR` on first write)

**Credential loading (lazy + graceful):**
- Reads `config/credentials.txt` (`key = value` lines) only when first accessed; result cached.
- Missing file does **not** crash import — critical so a fresh checkout (and the test suite)
  can import every module without credentials present.
- Accessors: `asc_issuer_id()`, `asc_key_id()`, `asc_private_key_path()`, `asc_vendor_number()`
  raise a clear error pointing to `/appmate-setup` only when a missing secret is actually used.
- Non-secret accessors carry defaults: `rag_base_url()` → `https://appmate.000ooo.ooo`,
  `astro_endpoint()` → `http://127.0.0.1:8089/mcp`.

**`config/credentials.example.txt` (shipped template):**
```
# AppMate config — copy to config/credentials.txt and fill in. credentials.txt is gitignored.
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
`config/README.md` explains where to obtain each value (ASC API key, vendor number, `.p8` file).

## 5. Script Changes (mechanical, Approach B)

All 15 scripts get the same mechanical treatment — **no workflow logic changes**:
1. Replace `pathlib.Path(__file__).with_name("<cache>.json")` and similar with
   `appmate_config.data_path("<cache>.json")`.
2. Replace credential/constant loading with `appmate_config` accessors:
   - `asc_client.py`: `_load_credentials()` + `VENDOR_NUMBER` constant → `appmate_config`
     accessors; switch module-level `_CREDS` to lazy use inside `make_token()`/`sales_report()`.
   - `astro_client.py`: `ENDPOINT`, `POP_CACHE_PATH` → `appmate_config`.
   - `appmate_rag_client.py`: `BASE_URL` → `appmate_config.rag_base_url()`.
   - `sales_report.py`, `aso_report.py`, `aso_optimize.py`, `aso_daily.py`, `aso_astro.py`,
     `aso_optimize_v2.py`, `feature_ideate.py`, `growth_strategy.py`, `fetch_full.py`,
     `fetch_metadata.py`, `fetch_icons.py`, `app_analytics.py`: all `APPS_FULL` / `SALES_CACHE`
     / cache / snapshot / output path constants → `appmate_config.data_path(...)`.
3. Inter-script imports are unchanged (the 5 ASO scripts remain an interdependent set;
   `aso_optimize.py` + `aso_report.py` still provide shared functions).

**English translation rule for code** (the subtle part):
- **→ English**: comments, docstrings, `print()` / diagnostic / log strings, CLI usage text.
- **Unchanged (stays Chinese)**:
  - functional Chinese literals used for matching/detection — e.g. `WISH_TRIGGERS` review
    trigger words in `feature_ideate.py`, locale/country tables;
  - report **output** strings — rendered markdown templates (`## 🧮 总和`, `DIM_LABELS_CN`,
    table headers, etc.). The English `SKILL.md` *describes* producing this Chinese output.

## 6. Skills & Commands

Six skills, each translated from its source workflow doc, with proper plugin `SKILL.md`
frontmatter (`name`, `description`). Source mapping:

| Skill (`skills/<dir>/SKILL.md`) | Source doc | Command |
|---|---|---|
| `appmate-setup` | `MyFeatures/ASC_API_SETUP.md` (reframed as a setup walkthrough) | `/appmate-setup` |
| `sales-daily-report` | `MyFeatures/SALES_DAILY_WORKFLOW.md` | `/appmate-sales` |
| `aso-optimize` | `MyFeatures/ASO_WORKFLOW.md` (+ `references/aso-methodology.md`) | `/appmate-aso-optimize` |
| `aso-daily-report` | `MyFeatures/ASO_DAILY_WORKFLOW.md` | `/appmate-aso-daily` |
| `feature-ideation` | `MyFeatures/FEATURE_IDEATION_WORKFLOW.md` | `/appmate-feature-ideas` |
| `growth-strategy` | `MyFeatures/GROWTH_STRATEGY_WORKFLOW.md` | `/appmate-growth` |

- **Skills**: full English process doc. All `cd /Users/fengyq/Desktop/AppMateMax` references
  become plugin-relative (`scripts/` invoked via `${CLAUDE_PLUGIN_ROOT}` or repo-relative).
  The `aso-optimize` skill carries the methodology as a `references/` file.
- **Commands**: thin entry points — frontmatter + a short body that invokes the matching
  skill and states the one-line trigger. They give users explicit, discoverable `/`-handles.
- `appmate-setup` skill walks the user through copying `credentials.example.txt`, filling it
  in, placing the `.p8` key, and running the 4-point self-check.

## 7. GitHub Deployment Artifacts

- **`.claude-plugin/plugin.json`** — manifest: `name: "appmate"`, `version: "0.1.0"`,
  `description`, `author`. Exact schema verified against current Claude Code plugin docs
  during implementation.
- **`.claude-plugin/marketplace.json`** — single-plugin marketplace pointing at `./` so the
  repo is installable via `claude plugin marketplace add <github-url>`.
- **`.gitignore`**:
  ```
  config/*
  !config/credentials.example.txt
  !config/README.md
  data/*
  !data/.gitkeep
  __pycache__/
  *.pyc
  .pytest_cache/
  .DS_Store
  .appmate_rag_cache/
  ```
- **`requirements.txt`** — `PyJWT`, `requests`, `cryptography` (runtime); note `pytest` for dev.
- **`README.md`** — English: what AppMate is, the 4 data sources, install steps, `/appmate-setup`,
  and a one-liner per workflow command.

## 8. Verification

- `python3 -m pytest tests/` stays green after the refactor (path module change must not
  break the 3 existing test files).
- **Fresh-checkout import smoke test**: with no `config/credentials.txt` present,
  `import appmate_config` and importing every client/workflow script succeeds (proves lazy
  credential loading).
- `plugin.json` / `marketplace.json` parse as valid JSON and match the plugin schema.
- Manual: structure matches §3; no `/Users/fengyq` paths remain in tracked files;
  no secrets tracked by git.

## 9. Out of Scope

- Approach C (deep refactor / Python-package restructure / merging the 5 ASO scripts).
- Translating generated report **output** to English.
- New workflows or new script functionality.
- Auto-pushing to GitHub (the user pushes; we prepare the repo + initial commit only).
- Live end-to-end runs against Apple/Astro/RAG APIs (no credentials in the build environment).
