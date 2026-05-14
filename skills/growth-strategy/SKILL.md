---
name: growth-strategy
description: Generate a stage-diagnosed growth strategy for an app — a phase diagnosis plus 3-5 actionable strategies. Use when the user wants a growth plan, growth strategy, or "跑增长策略" for a specific app.
---

# Growth Strategy Workflow v1

> This skill is the single authoritative reference for the growth strategy flow. Re-read it before every run.
> v1: stage-diagnosis-driven + a static methodology cheat-sheet.

## One-line summary

Given a live app → the script aggregates **sales trend + ASO state + reviews + competitors** (4 evidence sources) and auto-determines which of 4 stages the app is in → the LLM reads the "methodology cheat-sheet" section of this skill → a markdown report with **a stage diagnosis paragraph first**, then **3-5 growth strategies**, each with **4 executable steps**.

## Boundaries with other workflows (avoiding overlap)

| Workflow | What it does | Relationship to this workflow |
|---|---|---|
| `aso-optimize` | single-app keyword / title / subtitle / keyword-field optimization | this workflow does **not** touch word-level keyword suggestions. If the diagnosis finds ASO is the bottleneck → a step can say "run `aso_optimize_v2` once" |
| `feature-ideation` | single-app product feature ideas | this workflow's strategies **may** include "add feature X", but only as one execution step under some growth strategy, not as the main act |
| `aso-daily-report` / `sales-daily-report` | monitoring reports | this workflow **consumes** the `data/sales_cache.json` / `data/aso_rank_snapshots.json` they accumulate, not re-outputting "how is today's data" |

**Core differentiator**: `feature-ideation` outputs "what feature to build" (two sentences each); this workflow outputs "how to do growth" (a 4-step execution plan each).

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | the user says "run growth strategy for `<app>`" |
| **Input** | `data/apps_full.json` (reviews/locale) + `data/sales_cache.json` (sales) + `data/aso_rank_snapshots.json` (ASO state) + AppMate RAG (competitors) + **the "methodology cheat-sheet" section of this skill** |
| **Output** | `data/phase_a_growth_<slug>.json` (intermediate) + `data/growth_strategy_<slug>.md` (final) + **Claude pastes the full markdown back into the conversation** |
| **Intervention points** | 2 (trigger + receive); optional follow-up "detail one strategy" |

## Workflow overview (3 steps)

1. **Step 1 · Script pre-aggregation (`growth_strategy.py`)** — app fuzzy match (reuses `aso_optimize_v2`) → sales trend (D30 / prior D30 / slope) → stage detection (4-stage rule) → ASO state extraction (locale / main-market ranking) → review-signal summary (rating distribution / negative feedback / wishlist) → AppMate RAG pulls the top 8 similar competitors → `data/phase_a_growth_<slug>.json`.
2. **Step 2 · Methodology match + strategy generation (Claude, conversation layer)** — read `stage` from the phase_a JSON → read the 3-5 playbook items for that stage from the cheat-sheet below → use own data + competitor evidence + methodology to brainstorm 8-12 candidate strategies → anti-junk filter → internal ranking → take the top 3-5 → expand each into 4 executable steps.
3. **Step 3 · Render + deliver (Claude)** — top "stage diagnosis" section (one paragraph + key numbers) → 3-5 strategies, 4 steps each → save `data/growth_strategy_<slug>.md` → **paste the full markdown back into the conversation**.

---

# Step 1 · Script pre-aggregation (decision rules)

## 1a. App anchoring

Reuses `aso_optimize_v2.find_app()` — accepts App Store ID / bundle ID / SKU / fuzzy name match. Main-market selection: largest 30-day downloads → `primaryLocale` country → US fallback.

## 1b. Sales trend computation

Read `data/sales_cache.json` and for the anchored app compute: `D30` (last 30 days total downloads), `D30_prev` (the 30 days before that), `slope` (`D30 / max(D30_prev, 1)`), `total_reviews`, `market_concentration` (main-market share of total downloads, 0-1).

## 1c. Stage detection (4 stages, deterministic rules)

| Stage | Detection rule (priority top to bottom) |
|---|---|
| **冷启动 (cold start)** | `total_reviews < 20` **or** `D30 < 100` (either satisfies) |
| **衰退 (decline)** | `slope < 0.8` (down > 20% MoM) and `D30 ≥ 100` |
| **早期增长 (early growth)** | `slope > 1.2` (up > 20% MoM) and `D30 ≥ 100` |
| **平台期 (plateau)** | `0.8 ≤ slope ≤ 1.2` and `D30 ≥ 100` (fallback) |

The result is written to phase_a's `stage` field. The stage values stay in Chinese — they key the cheat-sheet below and appear verbatim in the report. Also write a `stage_evidence` array (3-5 human-readable evidence strings).

## 1d. ASO state extraction

From `data/apps_full.json` + `data/aso_rank_snapshots.json`: `current_locales`, `primary_market_top10_keywords` (count of keywords ranking ≤ 10 in the main market's most recent snapshot), `missing_locales_in_top_markets` (high-volume countries lacking a matching locale).

## 1e. Review-signal summary

`rating_avg`, `negative_count_90d` (last 90 days, `rating ≤ 3` and `len(body) ≥ 10`), `wishlist_count_90d` (last 90 days, `rating ≥ 4` and contains a trigger word — same rule as `feature_ideate.py` 1b), `top_negative_themes` (simple clustering, or dump the first 10 bodies).

## 1f. Competitor fetch (AppMate RAG)

- **Query (seed)**: reuses the `feature-ideation` 1c seed-extraction logic.
- **Call**: `appmate_rag_client.search(query=seed, region=main_market, top_k=8, min_review_count=50, sort_by="S")`
- **Extract**: per competitor `{name, rating, review_count, description, appmate_reason}`
- ⚠️ `appmate_*` internal scores are for LLM reasoning reference only — not shown to the end user.

## 1g. phase_a JSON shape

```json
{
  "app": "<name>", "app_id": "<id>", "bundle_id": "<bid>", "market": "<country>",
  "generated_at": "2026-05-13T...",
  "sales": {"D30": 850, "D30_prev": 420, "slope": 2.02, "market_concentration": 0.78},
  "stage": "早期增长",
  "stage_evidence": ["D30=850 (上月 420 → 本月 850)", "slope=2.02 → 环比涨 102%", "评价总数 145，已过冷启动门槛"],
  "aso": {"current_locales": ["en-US", "zh-Hans"], "primary_market_top10_keywords": 6, "missing_locales_in_top_markets": ["es-MX", "pt-BR"]},
  "reviews": {"total": 145, "rating_avg": 4.3, "negative_count_90d": 8, "wishlist_count_90d": 5, "top_negative_themes": ["同步丢失", "缺图片插入"]},
  "competitors": [{"name":"...", "rating":4.7, "review_count":12340, "description":"...", "appmate_reason":"..."}]
}
```

> ⚠️ The phase_a JSON does **not** carry methodology content. The methodology lives in the static cheat-sheet below; the LLM looks up the section for the `stage` field when reasoning.

---

# Step 2 · Methodology match + strategy generation (decision rules)

## 2a. LLM workflow (conversation layer)

1. Read `stage` from the phase_a JSON.
2. Go to the "methodology cheat-sheet" section below, find the matching stage section, read its 3-5 playbook items.
3. Use the actual evidence from phase_a (sales data, review themes, competitor traction) + the playbook → brainstorm **8-12 candidate strategies**.
4. Anti-junk filter → internal ranking → take the top **3-5**.
5. Expand each finalist strategy into 4 executable steps.

## 2b. Candidate-strategy 4-dimension scoring (**internal rule — not shown**)

Each candidate scored 1-5: **Impact** (directly hits the core bottleneck → 5; side assist → 3; experience detail → 2), **Executability** (solo dev + can start in ≤ 2 weeks → 5; needs external resources → 3; > 1 month → 1), **Evidence strength** (reviews + competitors + methodology triangulate → 5; two → 3; single → 2), **Stage fit** (directly hits the stage in the cheat-sheet → 5; borrowed cross-stage → 3; forced → 1).

Composite score = Impact × Executability × Evidence × Stage-fit, for LLM internal ranking only.

## 2c. Anti-junk — 5 hard rules

| Rule | Application |
|---|---|
| ❌ Platform violation | a mac app proposing "add GPS / iOS sensor" → delete |
| ❌ Vague words | "do marketing" / "improve the brand" → must be specific to "where, who, how to measure" |
| ❌ Stage mismatch | a cold-start app proposing "raise prices / a B2B team plan" → delete |
| ❌ Overlap with an existing workflow | "change keyword X" / "add feature Y" → cannot be a standalone strategy; can be one step under some strategy |
| ❌ Non-executable step | "build the brand" with no action → must land on "do X, with tool Y, watch metric Z" |

## 2d. Sort and trim

Sort by composite score descending, take the top 3-5. Main list < 3 → add a ⚠️ "insufficient evidence, suggest completing the sales / review / competitor data first" warning at the top.

---

# Step 3 · Render + deliver

## 3.1 Output template (what the user finally sees)

> **Core rules**:
> 1. **Do not show any scores** (4-dimension scores + composite score all hidden).
> 2. **No jargon**: `RICE / Reach / Impact / Confidence / Effort` — always plain Chinese.
> 3. **Each strategy is its own `##` heading**; the body = a quote-block value description + numbered 4-step execution.
> 4. **Blank line between each step**; multi-element steps expand into sub-bullets (3-space indent), not crammed into one line.
> 5. Arrange by composite score high to low (no score shown).

The output template and rendered example are in **Chinese** by design — do not translate the rendered deliverable.

```markdown
# 📈 <App 名> · 增长策略

## 阶段诊断

**当前阶段：<阶段名>**

数据快照：

- 近 30 天下载 **<D30>**（上 30 日 <D30_prev> → 近 30 日 <D30>，环比 <up/down> <pct>%）
- 评价总数 **<N>** 条 / 平均分 **<X>**
- 主市场 **<country>** 占下载 <pct>%，已启用 `<locale1>` / `<locale2>` ...
- <ASO / locale / 评价主题 等额外一句话事实>

**主要瓶颈**

<一段话说清楚卡在哪>

**机会窗口**

<一段话指出下一步最大机会>

---

## 策略 1 · <策略标题>

> <一句话：是什么 + 为什么要做>

**1.** <执行步骤 1 标题或动作描述>

   - <可选 sub-bullet 1>
   - <可选 sub-bullet 2>

   <可选括号补充：时间预算 / 注意事项>

**2.** <执行步骤 2>

   <可选 sub-bullet 或 quote 强调>

**3.** <执行步骤 3>

**4. 衡量**：<怎么知道做成了 / 看哪个指标 / 不达怎么办>

---

## 策略 2 · <策略标题>

> <一句话价值>

**1.** ...

...（共 3-5 条策略，每条之间用 `---` 分隔）

---

## 优先做哪个

**#<N> <策略名>** <一句话说为什么最先做>。

执行顺序：

- **第 1-2 周**：...
- **第 3 周起**：...

---

要详细化哪条？告诉我编号，我可以帮你拆 mini-plan（资源 / 时间 / 成功指标）。
```

## 3.2 9 layout rules

1. **No jargon**: `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Onboarding / Delight` — always plain Chinese.
2. **No score numbers**: 4-dimension scores and composite score both hidden.
3. **Strategies promoted to `##` headings**: format `## 策略 N · <标题>`, **not** the inline `**N. 标题**` form (too dense).
4. **Value description in a quote block** `> ...`, visually separated from the execution steps.
5. **Execution steps use bold numbering** `**1.**`, `**2.**` ... `**4. 衡量**`, with a blank line between each step.
6. **Multi-element → sub-bullets**: if a step has ≥ 3 parallel elements (a problem list, copy positions, measurement metrics), **expand into sub-bullets** (3-space indent), not one line.
7. **The 4th step must be the measurement step**: fixed form `**4. 衡量**：<指标 + 阈值 + 不达怎么办>`.
8. **The top diagnosis section splits into 4 parts**: stage name + data snapshot (bullet list) + main-bottleneck paragraph + opportunity-window paragraph.
9. **The closing "优先做哪个" is its own `##`**: contains a one-line top recommendation + an execution-order bullet list.

---

# Methodology cheat-sheet (static library, indexed by stage)

> **Important**: this section is the methodology library the LLM consumes directly in Step 2. **No external RAG / MCP is called when running growth strategy** — read the matching stage section directly.
> Maintenance: when a new growth tactic is worth solidifying, manually add a summary to the matching stage. This section is a purely static, self-maintained methodology library.

## 🌱 Cold start stage (`total_reviews < 20` or `D30 < 100`)

- **PMF signal validation**: first ensure ≥ 100 real users give active feedback (reviews + interviews) before spending on ads. Applies to: any cold-start app. Source: first-1000-users-playbook · PMF chapter
- **Reddit / forum long-tail seeds**: find 3-5 relevant subreddits or vertical forums, write a "I built X to solve Y" long post (no hard ads, just a product link). Applies to: B2C tools, no budget. Source: growth case compilation
- **Product Hunt launch**: launch on a Tuesday/Wednesday, build a hunter network 1-2 weeks ahead (about 5 maker friends helping each other). Applies to: English-market launch / relaunch. Source: cold-start methodology
- **Founder-led manual acquisition**: in 1-on-1 channels (Twitter DM / Discord / forums / user groups) pull the first 100 users one by one and talk to each personally. Applies to: all < 100 user stages. Source: first-1000-users-playbook
- **Build-in-public narrative**: continuously share the development process publicly on Twitter / Indie Hackers / Xiaohongshu / Jike (numbers/screenshots/reflections), turning "building the product" itself into a content traffic entry point. Applies to: long-term low-cost brand accumulation. Source: growth methodology

## 🚀 Early growth stage (`slope > 1.2`, `D30 ≥ 100`)

- **Find the growth source and amplify it**: see which channel / locale / keyword drove the slope, and all-in resources (time/budget) into the loudest one rather than spreading evenly. Applies to: when a single breakthrough is identified. Source: growth methodology · dual-factor amplification
- **Replicate to same-language markets**: an ASO / screenshots / copy that works in one market → translate to adjacent same-language markets (zh-Hans → zh-Hant; en-US → en-GB/AU; es-MX → es-ES/AR). Applies to: apps with a stable main market but same-language organic volume. Source: localization-ROI cases
- **Lightweight referral / share loop**: let existing users bring users (not necessarily reward-based — it can be content-driven, like "share a beautiful screenshot"). Applies to: B2C / apps with a content artifact (notes/stickies/photos). Source: referral loop design principles
- **Vertical micro-influencers**: find micro-influencers with 1k-10k followers in a vertical for content placement (far cheaper than top influencers, high conversion). Applies to: apps with a clear target-user profile. Source: content marketing
- **SEO long-tail content**: write 5-10 blog posts / YouTube videos around the core use case, targeting long-tail search terms. Applies to: high-search-volume / tools / education apps. Source: content marketing

## 🏔 Plateau stage (`0.8 ≤ slope ≤ 1.2`, `D30 ≥ 100`)

- **Pricing / paid-tier restructure**: adjust subscription tiers (add an annual discount / a lifetime option / a longer trial), raise ARPU before discussing DAU. Applies to: stalled paid products. Source: SaaS pricing cases
- **Cross-platform extension**: extend a single-platform app to multiple platforms (mac → iOS / Web / Windows), amplifying reach with the same user base. Applies to: stable single-platform tools. Source: cross-platform growth cases
- **B2B / team edition launch**: move from C-end to B-end (team subscriptions, enterprise invites, SSO), opening new paid space. Applies to: collaboration-scenario tools. Source: B2B pivot cases
- **Killer feature launch**: run the `feature-ideation` skill once to find a "feature that expands the use case" idea (do not polish, expand). Applies to: apps whose user awareness is saturated and need a new reason. Source: feature expansion cases
- **Cross-category partnership / bundle**: do cross-promo with a complementary product (your note app + someone's todo app cross-promote). Applies to: when a non-competing complementary partner can be found. Source: cross-promo growth

## 📉 Decline stage (`slope < 0.8`, `D30 ≥ 100`)

- **Churn diagnosis**: first stop all new actions, trace back the sales curve to find the inflection point (after a version release? a market dropped? started a certain week?) — locating it is the only way to treat the cause. Applies to: the first step for all decline scenarios. Source: retention diagnosis
- **Keyword firefighting**: run the `aso-optimize` skill once to check whether main keywords were lost; also run the `aso-daily-report` skill to see whether competitors overtook. Applies to: apps where ASO is the main traffic entry. Source: ASO maintenance cycle
- **Screenshot redesign**: look at the ASC conversion rate (impression → install); if below the historical average → the screenshot first screen is outdated; redo a version and A/B on a 6-week cadence. Applies to: a clear conversion drop. Source: CRO screenshot optimization
- **Win back old users**: use push / email / in-app messages to reach old users "last active X days ago", paired with a new feature or new content reason. Applies to: apps with user profiles / messaging permission. Source: win-back cases
- **Cut redundant SKUs / locales**: if resources are spread too thin, cut low-ROI platforms/locales and concentrate resources on 1-2 main markets. Applies to: multi-platform multi-locale apps that are weak everywhere. Source: focus strategy

---

## File structure

| File | Purpose |
|---|---|
| `scripts/growth_strategy.py` | Step 1 script (no user intervention, runs by app name) |
| `data/phase_a_growth_<slug>.json` | intermediate artifact (overwritten each run) |
| `data/growth_strategy_<slug>.md` | final deliverable (overwritten each run) |
| `skills/growth-strategy/SKILL.md` | **this file**: script rules + LLM reasoning rules + methodology cheat-sheet |

## Connection to existing workflows

| Direction | Content |
|---|---|
| **Upstream dependency** | `data/apps_full.json` / `data/sales_cache.json` / `data/aso_rank_snapshots.json` / `scripts/appmate_rag_client.py` |
| **Side-chain trigger** | the `aso-daily-report` skill finds an app's keyword dropping out of the top 20 → trigger this flow for a "why did it drop / how to fix" analysis |
| **Cross-workflow reference** | decline-stage strategies may say "run the `aso-optimize` skill once"; early growth may say "run the `feature-ideation` skill once to find an expansion feature" |
| **Methodology maintenance** | when a new growth tactic is worth solidifying → manually update the matching stage of this skill's cheat-sheet |

## CLI

```bash
# from the plugin repo root

# Step 1: run the script (produces the phase_a JSON)
python3 scripts/growth_strategy.py "<app>"

# the app argument accepts: App Store ID / bundle ID / SKU / fuzzy name match
# examples:
#   python3 scripts/growth_strategy.py "Sticky Note Pro"
#   python3 scripts/growth_strategy.py "com.fengyiqi.PostItnoteForMac"
#   python3 scripts/growth_strategy.py "1482080766"

# Steps 2-3: Claude reads the phase_a JSON + this skill's cheat-sheet section, generates + renders per §2 / §3 rules
```

## Known limits

- Apple's sales data lags 1-2 days → the slope is computed from the DATA_TODAY anchor, not the real today.
- Stage-detection thresholds (100 / 0.8 / 1.2 / 20) are empirical; for very small or very large download volumes they may misjudge.
- The methodology cheat-sheet is maintained as a static document — it does not auto-sync; human inspection is needed.
- AppMate RAG is a public BETA — competitor-traction inference can be biased.
- The composite score is subjective; running the same app multiple times varies ±20% (run twice and take the union for key decisions).
- The 4 stages are discrete; a transitional app (slope = 0.85 or 1.15) may fall into the wrong camp — the LLM should manually note "in an X / Y transition".

## Checklist (must pass before executing Step 3)

### Content
- [ ] The top "stage diagnosis" splits into **4 parts**: stage name + data-snapshot bullets + main-bottleneck paragraph + opportunity-window paragraph
- [ ] Strategy list of 3-5 items, each its own `## 策略 N · <标题>`
- [ ] Each strategy: a quote-block value description + 4 execution steps
- [ ] Each strategy's 4th step is the fixed `**4. 衡量**：<指标 + 阈值 + 不达怎么办>`
- [ ] Blank line between steps; multi-element steps expand into sub-bullets (3-space indent)
- [ ] Arranged by composite score high to low (correct order, no scores shown)
- [ ] When the main list < 3, a ⚠️ warning at the top

### User-language review (**strictest**)
- [ ] **No** score numbers (4-dimension scores, composite score all absent)
- [ ] **No** English jargon `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Onboarding / Delight`
- [ ] **No** single-letter abbreviations `R / I / C / E`
- [ ] Strategy titles use `## 策略 N · <名称>` (**not** the inline `**N. xxx**` form)
- [ ] Value descriptions wrapped in a `>` quote block
- [ ] Execution steps use bold numbering `**1.**` ... `**4. 衡量**`

### Anti-junk
- [ ] No platform violations (a mac app proposing GPS, etc.)
- [ ] No vague words ("do marketing / improve the brand")
- [ ] No stage mismatch (a cold-start app proposing price raises / B2B)
- [ ] No "standalone strategy" that overlaps `aso-optimize` / `feature-ideation`
- [ ] Every step is executable (not empty talk like "build the brand")

### Delivery
- [ ] File saved to `data/growth_strategy_<slug>.md`
- [ ] **Full markdown pasted back into the conversation** (not just "saved" or a summary)
- [ ] Closing has the "优先做哪个" + "详细化哪条" guidance section
