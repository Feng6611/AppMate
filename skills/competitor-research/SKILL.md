---
name: competitor-research
description: Identify the top 5-10 rivals outranking a single app on its own core keywords. Use when the user asks for competitor research, "找竞品" / "找对手" / "跑竞争对手分析", or invokes this competitor-research skill.
---

# Competitor Research Workflow

> Single authoritative reference. Re-read before every run. Pure-SERP approach: zero RAG, zero AppMate semantic search. The script holds all the data-layer logic; Claude does keyword tokenization and a single batched LLM relevance pass.

## Step 0 — Prerequisites

Run before anything else:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and direct them to the `appmate-setup` skill. Do not invoke any other step of this skill.

## One-line summary

Single app → script writes phase_a (raw metadata + primary_genre_id) → **LLM tokenizes keywords** → script fetches iTunes Search top-200 per token, collects rivals outranking self, aggregates, scores, hard-filters by genre+density, writes phase_b → **LLM does batched relevance pass on name + description[:200]** → script writes final JSON, Claude renders the markdown in the user's conversation language, pastes back into conversation.

## Difference from existing skills

| | `competitor-research` (this skill) | `feature-ideation` / `growth-strategy` |
|---|---|---|
| Role | produces the competitive signal | consumes it |
| Signal | iTunes Search SERP overlap, strict outrank | reuses this skill's `data/competitors_<slug>.json` (auto-chains this skill when the file is missing) |
| Output role | the deliverable itself | transient input evidence in their phase_a JSONs |
| Persistence | `data/competitors_<slug>.json` (cached, reused) | not cached |

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | user says "find competitors for `<app>`" / "跑 `<app>` 的竞品" / invokes this skill for `<app>` |
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
- Cut real ASO words using semantic understanding of the source-locale text (Chinese, Japanese, Korean, etc.).
- Recognize compound words (`桌面便签`, `云便签`).
- Reject CJK runs ≥ 6 characters (almost always invalid mashed runs).
- Recognize brand variants, typos, and English-Chinese fusions.
- De-duplicate case-insensitively.

Output a comma-separated token list and pass it to the script:

```bash
python3 scripts/competitor_research.py rank    "Sticky Note Pro" --tokens "便签,桌面便签,sticky note,memo"
```

This writes `data/phase_b_competitors_<slug>.json` with up to 25 candidates that survived the genre + density hard filters.

### Stage 3 — Claude: batched relevance filter + render

Read `data/phase_b_competitors_<slug>.json`. For each candidate, look at `name`, `description_short`, and `outranked_keywords[:3]`.

**One batched judgement call.** For ALL candidates in one pass, decide for each:

- `keep: true` + a one-sentence reason (in the user's conversation language) explaining why the rival's target users overlap with the app's
- `keep: false` + a one-sentence reason (in the user's conversation language) explaining why they do not

Example reasons (when the user is writing Chinese):
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

**Rendered in Chinese by default for this fork.** If the user explicitly asks for another language, translate the template headers, labels and prose accordingly. App Store metadata strings (title / subtitle / keywords / competitor app names) must remain in the App Store's source locale (e.g. zh-Hans names stay zh-Hans) — only the surrounding explanation is translated.

The template below is Chinese-first. Keep app names, keywords and market codes in their source form.

```markdown
# 🎯 <App name> · 值得研究的核心竞品

> ⚠️ <evidence-thin warning — only when kept < 3>

**主市场**: <flag> <country>  ·  **近 30 天下载**: <N>  ·  **已搜索核心关键词**: <X>

---

## 1. <Rival name> · ★<rating>（<review_count> 条评论）

在 **<outrank_count> 个关键词**上排在你前面，平均领先 **<round avg_rank_diff> 个名次**

| 关键词 | 你 | 对方 | 领先 | 热度 |
|---|:-:|:-:|:-:|:-:|
| `<kw1>` | <#N or unranked> | **#<n>** | <diff> | <pop> <🔥 if ≥50> |
| `<kw2>` | ... | ... | ... | ... |
| `<kw3>` | ... | ... | ... | ... |

> **为什么看它**: <relevance_reason — one sentence in Chinese by default>

---

## 2. <Rival name> · ...
... (5–10 rivals total, top 3 keywords each) ...

---

**Top <N>**: #X / #Y / #Z — <用一句话概括每个核心竞品的威胁点>

想深入看某个竞品的关键词布局，可以告诉我编号，我会用 `aso-optimize` workflow 拉它的元数据做横向对比。
```

### Empty-state template (when `len(filtered) == 0`)

When the LLM relevance pass keeps zero candidates, do NOT render the per-rival `##` blocks. Instead, render exactly this:

```markdown
# 🎯 <App name> · 值得研究的核心竞品

> ⚠️ 暂无合格竞品 · 在自身关键词 SERP 中，没有满足 `MIN_OUTRANK_COUNT = 3` 门槛的同类竞品。

**主市场**: <flag> <country>  ·  **近 30 天下载**: <N>  ·  **已搜索核心关键词**: <X>

可能原因（按概率排序）:

1. **关键词太少**: 至少需要 3 个有效 token，竞品才可能通过密度门槛。检查 `phase_a_competitors_<slug>.json` 里的 `raw.keywords` 是否为空或只有 1-2 个词。
2. **该 App 已经是细分赛道领先者**: 没有竞品能在你的自身 SERP 中累计领先 ≥ 3 次。
3. **类目不匹配**: 你的 `primary_genre_id` 与候选竞品不一致，细分关键词跨类目混排时很常见。

要继续深挖，运行 `python3 scripts/competitor_research.py show-b "<app>"` 查看 phase_b 候选池（过滤前明细）。
```

## 10 inviolable rules

1. Each rival is its own `H2 (##)` block — low-density layout.
2. Keywords wrapped in backticks `` `桌面便签` ``.
3. Column headers are full words in the user's conversation language. **Never** use single-letter abbreviations `T/S/K/X`.
4. The "Why this one" line uses a `>` blockquote (translate the label to the user's conversation language).
5. The keywords table shows **exactly top 3** outranked keywords per rival — full list is in JSON.
6. **`dropped_by_relevance` never appears in markdown.** JSON only.
7. Sort rivals by `threat_score` descending.
8. Closing "Top N" + "deeper look at one rival" guidance is required (translated to the user's conversation language).
9. **Paste the full markdown back into the conversation.** "Saved to data/competitors_<slug>.md" alone is not allowed.
10. **Empty-state**: when `len(filtered) == 0`, render the Empty-state template above (no `##` rival blocks); never invent placeholder rivals.

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
- Use the resulting "Top N" rivals to seed a follow-up `aso-optimize` skill run for `<app>` for keyword reshuffling.
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
- [ ] Single-language throughout the rendered output (matches the user's conversation language)
- [ ] **No** single-letter abbreviations `T/S/K/X`
- [ ] No technical jargon (no "SERP" / "RAG" / "outrank" in user-visible text)
- [ ] Keywords wrapped in backticks

### Structure
- [ ] Each rival uses `## N. <name>`
- [ ] The "Why this one" label uses `>` blockquote
- [ ] `dropped_by_relevance` NOT rendered
- [ ] Closing "Top N" + "deeper look at one rival" line present

### Delivery
- [ ] `data/competitors_<slug>.json` written
- [ ] `data/competitors_<slug>.md` written
- [ ] **Full markdown pasted back into the conversation** (not just "saved")
