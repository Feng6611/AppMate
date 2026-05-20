---
name: growth-strategy
description: Generate a stage-diagnosed growth strategy for an app — a phase diagnosis plus 3-5 actionable strategies. Use when the user wants a growth plan, growth strategy, or "跑增长策略" for a specific app.
---

# Growth Strategy Workflow v2

> This skill is the single authoritative reference for the growth strategy flow. Re-read it before every run.
> v2: dropped the AppMate RAG dependency. Competitors now come from the `competitor-research` skill's output (auto-chained when missing), unifying the competitive signal with `feature-ideation`. v1 had been the "RAG top-8 by seed word" design.

## Step 0 — Prerequisites

### 0.1 Credentials gate

Every step in this skill calls App Store Connect APIs. **Before any other step**, run:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Do not invoke any other part of this skill, do not run `scripts/growth_strategy.py`. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and tell them to invoke the `appmate-setup` skill. The downstream script also enforces this gate (exits 2 with the same message).

### 0.2 Competitor data: auto-chain the `competitor-research` skill if missing

This workflow consumes `data/competitors_<slug>.json`, the final artifact produced by the `competitor-research` skill (invoked for the same `<app>`). Both skills compute slug via `slugify(canonical_app_name, market)`, so passing the same app argument to both guarantees the slug matches.

**Decision rule — before invoking `growth_strategy.py`:**

1. Resolve the canonical app + market for `<app>` (read `data/apps_full.json`, call `find_app(<arg>)` → name, then pick main market via the largest 30-day downloads in `sales_cache.json` with the same fallbacks the script uses — primaryLocale, then US). Compute `expected = data/competitors_<slugify(name, market)>.json`.
2. Check whether `expected` exists.
3. **If it does not exist**, invoke the `competitor-research` skill end-to-end for the same `<app>` argument first — all three stages: Stage 1 script `analyze`, Stage 2 LLM tokenization, Stage 3 LLM relevance pass + final-JSON + markdown write. Paste the rivals markdown back into the conversation per that skill's own rules. Then return here and proceed to Step 1 of growth-strategy. The user gets two reports out of one ask: rivals first, then the growth plan. That is intentional — both are useful, and the rivals card is the same competitive evidence the LLM will read in Step 2.
4. **If it exists**, proceed directly. Optionally check `competitors_generated_at`; if it is > 30 days old, mention staleness when delivering the final growth report (do **not** auto-refresh unless the user asks).

**No RAG fallback. No placeholder competitors.** The only two paths are: the cached file, or a fresh `competitor-research` skill run.

**Safety net**: `growth_strategy.py` exits 2 with `competitors JSON not found` if the file is missing at script-execution time. This catches the case where the script was invoked outside the skill (cron, manual CLI). When it fires, treat it the same way — invoke the `competitor-research` skill for the same app, then re-run.

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
| **Input** | `data/apps_full.json` (reviews/locale) + `data/sales_cache.json` (sales) + `data/aso_rank_snapshots.json` (ASO state) + **`data/competitors_<slug>.json`** (from the `competitor-research` skill — auto-chained on first run for an app, then cached) + **the "methodology cheat-sheet" section of this skill** |
| **Output** | `data/phase_a_growth_<slug>.json` (intermediate) + `data/growth_strategy_<slug>.md` (final) + **Claude pastes the full markdown back into the conversation** |
| **Intervention points** | 2 (trigger + receive); optional follow-up "detail one strategy" |

## Workflow overview (3 steps)

1. **Step 1 · Script pre-aggregation (`growth_strategy.py`)** — app fuzzy match (reuses `aso_optimize_v2`) → sales trend (D30 / prior D30 / slope) → stage detection (4-stage rule) → ASO state extraction (locale / main-market ranking) → review-signal summary (rating distribution / negative feedback / wishlist) → load competitors from `data/competitors_<slug>.json` (Claude should have already auto-chained the `competitor-research` skill per §0.2 if the file was missing; script exits 2 as a safety net otherwise) → `data/phase_a_growth_<slug>.json`.
2. **Step 2 · Methodology match + strategy generation (Claude, conversation layer)** — read `stage` from the phase_a JSON → read the 3-5 playbook items for that stage from the cheat-sheet below → use own data + competitor evidence + methodology to brainstorm 8-12 candidate strategies → anti-junk filter → internal ranking → take the top 3-5 → expand each into 4 executable steps.
3. **Step 3 · Render + deliver (Claude)** — top "stage diagnosis" section (one paragraph + key numbers) → 3-5 strategies, 4 steps each → save `data/growth_strategy_<slug>.md` → **paste the full markdown back into the conversation**.

---

# Step 1 · Script pre-aggregation (decision rules)

## 1a. App anchoring

Reuses `aso_optimize_v2.find_app()` — accepts App Store ID / bundle ID / SKU / fuzzy name match. Main-market selection: largest 30-day downloads → `primaryLocale` country → US fallback.

## 1b. Sales trend computation

Read `data/sales_cache.json` and for the anchored app compute: `D30` (last 30 days total downloads), `D30_prev` (the 30 days before that), `slope` (`D30 / max(D30_prev, 1)`), `total_reviews`, `market_concentration` (main-market share of total downloads, 0-1).

## 1c. Stage detection (4 stages, deterministic rules)

| Stage | `stage` key emitted | Detection rule (priority top to bottom) |
|---|---|---|
| **Cold start** | `cold_start` | `total_reviews < 20` **or** `D30 < 100` (either satisfies) |
| **Decline** | `decline` | `slope < 0.8` (down > 20% MoM) and `D30 ≥ 100` |
| **Early growth** | `early_growth` | `slope > 1.2` (up > 20% MoM) and `D30 ≥ 100` |
| **Plateau** | `plateau` | `0.8 ≤ slope ≤ 1.2` and `D30 ≥ 100` (fallback) |

The result is written to phase_a's `stage` field using the exact keys `cold_start` / `decline` / `early_growth` / `plateau` — they index the cheat-sheet below. When rendering the report, translate the stage to its friendly name in the user's conversation language (e.g. "Cold start", "Decline", "Early growth", "Plateau" in English; "冷启动" / "衰退" / "早期增长" / "平台期" in Chinese). Also write a `stage_evidence` array (3-5 human-readable evidence strings, in English as emitted by the script — the LLM translates them when rendering).

## 1d. ASO state extraction

From `data/apps_full.json` + `data/aso_rank_snapshots.json`: `current_locales`, `primary_market_top10_keywords` (count of keywords ranking ≤ 10 in the main market's most recent snapshot), `missing_locales_in_top_markets` (high-volume countries lacking a matching locale).

## 1e. Review-signal summary

`rating_avg`, `negative_count_90d` (last 90 days, `rating ≤ 3` and `len(body) ≥ 10`), `wishlist_count_90d` (last 90 days, `rating ≥ 4` and contains a trigger word from the static `_WISH_TRIGGERS` list in `growth_strategy.py`), `top_negative_themes` (simple clustering, or dump the first 10 bodies).

> The bucketing helpers (`bucket_reviews`, `_has_wish_trigger`, etc.) live inline in `growth_strategy.py` — they used to be imported from `feature_ideate.py`, but feature_ideate v3 dropped pre-bucketing and the helpers were moved here.

## 1f. Competitor loader (no RAG)

`load_competitors(app_name, market)` reads `OUTPUT_DIR / f"competitors_{slugify(app_name, market)}.json"`. The file is the final artifact of the `competitor-research` skill (see `skills/competitor-research/SKILL.md`). Per §0.2, Claude should ensure this file exists *before* invoking the script — by auto-chaining that skill when it's missing.

| Step | Behavior |
|---|---|
| File missing | return `None` → `build_phase_a` returns `None` → `main()` prints a safety-net message pointing at the `competitor-research` skill and exits 2. Normally never fires when the skill flow was followed; fires if the script was invoked directly. |
| File present | read `payload["filtered"]` (already top-10 by `threat_score`, already passed the LLM relevance pass) and copy these fields per entry: `name`, `description_short`, `outranked_keywords`, `relevance_reason`, `threat_score`, `rating`, `review_count` |
| Stale data | the script does **not** check `generated_at` freshness; it surfaces the timestamp in phase_a so the LLM can flag staleness in the report if it looks old (> 30 days) |

> **v1 → v2 change**: v1 called `appmate_rag_client.search(query=seed, region=market, top_k=8, ...)` directly with a seed-word the script picked from the app's name. The seed-extraction was fragile (compound brand names lost context, English-only `"app"` fallback returned useless rivals) and the RAG result was a different shape than the SERP-overlap rivals produced by the `competitor-research` skill. v2 reuses the already-curated, already-LLM-filtered result of that skill, so growth-strategy and feature-ideation produce a coherent picture of the same competitive landscape.

## 1g. phase_a JSON shape

```json
{
  "app": "<name>", "app_id": "<id>", "bundle_id": "<bid>", "market": "<country>",
  "generated_at": "2026-05-13T...",
  "sales": {"D30": 850, "D30_prev": 420, "slope": 2.02, "market_concentration": 0.78},
  "stage": "early_growth",
  "stage_evidence": ["D30=850 (prior 30 days 420 → last 30 days 850)", "slope=2.02 → MoM up 102%", "reviews 145, past the cold-start threshold"],
  "aso": {"current_locales": ["en-US", "zh-Hans"], "primary_market_top10_keywords": 6, "missing_locales_in_top_markets": ["es-MX", "pt-BR"]},
  "reviews": {"total": 145, "rating_avg": 4.3, "negative_count_90d": 8, "wishlist_count_90d": 5, "top_negative_themes": ["同步丢失", "缺图片插入"]},
  "competitors_source": "<absolute path to competitors_<slug>.json>",
  "competitors_generated_at": "<timestamp from competitors_<slug>.json>",
  "competitors": [
    {"name": "...", "description_short": "...", "outranked_keywords": ["..."],
     "relevance_reason": "...", "threat_score": 42, "rating": 4.7, "review_count": 1234}
  ]
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
> 2. **No jargon**: `RICE / Reach / Impact / Confidence / Effort` — always plain prose in the user's conversation language.
> 3. **Each strategy is its own `##` heading**; the body = a quote-block value description + numbered 4-step execution.
> 4. **Blank line between each step**; multi-element steps expand into sub-bullets (3-space indent), not crammed into one line.
> 5. Arrange by composite score high to low (no score shown).

**Rendered in the same language the user has been using in this conversation.** Default to English; if the user has been writing in Chinese / Japanese / Spanish / etc., translate the template headers, labels and prose accordingly. App Store metadata strings (title / subtitle / keywords / competitor app names) must remain in the App Store's source locale (e.g. zh-Hans names stay zh-Hans) — only the surrounding explanation follows the user's conversation language.

The template below is written with English placeholders. Substitute the equivalent words in the user's conversation language when rendering.

```markdown
# 📈 <App name> · Growth strategy

## Stage diagnosis

**Current stage: <Stage name>**

Data snapshot:

- 30-day downloads **<D30>** (prior 30 days <D30_prev> → last 30 days <D30>, <up/down> <pct>% MoM)
- Total reviews **<N>** / average rating **<X>**
- Main market **<country>** holds <pct>% of downloads, locales enabled: `<locale1>` / `<locale2>` ...
- <one extra fact: ASO / locale / review themes>

**Main bottleneck**

<one paragraph explaining where the app is stuck>

**Opportunity window**

<one paragraph indicating the biggest near-term opportunity>

---

## Strategy 1 · <Strategy title>

> <one sentence: what it is + why do it>

**1.** <execution step 1 title or action description>

   - <optional sub-bullet 1>
   - <optional sub-bullet 2>

   <optional parenthetical: time budget / caveats>

**2.** <execution step 2>

   <optional sub-bullet or quote emphasis>

**3.** <execution step 3>

**4. Measure**: <how you know it worked / which metric to watch / what to do if it misses>

---

## Strategy 2 · <Strategy title>

> <one-sentence value>

**1.** ...

... (3-5 strategies total, separated by `---`) ...

---

## Which one first

**#<N> <Strategy name>** <one sentence saying why this goes first>.

Execution order:

- **Weeks 1-2**: ...
- **From week 3**: ...

---

Want one expanded? Tell me the number and I can help break it into a mini-plan (resources / timeline / success metrics).
```

## 3.2 9 layout rules

1. **No jargon**: `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Onboarding / Delight` — always plain prose in the user's conversation language.
2. **No score numbers**: 4-dimension scores and composite score both hidden.
3. **Strategies promoted to `##` headings**: format `## Strategy N · <Title>` (translated to the user's conversation language, e.g. `## 策略 N · <标题>` in Chinese), **not** the inline `**N. Title**` form (too dense).
4. **Value description in a quote block** `> ...`, visually separated from the execution steps.
5. **Execution steps use bold numbering** `**1.**`, `**2.**` ... `**4. Measure**` (translated to the user's conversation language), with a blank line between each step.
6. **Multi-element → sub-bullets**: if a step has ≥ 3 parallel elements (a problem list, copy positions, measurement metrics), **expand into sub-bullets** (3-space indent), not one line.
7. **The 4th step must be the measurement step**: fixed form `**4. Measure**: <metric + threshold + what to do if missed>` (translated to the user's conversation language).
8. **The top diagnosis section splits into 4 parts**: stage name + data snapshot (bullet list) + main-bottleneck paragraph + opportunity-window paragraph.
9. **The closing "Which one first" is its own `##`** (translated to the user's conversation language): contains a one-line top recommendation + an execution-order bullet list.

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
| **Upstream auto-chain** | `data/apps_full.json` / `data/sales_cache.json` / `data/aso_rank_snapshots.json` + **`data/competitors_<slug>.json`**. When the competitors file is missing, this skill first invokes the `competitor-research` skill for `<app>` end-to-end (rivals markdown gets pasted back as a side effect), then continues. |
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
- The competitor list reflects whenever the `competitor-research` skill was last run for this app — staleness shows up in `competitors_generated_at`; if it's > 30 days old, suggest re-running the prereq before trusting the report.
- The composite score is subjective; running the same app multiple times varies ±20% (run twice and take the union for key decisions).
- The 4 stages are discrete; a transitional app (slope = 0.85 or 1.15) may fall into the wrong camp — the LLM should manually note "in an X / Y transition".

## Checklist (must pass before executing Step 3)

### Content
- [ ] The top "stage diagnosis" splits into **4 parts**: stage name + data-snapshot bullets + main-bottleneck paragraph + opportunity-window paragraph
- [ ] Strategy list of 3-5 items, each its own `## Strategy N · <Title>` (translated to the user's conversation language)
- [ ] Each strategy: a quote-block value description + 4 execution steps
- [ ] Each strategy's 4th step is the fixed `**4. Measure**: <metric + threshold + what to do if missed>` (translated to the user's conversation language)
- [ ] Blank line between steps; multi-element steps expand into sub-bullets (3-space indent)
- [ ] Arranged by composite score high to low (correct order, no scores shown)
- [ ] When the main list < 3, a ⚠️ warning at the top

### User-language review (**strictest**)
- [ ] **No** score numbers (4-dimension scores, composite score all absent)
- [ ] **No** English jargon `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Onboarding / Delight`
- [ ] **No** single-letter abbreviations `R / I / C / E`
- [ ] Strategy titles use `## Strategy N · <Name>` translated to the user's conversation language (**not** the inline `**N. xxx**` form)
- [ ] Value descriptions wrapped in a `>` quote block
- [ ] Execution steps use bold numbering `**1.**` ... `**4. Measure**` (translated to the user's conversation language)

### Anti-junk
- [ ] No platform violations (a mac app proposing GPS, etc.)
- [ ] No vague words ("do marketing / improve the brand")
- [ ] No stage mismatch (a cold-start app proposing price raises / B2B)
- [ ] No "standalone strategy" that overlaps `aso-optimize` / `feature-ideation`
- [ ] Every step is executable (not empty talk like "build the brand")

### Delivery
- [ ] File saved to `data/growth_strategy_<slug>.md`
- [ ] **Full markdown pasted back into the conversation** (not just "saved" or a summary)
- [ ] Closing has the "Which one first" + "Want one expanded" guidance section (translated to the user's conversation language)
