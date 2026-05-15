---
name: aso-daily-report
description: Generate the ASO keyword-ranking daily report for the top-3 apps by downloads. Use when the user asks for an ASO daily report, ASO monitoring, keyword rank changes, or "跑 ASO 日报".
---

# ASO Monitoring Daily Report

> Run once to watch the keyword-ranking changes of the top-3 apps in their main markets.

## Step 0 — Prerequisites (credentials must be configured)

Every step in this skill calls App Store Connect APIs. **Before any other step**, run:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Do not invoke any other part of this skill, do not run `scripts/aso_daily.py`. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup`. The downstream script also enforces this gate (exits 2 with the same message), but the explicit precheck avoids wasted iTunes Search calls.

## One-line summary

Take the top-3 apps by download volume → find each one's main market → **LLM semantic tokenization** → query iTunes Search for rankings → rank ≤ 20 enters the "target keyword group" → popularity & difficulty come from the static keyword reference → compare against yesterday's snapshot → markdown report.

## Difference from the `aso-optimize` skill

| | **ASO daily report** (this skill) | **ASO optimize** (`aso-optimize` skill) |
|---|---|---|
| Trigger | user runs it occasionally | on demand, single app |
| Scope | runs all top-3 apps | one app, deep optimization |
| Purpose | **monitor** changes + rank delta | **generate** new metadata |
| Output | dashboard tables | paste-ready 3-string set |
| LLM role | tokenization only (Step 2) | the whole flow |
| User intervention | 2 (trigger + provide the LLM tokenization loop) | 2 (trigger + receive the final) |
| Candidate filter | rank ≤ 20 = target word | **no filter** — full data |
| Report granularity | horizontal comparison of 3 apps | single-app depth |

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | the user asks → you (Claude) start the flow |
| **Input** | `data/apps_full.json` (live-app list) + `data/sales_cache.json` (top-3) + `data/aso_rank_snapshots.json` (yesterday's snapshot) |
| **Output** | in-conversation markdown + `data/aso_daily.md` file |

## Workflow (3 stages)

1. **Step 1: get the top-3 + each one's current state (script)** — descending by 30-day downloads; skip not-live / DEVELOPER_REJECTED; for each app: find the single largest market, pick the locale, extract raw title/subtitle/keywords. Output an intermediate JSON (the raw metadata of the 3 apps).
2. **Step 2: LLM tokenization (you, conversation layer)** — read each app's raw metadata; cut real ASO words with Chinese semantics; reject long CJK mashed runs (≥ 6 chars are usually invalid); output a token list per app.
3. **Step 3: validate + render (script + LLM)** — script: each token → iTunes rank + popularity + difficulty; write today's snapshot to `data/aso_rank_snapshots.json`; compare against yesterday's snapshot to compute the delta; filter to rank ≤ 20 = target words; LLM renders per the report template.

## User intervention points (2)

1. **Start**: the user says "run the ASO daily report".
2. **Step 2 LLM tokenization**: you read the raw metadata of the 3 apps and produce the token list for the script (the user does nothing, but the LLM's thinking is an intervention).

Overall experience: **trigger → you run it all yourself → give the user the report**.

## Report template (v1 — follow exactly)

The rendered report is in **Chinese** by design. Do not translate the rendered output.

### Top one-liner (required)

```
**昨天 ({MM-DD}) 数据 · 排名 = App Store 网页搜索 · 热度/难度 = 内部指标**
```

### Per-app block (top 3 by 30-day downloads)

```markdown
## {idx}. {app_name}  ·  {platform}  ·  {flag} {country}

昨日下载 **{N}**  ·  目标词 **{X}** 个（排名 ≤ 20，从 {Y} 个候选中筛出）

> ⚠️ 若没有该 country 对应语言族的本地化，提示一行

| 关键词 | 排名 | Δ | 热度 | 难度 |
|---|:-:|:-:|:-:|:-:|
| `keyword` | **#N** | ↑3 | **88** 🔥 | 44 🟢 |
| ... | ... | ↓1 | ... | ... |
```

Sorting: **descending by popularity**, ties by ascending rank.

## 8 inviolable rules

1. Top one-liner only (`昨天(MM-DD) 数据 …`), do not stack metadata rows.
2. Each app uses `H2 (##)`, **single-market focus**, do not show multiple markets.
3. **Do not** show source tags (T/S/K/X), **do not** add a suggestions column, **do not** show competitor counts.
4. **Must** show the delta (even if it is all `—` on day one).
5. Difficulty colors: ≥ 70 🔴 hard · 50-69 🟡 medium · < 50 🟢 easy.
6. Heat colors: ≥ 50 🔥 · otherwise plain number.
7. Rank ≤ 10 bold `**#N**`, 11-20 plain `#N`, > 20 should not appear (already filtered by `TARGET_RANK_CEILING`).
8. **Must paste back into the conversation** — after running the script, Claude must paste the complete markdown report into the reply; "aso_daily.md generated" alone or a summary alone is not allowed.

## Data source conventions

| Dimension | Source |
|---|---|
| Pick top-3 apps | `data/sales_cache.json`, 30-day downloads descending |
| Yesterday's downloads (per market) | `data/sales_cache.json` (iTunes Connect sales report) |
| Main market (single focus) | the country with the largest 30-day downloads |
| Title / subtitle | `data/apps_full.json` `appInfo.localizations[picked_locale]` |
| Keyword field | `data/apps_full.json` `versions[latest].localizations[picked_locale]` |
| Candidate tokenization | **LLM semantic split** (not regex / jieba) |
| Rank | iTunes Search Top-200 (same source as the App Store web page) |
| Heat (1-99) | `keyword_local.lookup_popularity_batch` — backed by `data/keyword_reference_<region>.json` |
| Difficulty (1-99) | same as above |
| Δ vs yesterday | `data/aso_rank_snapshots.json` comparing today's/yesterday's snapshot |

## Why not regex / jieba tokenization

| Approach | Problem |
|---|---|
| **regex** | long CJK runs (e.g. `网络翻译邮箱地图地球`) cannot be split → rejected by `_good_token`'s CJK ≥ 6 rule → real target words lost |
| **jieba** | boundary judgment is often wrong (`便利贴` → `便利`+`贴`), and it cannot recognize ASO-domain words (`桌面便签`, `云便签`, etc.) |
| **LLM** | ✓ semantic understanding — recognizes compound words, brand variants, typos, domain words |

## Key parameters

| Parameter | Value | Note |
|---|---|---|
| `TARGET_RANK_CEILING` | 20 | rank ≤ this value enters the target keyword group (monitoring view) |
| Top-N | 3 | default top 3 apps |

## CLI

```bash
# from the plugin repo root

# existing automatic version (regex tokenization — misses long CJK runs)
python3 scripts/aso_daily.py

# new version (LLM tokenization): two steps
# Step 1: run analyze separately for each top-3 app with the v2 tool
python3 scripts/aso_optimize_v2.py analyze "<app 1>"
python3 scripts/aso_optimize_v2.py analyze "<app 2>"
python3 scripts/aso_optimize_v2.py analyze "<app 3>"

# Step 2-3: paste the 3 phase_a JSONs to Claude, who does the LLM
# tokenization + validate + render
```

## Connection to the ASO optimize workflow

- Each daily-report run that finds an app's keyword dropping out of the top 20 → trigger the `aso-optimize` skill (`aso_optimize_v2.py analyze <app>`) for a deep optimization.
- The `aso-optimize` skill outputs new metadata → the user updates App Store Connect → a few days later the daily report shows the rank change.

## Known limits

- Apple's sales data lags 1-2 days → the report's data date is usually 2 days ago.
- The rank ≤ 20 filter: the daily report only shows "hit" words; words that did not rank in do not appear (this differs from `aso-optimize`, which sees the full set).
- The main market is fixed and single — if an app has volume in multiple markets, only the largest is run.
- LLM tokenization requires you (Claude) to think once in the conversation; it cannot run unattended via cron.
