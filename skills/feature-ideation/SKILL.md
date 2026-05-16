---
name: feature-ideation
description: Generate prioritized feature recommendations for an app from reviews + competitor evidence. Use when the user wants feature ideas, product roadmap input, or "跑功能策划" for a specific app.
---

# Feature Ideation Workflow v3

> This skill is the single authoritative reference for the feature ideation flow. Re-read it before every run.
> v3: removed mechanical review bucketing (rating thresholds + trigger-word list) and removed the direct AppMate RAG dependency. The LLM now classifies each raw review on its own; competitors come from the `/appmate-competitors` output. v2 had been the prior "negative + wishlist buckets + RAG seed" design.

## Step 0 — Prerequisites

### 0.1 Credentials gate

Every step in this skill calls App Store Connect APIs. **Before any other step**, run:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Do not invoke any other part of this skill, do not run `scripts/feature_ideate.py`. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup`. The downstream script also enforces this gate (exits 2 with the same message).

### 0.2 Competitor data: auto-chain `/appmate-competitors` if missing

This workflow consumes `data/competitors_<slug>.json`, the final artifact produced by the `competitor-research` skill (i.e. `/appmate-competitors <app>`). Both skills compute slug via `slugify(canonical_app_name, market)`, so passing the same app argument to both guarantees the slug matches.

**Decision rule — before invoking `feature_ideate.py`:**

1. Resolve the canonical app + market for `<app>` (read `data/apps_full.json`, call `find_app(<arg>)` → name, then pick main market via the largest 30-day downloads in `sales_cache.json` with the same fallbacks the script uses — primaryLocale, then US). Compute `expected = data/competitors_<slugify(name, market)>.json`.
2. Check whether `expected` exists.
3. **If it does not exist**, invoke the `competitor-research` skill end-to-end for the same `<app>` argument first — all three stages: Stage 1 script `analyze`, Stage 2 LLM tokenization, Stage 3 LLM relevance pass + final-JSON + markdown write. Paste the rivals markdown back into the conversation per that skill's own rules. Then return here and proceed to Step 1 of feature-ideation. The user gets two reports out of one ask: rivals first, then features. That is intentional — both are useful, and the rivals card is also the new evidence basis for feature ideas.
4. **If it exists**, proceed directly. Optionally check `competitors_generated_at`; if it is > 30 days old, mention staleness when delivering the final feature report (do **not** auto-refresh unless the user asks).

**No RAG fallback. No placeholder competitors.** The only two paths are: the cached file, or a fresh `/appmate-competitors` run. The earlier (v2) direct `appmate_rag_client.search(...)` call is gone for good — competitor evidence is unified through the `competitor-research` flow so the two workflows stay coherent.

**Safety net**: `feature_ideate.py` still exits 2 with `competitors JSON not found` if the file is missing at script-execution time. This catches the case where the script was invoked outside the skill (cron, manual CLI). When it fires, treat it the same way — invoke `competitor-research` for the same app, then re-run.

## One-line summary

Given a live app → the script aggregates raw reviews (last 90 days, ≤ 150) plus the kept competitors from `competitors_<slug>.json` → the LLM reads each review and classifies it itself (complaint / suggestion / praise), then scores ideas internally on 4 dimensions → a markdown report with two sentences per feature (what it is + why), with no scores shown.

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | the user says "run feature ideation for `<app>`" |
| **Input** | `data/apps_full.json` (reviews) + **`data/competitors_<slug>.json`** (from `/appmate-competitors` — auto-chained on first run for an app, then cached) |
| **Output** | `data/phase_a_feature_<slug>.json` (intermediate) + `data/feature_ideas_<slug>.md` (final) + **Claude pastes the full markdown back into the conversation** |
| **Intervention points** | 2 (trigger + receive); optional follow-up "detail one of the ideas" |

## Workflow overview (3 steps)

1. **Step 1 · Script pre-aggregation (`feature_ideate.py`)** — app fuzzy match (reuses `aso_optimize_v2`) → pull raw reviews from last 90 days (≤ 150, no filter) → load competitors from `data/competitors_<slug>.json` (Claude should have already auto-chained `/appmate-competitors` per §0.2 if the file was missing; script exits 2 as a safety net otherwise) → `data/phase_a_feature_<slug>.json`.
2. **Step 2 · LLM idea generation (Claude, conversation layer)** — read each raw review, decide whether it is a complaint, a suggestion, a praise, or noise; brainstorm 15-20 candidates (5× principle); score each on 4 dimensions (internal only); anti-junk filter (4 hard rules); sort by composite score descending, take the top 5-10.
3. **Step 3 · Render + deliver (Claude)** — two sentences per item (what it is + why); arrange by composite score descending but **do not show scores**; save `data/feature_ideas_<slug>.md`; **paste the full markdown back into the conversation**.

---

# Step 1 · Script pre-aggregation (decision rules)

## 1a. App anchoring

Reuses `aso_optimize_v2.find_app()` — accepts App Store ID / bundle ID / SKU / fuzzy name match.

**Main-market selection:**
1. Preferred: the country with the largest 30-day downloads (read `data/sales_cache.json`).
2. Fallback: the country corresponding to the app's `primaryLocale`.
3. Extreme fallback: US (so the script does not crash).

## 1b. Raw reviews collector

`collect_raw_reviews()` does the bare minimum — no rating threshold, no trigger-word list, no semantic split. The LLM in Step 2 reads each body and decides what it is.

| Rule | Value |
|---|---|
| Age cutoff | last 90 days (`createdDate` ≥ today − 90) |
| Cap | first **150** entries after newest-first sort |
| Per-entry schema | `{rating, title, body, locale, created_at}` (`body` is Apple's original field name) |
| Cross-language | no language filter — reviews in all locales pass through; the LLM handles translation |

> **v2 → v3 change**: v2 had two pre-computed buckets — `reviews_negative` (`rating ≤ 3` + body ≥ 10 chars) and `reviews_wishlist` (`rating ≥ 4` + a trigger word from a hardcoded list). Both were leaky: rating ∈ {4, 5} entries often carried strong suggestions, low-rating entries were sometimes just venting with nothing actionable, and the trigger-word list missed many real signals. v3 sends raw reviews and lets the LLM do the semantic call.

## 1c. Competitor loader (no RAG)

`load_competitors(app_name, market)` reads `OUTPUT_DIR / f"competitors_{slugify(app_name, market)}.json"`. The file is the final artifact of `/appmate-competitors` (see `skills/competitor-research/SKILL.md`). Per §0.2, Claude should ensure this file exists *before* invoking the script — by auto-chaining `/appmate-competitors` when it's missing.

| Step | Behavior |
|---|---|
| File missing | return `None` → `build_phase_a` returns `None` → `main()` prints a safety-net message pointing at `/appmate-competitors` and exits 2. Normally never fires when the skill flow was followed; fires if the script was invoked directly. |
| File present | read `payload["filtered"]` (already top-10 by `threat_score`, already passed the LLM relevance pass) and copy these fields per entry: `name`, `description_short`, `outranked_keywords`, `relevance_reason`, `threat_score`, `rating`, `review_count` |
| Stale data | the script does **not** check `generated_at` freshness; it surfaces the timestamp in phase_a so the LLM can flag staleness in the report if it looks old (> 30 days) |

> **v2 → v3 change**: v2 called `appmate_rag_client.search(query=seed, region=market, top_k=10, ...)` directly with a seed-word it picked from the app's name. The seed-extraction was fragile (compound brand names like `便签Pro` lost their context, English-only `app` fallback returned useless rivals), and the RAG result was a different shape than the SERP-overlap rivals produced by `/appmate-competitors`. v3 reuses the already-curated, already-LLM-filtered result of `/appmate-competitors`, so the two workflows produce a coherent picture of the same competitive landscape.

## 1d. phase_a JSON shape

```json
{
  "app": "<name>",
  "app_id": "<id>",
  "bundle_id": "<bid>",
  "market": "<country>",
  "downloads_30d_in_market": 1300,
  "generated_at": "2026-05-13T...",
  "reviews": [
    {"rating": 2, "title": "", "body": "...", "locale": "CHN", "created_at": "2026-05-05T..."},
    {"rating": 5, "title": "", "body": "希望加...", "locale": "CHN", "created_at": "..."}
  ],
  "competitors_source": "<absolute path to competitors_<slug>.json>",
  "competitors_generated_at": "<timestamp from competitors_<slug>.json>",
  "competitors": [
    {"name": "...", "description_short": "...", "outranked_keywords": ["..."],
     "relevance_reason": "...", "threat_score": 42, "rating": 4.7, "review_count": 1234}
  ]
}
```

---

# Step 2 · LLM idea generation (decision rules)

## 2a. Read + classify reviews first (new in v3)

Before brainstorming, walk the `reviews[]` array once. For each entry decide which bin it falls into — **no fixed rating rules**, use the body content:

| Bin | Looks like |
|---|---|
| **Complaint** | crash report, sync loss, billing dispute, broken core flow, uninstall warning |
| **Suggestion** | "希望加 X / would love Y / 能否 / please add / 不能 X / 为什么没有 Y / I wish" — explicit feature ask |
| **Praise + hidden signal** | rating ≥ 4 but the body mentions a workflow they wish was smoother, or a competitor they prefer for one feature |
| **Noise** | spammy / "good" / non-actionable rating-only entry — ignore |

You may **discount or skip noise**; this is not a "first 50" cap. A rating ∈ {4, 5} body that contains a strong suggestion still goes into the suggestion bin — do not anchor on the star count.

## 2b. The 5× principle

Brainstorm **15-20 candidates** internally, pulling 15-20 from the two evidence sources (your bins from §2a + competitors), then cross-dedup → trim to 5-10 finalists by composite score. Rationale: experience says the candidate count should be 5× the finalist count for comparative filtering to be meaningful.

## 2c. The 4-dimension scoring formula (**internal rule — never shown to the user**)

> The following is the LLM's internal ranking methodology (based on RICE). **The final markdown output does not show scores** — items are only arranged from high to low score; the user sees only a sorted feature list.

Each candidate is scored 1-5 on 4 dimensions:

| Internal dimension | 1-5 scoring basis |
|---|---|
| **Reach** | reviews mention ≥ 10 → 5; validated by multiple competitors → 4; single evidence → 2 |
| **Impact** | solves a payment blocker / prevents uninstall → 5; improves retention → 4; experience detail → 2 |
| **Confidence** | reviews ≥ 3 + competitor validation → 5; single source only → 2; pure speculation → 1 |
| **Effort** | macOS solo dev: half a day → 1; 2+ weeks → 5 |

**Composite score = (R × I × C) / E** (range 0.2 - 125, **for LLM internal ranking only**).

## 2d. Anti-junk — 4 hard rules

| Rule | Application |
|---|---|
| ❌ Single evidence | Confidence ≤ 2 AND Reach ≤ 2 → cut directly |
| ❌ Platform violation | a mac app proposing "add GPS / push / an iOS-only sensor" → delete |
| ❌ Vague words | "improve performance / nicer / smarter" → must be specific to a behavior |
| ❌ Rename-style non-action | "rename a button" must state "which interaction changed" |

## 2e. Sort and trim

- Sort by composite score, high to low.
- Take the top **5-10** as finalists.
- Main list < 5 → add a ⚠️ "insufficient evidence, suggest adding more reviews or expanding the competitor pool with `/appmate-competitors`" warning at the top.

---

# Step 3 · Render + deliver

## 3.1 Output template (**what the user finally sees**)

> **Core rules**:
> 1. **Do not show any scores** (composite score, 4-dimension scores all hidden) — scores are only the LLM's internal ranking basis.
> 2. **No jargon**: `RICE / R / I / C / E / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight`.
> 3. **Two sentences per item only**: the first says "what it is / how it interacts", the second says "why do it / what the evidence is".
> 4. Arrange by composite score high to low (but do not show the score).

**Rendered in the same language the user has been using in this conversation.** Default to English; if the user has been writing in Chinese / Japanese / Spanish / etc., translate the template headers, labels and prose accordingly. App Store metadata strings (title / subtitle / keywords / competitor app names) must remain in the App Store's source locale (e.g. zh-Hans names stay zh-Hans) — only the surrounding explanation follows the user's conversation language.

The template below is written with English placeholders. Substitute the equivalent words in the user's conversation language when rendering.

```markdown
# 🚀 <App name> · Feature recommendations

> ⚠️ <evidence-thin warning — only shown when total reviews < 10 OR total competitors == 0. Example: "Evidence thin: only 7 reviews + 0 competitors. Recommend running /appmate-competitors first to add competitor evidence, then revisit this report.">

**1. <Feature title>** — <one sentence: what the feature is, how it interacts>. <one sentence: why do it, what's the evidence>.

**2. <Feature title>** — <same structure>.

... (5-10 items total) ...

**N. <Feature title>** — <same structure>.

---

**Top N**: #X / #Y / #Z — short summary of each item's core value (one sentence each).

Want one expanded? Tell me the number and I can help you write a mini PRD (user stories / acceptance criteria / sprint breakdown).
```

## 3.2 6 layout rules

1. **No jargon**: the user-visible content must not contain `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight` — always use plain prose in the user's conversation language.
2. **No score numbers**: do not show the composite score or any of the 4-dimension scores.
3. **Two sentences per item**: first "what it is", second "why". The two sentences are separated by a period (use the punctuation natural to the user's conversation language — e.g. full-width `。` for Chinese, `.` for English).
4. **Bold feature title**: `**N. Title**` followed by `— ` (em dash, full-width when the surrounding text is CJK).
5. **Top evidence warning**: when reviews total < 10 or competitors total == 0, the warning must show.
6. **Closing "Top N" + "Want one expanded"**: guide the user to follow up (translated to the user's conversation language).

---

## File structure

| File | Purpose |
|---|---|
| `scripts/feature_ideate.py` | Step 1 script (runs by app name; hard-depends on `data/competitors_<slug>.json`) |
| `data/phase_a_feature_<slug>.json` | intermediate artifact (overwritten each run) |
| `data/feature_ideas_<slug>.md` | final deliverable (overwritten each run) |

## Connection to existing workflows

| Direction | Content |
|---|---|
| **Upstream auto-chain** | `data/apps_full.json` + **`data/competitors_<slug>.json`**. When the competitors file is missing, this skill first invokes `/appmate-competitors <app>` end-to-end (rivals markdown gets pasted back as a side effect), then continues. |
| **Side-chain trigger** | the `aso-daily-report` skill finds an app's rank dropping out → trigger this flow to find new features as a fix |
| **Downstream upgrade (v4)** | add a `feature_detail_<slug>.py` to expand a single idea into a PRD |

## CLI

```bash
# from the plugin repo root

# Step 0 prerequisite (one-time per app, also refresh whenever the SERP shifts):
python3 scripts/competitor_research.py analyze "<app>"
# ...then Claude tokenizes + the rank pass + Claude writes data/competitors_<slug>.json
# (handled by /appmate-competitors end-to-end)

# Step 1: aggregate reviews + competitors → phase_a JSON
python3 scripts/feature_ideate.py "<app>"

# the app argument accepts: App Store ID / bundle ID / SKU / fuzzy name match
# examples:
#   python3 scripts/feature_ideate.py "Sticky Note Pro"
#   python3 scripts/feature_ideate.py "com.fengyiqi.PostItnoteForMac"
#   python3 scripts/feature_ideate.py "1482080766"

# Steps 2-3: Claude reads the phase_a JSON and generates + renders per §2 / §3 rules
```

If `feature_ideate.py` exits 2 with `competitors JSON not found`, that is the safety net firing — invoke `/appmate-competitors "<app>"` end-to-end, then re-run this command. (In normal skill-driven runs you should not hit this, because §0.2 instructs Claude to auto-chain `/appmate-competitors` when the file is missing, before ever invoking the script.)

## Known limits

- Reviews mix languages; LLM classification may be off on idiomatic phrasing (taking the most recent 90 days lowers the risk).
- The competitor list reflects whenever `/appmate-competitors` was last run for this app — staleness shows up in `competitors_generated_at`; if it's > 30 days old, suggest re-running the prereq before trusting the report.
- The composite score is fairly subjective; running the same app multiple times varies ±20% (suggest taking the union).
- Apps with ≤ 5 reviews struggle to produce reliable ideas (the first run warns "insufficient evidence").
- v3 dropped the direct AppMate RAG call → no more "blind" same-keyword similar apps; the trade-off is a sharper, already-LLM-curated competitor set from the SERP-overlap path.

## Checklist (must pass before executing Step 3)

### Content
- [ ] Main list of 5-10 features
- [ ] Exactly 2 sentences per feature (what it is + why), not long paragraphs
- [ ] Arranged by composite score high to low (correct order, no scores shown)
- [ ] When evidence is thin (reviews < 10 OR competitors == 0), a ⚠️ warning at the top

### User-language review (**strictest**)
- [ ] **No** score numbers (composite score N, R/I/C/E individual scores all absent)
- [ ] **No** English jargon `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight`
- [ ] **No** single-letter abbreviations `R / I / C / E`
- [ ] Each feature title uses `**N. Name**` bold + em dash `—` (full-width when surrounding text is CJK)

### Anti-junk
- [ ] No "single evidence + low confidence" features
- [ ] No platform violations like a mac app proposing GPS
- [ ] No vague words like "improve performance"
- [ ] Rename / change-icon type non-actions must be specific to a behavior

### Delivery
- [ ] File saved to `data/feature_ideas_<slug>.md`
- [ ] **Full markdown pasted back into the conversation** (not just "saved")
- [ ] Closing has the "Top N" + "Want one expanded" guidance section (in the user's conversation language)
