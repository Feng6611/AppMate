---
name: feature-ideation
description: Generate prioritized feature recommendations for an app from reviews + competitor evidence. Use when the user wants feature ideas, product roadmap input, or "跑功能策划" for a specific app.
---

# Feature Ideation Workflow v2

> This skill is the single authoritative reference for the feature ideation flow. Re-read it before every run.
> v2: removed the ASO traffic-blindspot source (high cost, poor results) + simplified the output format (two sentences per item, no scores).

## One-line summary

Given a live app → the script aggregates two evidence sources (**reviews + competitors**) → the LLM scores and internally ranks on 4 dimensions → a markdown report with two sentences per feature (what it is + why), with no scores shown.

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | the user says "run feature ideation for `<app>`" |
| **Input** | `data/apps_full.json` (reviews) + AppMate RAG (competitors) |
| **Output** | `data/phase_a_feature_<slug>.json` (intermediate) + `data/feature_ideas_<slug>.md` (final) + **Claude pastes the full markdown back into the conversation** |
| **Intervention points** | 2 (trigger + receive); optional follow-up "detail one of the ideas" |

## Workflow overview (3 steps)

1. **Step 1 · Script pre-aggregation (`feature_ideate.py`)** — app fuzzy match (reuses `aso_optimize_v2`) → review bucketing (negative feedback + wishlist) → AppMate RAG pulls the top 10 similar competitors → `data/phase_a_feature_<slug>.json`.
2. **Step 2 · LLM idea generation (Claude, conversation layer)** — brainstorm 15-20 candidates (5× principle); score each on 4 dimensions (for internal ranking, not shown); anti-junk filter (4 hard rules); sort by composite score descending, take the top 5-10.
3. **Step 3 · Render + deliver (Claude)** — two sentences per item (what it is + why); arrange by composite score descending but **do not show scores**; save `data/feature_ideas_<slug>.md`; **paste the full markdown back into the conversation**.

---

# Step 1 · Script pre-aggregation (decision rules)

## 1a. App anchoring

Reuses `aso_optimize_v2.find_app()` — accepts App Store ID / bundle ID / SKU / fuzzy name match.

**Main-market selection:**
1. Preferred: the country with the largest 30-day downloads (read `data/sales_cache.json`).
2. Fallback: the country corresponding to the app's `primaryLocale`.
3. Extreme fallback: US (so the script does not crash).

## 1b. Review bucketing

| Bucket | Filter condition | Cap |
|---|---|---|
| **Negative feedback** | `rating ≤ 3` AND `len(body) ≥ 10` | most recent 90 days, first 50 |
| **Wishlist** | `rating ≥ 4` AND contains a trigger word (`希望/能否/建议/wish/would love/please add/求/请加/不能/为什么没有`) | most recent 90 days, first 50 |
| **Cross-language** | reviews in the main-market locale first; other languages added by time | — |

Each review records: `{rating, title, body, locale, created_at}` (`body` is Apple's original review-body field name).

## 1c. Competitor fetch (AppMate RAG)

- **Query (seed)**: extract the longest meaningful real word from the app's main title / enabled locale names as the seed.
  - Example: "Sticky Note Pro: Post-it&Memo" → `Sticky`
  - Example (zh-Hans locale): "便签Pro:备忘录Memo便利贴" → `Memo`
  - Extreme fallback: the literal string `"app"`
- **Call**: `appmate_rag_client.search(query=seed, region=main_market, top_k=10, min_review_count=50, sort_by="S")`
- **Extract**: per competitor `{name, rating, review_count, description, appmate_reason}`
- ⚠️ `appmate_*` internal scores are for evidence ranking only — not shown to the end user.

> **v1 → v2 change**: v1 once tried to use `astro_popularity_cache.json` to find "high-pop traffic blindspots" as a third evidence source — measured as poor: the cache was polluted by other apps' queries (cross-category high-pop words like `微信 / 浏览器 / qq` appeared in the blindspot list of a note app); new-scenario apps had an empty cache; actively querying Astro MCP is costly and unstable. This step was removed. If re-added in the future, the script must actively call Astro `lookup_popularity_batch` to pull category-relevant words, rather than passively reading the cache.

## 1d. phase_a JSON shape

```json
{
  "app": "<name>",
  "app_id": "<id>",
  "bundle_id": "<bid>",
  "market": "<country>",
  "downloads_30d_in_market": 1300,
  "generated_at": "2026-05-13T...",
  "competitor_seed": "Memo",
  "reviews_negative": [{"rating":2, "title":"", "body":"...", "locale":"CHN", "created_at":"2026-05-05T..."}, ...],
  "reviews_wishlist": [{"rating":5, "title":"", "body":"希望加...", "locale":"CHN", "created_at":"..."}, ...],
  "competitors": [{"name":"...", "rating":4.7, "review_count":1234, "description":"...", "appmate_reason":"..."}, ...]
}
```

---

# Step 2 · LLM idea generation (decision rules)

## 2a. The 5× principle

The LLM first internally brainstorms **15-20 candidates**, pulling 15-20 from the two evidence sources (reviews + competitors), then cross-dedups → trims to 5-10 finalists by composite score. Rationale: experience says the candidate count should be 5× the finalist count for comparative filtering to be meaningful.

## 2b. The 4-dimension scoring formula (**internal rule — never shown to the user**)

> The following is the LLM's internal ranking methodology (based on RICE). **The final markdown output does not show scores** — items are only arranged from high to low score; the user sees only a sorted feature list.

Each candidate is scored 1-5 on 4 dimensions:

| Internal dimension | 1-5 scoring basis |
|---|---|
| **Reach** | reviews mention ≥ 10 → 5; validated by multiple competitors → 4; single evidence → 2 |
| **Impact** | solves a payment blocker / prevents uninstall → 5; improves retention → 4; experience detail → 2 |
| **Confidence** | reviews ≥ 3 + competitor validation → 5; single source only → 2; pure speculation → 1 |
| **Effort** | macOS solo dev: half a day → 1; 2+ weeks → 5 |

**Composite score = (R × I × C) / E** (range 0.2 - 125, **for LLM internal ranking only**).

## 2c. Anti-junk — 4 hard rules

| Rule | Application |
|---|---|
| ❌ Single evidence | Confidence ≤ 2 AND Reach ≤ 2 → cut directly |
| ❌ Platform violation | a mac app proposing "add GPS / push / an iOS-only sensor" → delete |
| ❌ Vague words | "improve performance / nicer / smarter" → must be specific to a behavior |
| ❌ Rename-style non-action | "rename a button" must state "which interaction changed" |

## 2d. Sort and trim

- Sort by composite score, high to low.
- Take the top **5-10** as finalists.
- **No "backup pool" section anymore** (v2 simplification).
- Main list < 5 → add a ⚠️ "insufficient evidence, suggest adding more reviews or expanding the competitor pool" warning at the top.

---

# Step 3 · Render + deliver

## 3.1 Output template (**what the user finally sees**)

> **Core rules**:
> 1. **Do not show any scores** (composite score, 4-dimension scores all hidden) — scores are only the LLM's internal ranking basis.
> 2. **No jargon**: `RICE / R / I / C / E / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight`.
> 3. **Two sentences per item only**: the first says "what it is / how it interacts", the second says "why do it / what the evidence is".
> 4. Arrange by composite score high to low (but do not show the score).

The output template and rendered example are in **Chinese** by design — do not translate the rendered deliverable.

```markdown
# 🚀 <App 名> · 功能推荐

> ⚠️ <证据偏薄警告 — 仅当负反馈+愿望<5 条时显示。例：「证据偏薄：仅 2 条负反馈 + 0 条愿望清单 + 10 个竞品。仅供方向参考。」>

**1. <功能标题>** — <一句话：这个功能是什么、怎么交互>。<一句话：为什么要做、证据是什么>。

**2. <功能标题>** — <同上结构>。

...（共 5-10 条）...

**N. <功能标题>** — <同上结构>。

---

**重点 N 个**：#X / #Y / #Z — 简述各自的核心价值（一句话总结分别对应什么）。

要详细化哪个？告诉我编号，我可以帮你写 mini PRD（用户故事 / 验收标准 / 拆分 sprint）。
```

## 3.2 6 layout rules

1. **No jargon**: the user-visible content must not contain `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight` — always use plain Chinese.
2. **No score numbers**: do not show the composite score or any of the 4-dimension scores.
3. **Two sentences per item**: first "what it is", second "why". The two sentences are separated by a full-width period `。`.
4. **Bold feature title**: `**N. 标题**` followed by `— ` (full-width em dash).
5. **Top evidence warning**: when negative feedback + wishlist < 5 items, the warning must show.
6. **Closing "重点 N 个" + "详细化哪个"**: guide the user to follow up.

---

## File structure

| File | Purpose |
|---|---|
| `scripts/feature_ideate.py` | Step 1 script (no user intervention, runs by app name) |
| `data/phase_a_feature_<slug>.json` | intermediate artifact (overwritten each run) |
| `data/feature_ideas_<slug>.md` | final deliverable (overwritten each run) |

## Connection to existing workflows

| Direction | Content |
|---|---|
| **Upstream dependency** | `data/apps_full.json` / `scripts/appmate_rag_client.py` |
| **Side-chain trigger** | the `aso-daily-report` skill finds an app's rank dropping out → trigger this flow to find new features as a fix |
| **Downstream upgrade (v3)** | add a `feature_detail_<slug>.py` to expand a single idea into a PRD |

## CLI

```bash
# from the plugin repo root

# Step 1: run the script (produces the phase_a JSON)
python3 scripts/feature_ideate.py "<app>"

# the app argument accepts: App Store ID / bundle ID / SKU / fuzzy name match
# examples:
#   python3 scripts/feature_ideate.py "Sticky Note Pro"
#   python3 scripts/feature_ideate.py "com.fengyiqi.PostItnoteForMac"
#   python3 scripts/feature_ideate.py "1482080766"

# Steps 2-3: Claude reads the phase_a JSON and generates + renders per §2 / §3 rules
```

## Known limits

- Reviews mix languages; LLM translation may be off (taking the most recent 90 days lowers the risk).
- AppMate RAG is a public BETA — competitors may not always be accurate.
- The composite score is fairly subjective; running the same app multiple times varies ±20% (suggest taking the union).
- Apps with ≤ 5 reviews struggle to produce reliable ideas (the first run warns "insufficient evidence").
- v2 removed the ASO traffic-blindspot source → lost the "what users search but the app does not cover" angle, relying only on reviews + competitors.

## Checklist (must pass before executing Step 3)

### Content
- [ ] Main list of 5-10 features
- [ ] Exactly 2 sentences per feature (what it is + why), not long paragraphs
- [ ] Arranged by composite score high to low (correct order, no scores shown)
- [ ] When evidence is thin, a ⚠️ warning at the top

### User-language review (**strictest**)
- [ ] **No** score numbers (composite score N, R/I/C/E individual scores all absent)
- [ ] **No** English jargon `RICE / Reach / Impact / Confidence / Effort / Explore / Exploit / Core value / Onboarding / Delight`
- [ ] **No** single-letter abbreviations `R / I / C / E`
- [ ] Each feature title uses `**N. 名称**` bold + full-width em dash `—`

### Anti-junk
- [ ] No "single evidence + low confidence" features
- [ ] No platform violations like a mac app proposing GPS
- [ ] No vague words like "improve performance"
- [ ] Rename / change-icon type non-actions must be specific to a behavior

### Delivery
- [ ] File saved to `data/feature_ideas_<slug>.md`
- [ ] **Full markdown pasted back into the conversation** (not just "saved")
- [ ] Closing has the "重点 N 个" + "详细化哪个" guidance section
