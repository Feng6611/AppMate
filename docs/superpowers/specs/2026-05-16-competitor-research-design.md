# Competitor Research — Design Spec

**Date**: 2026-05-16
**Status**: Draft, awaiting user review
**Scope**: A new skill that, given a single live app, produces a ranked list of the most valuable competitors to study — defined as rivals who **outrank you** on your own core keywords.

---

## 1. Background

AppMate currently has six skills. Three of them touch "competitors":

| Skill | How it uses competitors |
|---|---|
| `feature-ideation` | Calls AppMate RAG with a single seed word, fetches top-10 semantically similar apps, uses them as **evidence** for feature ideas. |
| `growth-strategy` | Same pattern, fetches top-8 semantically similar apps as **strategy evidence**. |
| `aso-optimize` | Mentions "competitor inspiration" in the methodology but does not actually call any competitor source. |

In all three, "competitor" is a transient input — fetched fresh per run, used as supporting evidence, then discarded. No skill produces a **competitor list as its primary deliverable**, and no skill identifies the rivals who are actually taking traffic that should be yours.

The semantic-similarity definition that RAG provides ("apps that look like yours") is a weak proxy for what an indie developer actually needs: **"who is beating me on the keywords my own app targets."** Two apps can be semantically similar yet never compete in any user's search; conversely, two apps can be in different sub-niches yet land on the same search result page and steal each other's installs.

This skill answers the second question directly, using SERP overlap as the hard signal.

---

## 2. Goals and non-goals

### Goals

- Given a single app, identify **5–10 competitors who are outranking it on its own keywords**.
- Define "most valuable" by threat score: how often the rival outranks you, by how many positions, weighted by keyword popularity.
- Filter out same-keyword-but-unrelated apps using a category gate + a density threshold + an LLM topical-relevance pass.
- Produce both a human-readable Chinese markdown report and a machine-readable JSON contract that downstream skills can consume later.
- Reuse the existing iTunes Search client; add zero new data sources; add zero RAG calls.

### Non-goals

- Not changing `feature-ideation`, `growth-strategy`, or `aso-optimize` in this iteration. Downstream integration is a follow-up task.
- Not building continuous monitoring (no daily diff snapshots). Runs are on-demand.
- Not building a multi-app sweep (`top-3` mode). Single app per invocation.
- Not exposing AppMate RAG fields in the output. The deliverable is positioned as evidence-based hard data.

---

## 3. User flow

```
User: /appmate-competitors <app>
   ↓
[Python script]  credentials gate → app fuzzy match → main market →
                  raw metadata → write phase_a JSON
   ↓
[Claude in conversation layer]  read phase_a → semantic tokenize
                                 keywords → write back token list
   ↓
[Python script]  for each token: iTunes Search top-200 →
                  collect rivals outranking self → aggregate per rival →
                  hard filters (genre + density) → threat score →
                  write phase_b JSON (≤25 candidates)
   ↓
[Claude in conversation layer]  read phase_b → one batched LLM call to
                                 mark keep/drop with one-sentence reason
                                 per candidate → write final
                                 competitors_<slug>.json → render Chinese
                                 markdown → save .md file → paste full
                                 markdown back into the conversation
```

**User intervention points: 2** (trigger + LLM work). Both LLM steps (tokenize after Phase A, relevance filter after Phase B) happen inside the same Claude session — the user is not interrupted between them; the script runs are wrapped inside the same conversation turn. This mirrors `aso-daily-report`'s flow.

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────┐
│  Python: scripts/competitor_research.py              │
│  · subcommand: analyze <app>   → phase_a             │
│  · subcommand: rank <app>      → phase_b             │
│  · subcommand: show-a/show-b   → debug                │
│                                                       │
│  Reuses:                                              │
│  · aso_optimize_v2.find_app()         — fuzzy match  │
│  · aso_optimize_v2.slugify()                          │
│  · aso_report.rank_keyword()          — base ranker  │
│  · keyword_local.lookup_popularity()  — heat lookup  │
│  · appmate_config                     — creds gate   │
│                                                       │
│  Adds:                                                │
│  · rank_keyword_with_details()        — keeps SERP   │
│                                          metadata    │
│  · aggregate_rivals()                 — cross-token  │
│  · score_threat()                     — formula §6   │
│  · filter_by_genre_and_density()                      │
└──────────────────────────────────────────────────────┘
                       │
                       │  intermediate JSON
                       ▼
┌──────────────────────────────────────────────────────┐
│  Claude (conversation layer)                          │
│  · Step 2: tokenize keywords (same prompt style as    │
│            aso-daily-report Step 2)                   │
│  · Step 5: batched relevance filter (one LLM call,    │
│            max 25 candidates × ≤200 chars description)│
│  · Step 6: render Chinese markdown per template §8    │
│  · Step 7: paste full markdown back into conversation │
└──────────────────────────────────────────────────────┘
```

The Python/Claude split mirrors `feature-ideation` and `aso-daily-report`: scripts do deterministic data work, Claude does anything requiring semantic judgement.

---

## 5. Phase A — script: fetch app metadata

### Trigger
```bash
python3 scripts/competitor_research.py analyze "<app>"
```

### Inputs
- `<app>`: App Store ID / bundle ID / SKU / fuzzy name (resolved by `aso_optimize_v2.find_app`).
- `data/apps_full.json` and `data/sales_cache.json` (existing caches).

### Behavior
1. Run `appmate_config.check()`; if non-zero, exit 2 with the standard "credentials not configured, run `/appmate-setup`" message (consistent with all other skills).
2. Resolve the app.
3. Pick the main market: country with the largest 30-day downloads (read `sales_cache.json`); fall back to the app's `primaryLocale` country; final fallback US.
4. Extract raw `title`, `subtitle`, `keywords` for the picked locale from `apps_full.json`.
5. Fetch `primary_genre_id` via iTunes Lookup (`https://itunes.apple.com/lookup?id=<itunes_id>&country=<market>`). This is one additional HTTP call per `analyze` run — `apps_full.json` does not currently cache this field, and Phase B's genre filter depends on it. Cache the lookup result in `data/itunes_lookup_cache.json` (new file, keyed by `itunes_id`, no TTL — categories rarely change). If the lookup fails after the standard 4-retry policy, exit 2 with a clear "iTunes Lookup failed for primary_genre_id" message — the genre filter is mandatory, we do not silently skip it.
6. Write `data/phase_a_competitors_<slug>.json` (see §9).

### Exit codes
- `0`: success
- `2`: credentials gate failed or app not found

---

## 6. Phase B — script: rank lookup and aggregation

### Trigger
```bash
python3 scripts/competitor_research.py rank "<app>" --tokens "tok1,tok2,..."
```

The tokens come from the Claude tokenization step (§7).

### Behavior

#### 6.1 Per-token SERP fetch

For each token `k`, call `rank_keyword_with_details(k, country, entity)`, a new function adapted from `aso_report.rank_keyword`. The difference: the existing function discards everything except `bundleId → rank`; the new function keeps the full SERP entry per app:

```python
{
  "itunes_id": str,           # trackId
  "bundle_id": str,
  "name": str,                # trackName
  "description": str,         # full description, truncated later
  "primary_genre_id": int,
  "rating": float,            # averageUserRating
  "review_count": int,        # userRatingCount
  "rank_in_serp": int         # 1..200
}
```

The endpoint is the same Apple iTunes Search API already used. **Zero new HTTP calls.** Reuse the existing `rank_cache` mechanism so re-runs within the cache window do not re-hit Apple.

#### 6.2 Self-rank extraction

For each token, locate the current app's own entry by `bundleId`. If not found in the top-200, set `self_rank[k] = None` (treated as the ceiling `SELF_NORANK_CEILING = 200` in scoring).

#### 6.3 Cross-token aggregation

For each unique rival `itunes_id` appearing in any SERP:

```python
{
  "itunes_id": "...",
  "name": "...",
  "rating": ...,
  "review_count": ...,
  "primary_genre_id": ...,
  "description_short": description[:200],
  "outranked_keywords": [
    {
      "keyword": k,
      "self_rank": self_rank[k] or 200,
      "rival_rank": rival_rank_in_k,
      "diff": (self_rank[k] or 200) - rival_rank_in_k,
      "popularity": keyword_local.lookup_popularity(k, region)
    }
    for k in tokens
    if rival_rank_in_k is not None
       and rival_rank_in_k < (self_rank[k] or 200)
  ],
  "outrank_count": len(outranked_keywords),
  "avg_rank_diff": mean(o["diff"] for o in outranked_keywords),
  "threat_score": sum(o["popularity"] * o["diff"] for o in outranked_keywords)
}
```

Only keywords where the rival is **strictly higher ranked** than the app are counted.

Note: `self_ranks` at the top of `phase_b` stores `null` for "unranked" (compact raw signal). Inside per-rival `outranked_keywords`, `self_rank` stores `200` (the normalized value used by scoring). This split is intentional — the top-level dict preserves raw lookup data, the nested record is scoring-ready.

#### 6.4 Threat score formula

```
threat_score(C) = Σ_{k where rank_C(k) < rank_self(k)}  popularity(k) × (rank_self(k) − rank_C(k))

where:
  rank_self(k) ∈ [1, 200]; None → 200
  rank_C(k)    ∈ [1, 200]
  popularity(k) ∈ [1, 99]; if keyword_local lookup fails → 1
```

Rationale:
- **Position differential** rewards rivals who beat you by larger margins.
- **Popularity weight** ensures dominating a hot keyword by one position outscores dominating a cold keyword by ten positions.
- **Count** is implicit in the sum across tokens.

Worked example: rival sits at `#3` on `便签 widget` (popularity 76), app is unranked. Contribution = `76 × (200 − 3) = 14,972`.

#### 6.5 Hard filters

Applied in order, before LLM relevance:

1. **Same primary genre**: `rival.primary_genre_id == app.primary_genre_id`. Removes cross-category noise (a productivity app surfacing in a games SERP, etc.).
2. **Outrank density**: `outrank_count >= MIN_OUTRANK_COUNT (= 3)`. Removes single-point flukes (a rival appearing higher on exactly one common word).

After filters, sort by `threat_score` descending, truncate to `MAX_CANDIDATES_BEFORE_LLM (= 25)`.

#### 6.6 Output

Write `data/phase_b_competitors_<slug>.json` (see §9).

---

## 7. Step C — Claude in conversation: tokenize + relevance filter

Claude does two LLM-side jobs in the same conversation turn:

### 7.1 Tokenization

Read `phase_a` → segment title + subtitle + keywords into meaningful ASO tokens. Same rules as `aso-daily-report` Step 2:

- Recognize compound words (`桌面便签`, `云便签`).
- Reject CJK runs ≥ 6 characters (almost always invalid concatenations).
- Recognize brand variants and typos.
- Output a JSON-encodable list of strings.

Then write the token list back to the script (the script's `rank` subcommand accepts `--tokens "..."`).

### 7.2 Relevance filter (batched, single LLM call)

Read `phase_b` → look at each candidate's `{name, description_short, outranked_keywords[:3]}` → output a decision per candidate:

- `keep: true`  + a one-sentence Chinese reason explaining why the rival's target users overlap with the app's
- `keep: false` + a one-sentence Chinese reason explaining why they do not

Examples:

| Verdict | Example reason |
|---|---|
| keep | 「XX便签」描述同样主打桌面快速记事,目标用户重叠 |
| drop | 描述显示是情绪打卡 app,跟便签场景不重叠 |

Constraint: **a single batched LLM call for all candidates** (not per-candidate), so the latency budget is one inference, not 25.

### 7.3 Finalization

- Keep candidates where `keep == true`, sort by `threat_score` descending, take top 5–10.
- Write `data/competitors_<slug>.json` with two arrays:
  - `filtered`: the kept candidates (full structure, in threat order)
  - `dropped_by_relevance`: the dropped candidates with minimal fields + drop reason (diagnostic only, **not surfaced in markdown**)
- Render the Chinese markdown per §8, write to `data/competitors_<slug>.md`.
- **Paste the full markdown back into the conversation** (per user memory: 日报对话直贴).

---

## 8. Markdown report template

The rendered report is in **Chinese** by design — do not translate the rendered output. The source code, comments, and this spec are in English.

```markdown
# 🎯 <App 名> · 最值得研究的竞品

> ⚠️ <evidence-thin warning — only when kept < 3 candidates,
>     e.g. "证据偏薄:仅 2 个对手通过相关性过滤。仅供方向参考。">

**主市场**: <flag> <country>  ·  **30 天下载**: <N>  ·  **检索核心词**: <X> 个

---

## 1. <对手名> · ★<rating> (<review_count> 评)

在你 **<outrank_count> 个词**上排名高过你,平均高 **<avg_rank_diff> 名**

| 关键词 | 你 | 他 | 高你 | 词热度 |
|---|:-:|:-:|:-:|:-:|
| `<kw1>` | <#N 或 未上榜> | **#<n>** | <diff> | <pop> <🔥 if ≥50> |
| `<kw2>` | ... | ... | ... | ... |
| `<kw3>` | ... | ... | ... | ... |

> **为什么是他**: <relevance_reason 一句中文>

---

## 2. <对手名> · ★... (...)
... (same structure, top 3 keywords each, 5–10 rivals total) ...

---

**重点 <N> 个**: #X / #Y / #Z — <one-sentence summary of each top rival's core threat>

要详细看哪个的关键词布局?告诉我编号,我可以用 /appmate-aso-optimize 拉出他的元数据对照。
```

### Layout rules (inviolable)

1. Each rival is its own `H2 (##)` block — low-density layout (per user memory: 增长策略报告低密度排版).
2. Keywords are wrapped in backticks `` `桌面便签` `` (consistent with `aso-daily-report`).
3. Column headers are full Chinese words. **Never** use single-letter abbreviations `T/S/K/X` (per user memory: ASO 输出禁单字母位置缩写).
4. The "为什么是他" line uses a `>` blockquote (highlights the LLM-judged relevance as something the reader can challenge).
5. The keywords table shows **exactly top 3 outranked keywords per rival** — never more. Full list is in JSON.
6. **`dropped_by_relevance` is never rendered in markdown.** It lives in JSON for diagnostic inspection only.
7. Sort rivals by `threat_score` descending.
8. The closing "重点 N 个" + "详细看哪个" line is required (consistent with `feature-ideation` / `growth-strategy`).
9. The full markdown must be pasted back into the conversation — never "saved competitors_<slug>.md" alone (per user memory: 日报对话直贴).

---

## 9. Data contracts

### 9.1 `data/phase_a_competitors_<slug>.json`

```json
{
  "app": "Sticky Note Pro",
  "app_id": "1482080766",
  "bundle_id": "com.fengyiqi.PostItnoteForMac",
  "platform": "MAC_OS",
  "market": "CHN",
  "primary_genre_id": 6007,
  "locale": "zh-Hans",
  "downloads_30d_in_market": 1234,
  "generated_at": "2026-05-16T14:00:00Z",
  "raw": {
    "title": "便签Pro:备忘录Memo便利贴",
    "subtitle": "桌面便签 快速记事",
    "keywords": "便签,云便签,桌面便签,..."
  }
}
```

### 9.2 `data/phase_b_competitors_<slug>.json`

```json
{
  "app": "...",
  "app_id": "...",
  "market": "CHN",
  "primary_genre_id": 6007,
  "generated_at": "...",
  "tokens": ["sticky note", "便签", "桌面便签", "memo", "..."],
  "self_ranks": { "sticky note": 7, "便签": 12, "桌面便签": null },
  "candidates": [
    {
      "itunes_id": "1234567890",
      "bundle_id": "com.foo.bar",
      "name": "XX 便签",
      "description_short": "(first 200 chars)",
      "primary_genre_id": 6007,
      "rating": 4.7,
      "review_count": 12340,
      "outranked_keywords": [
        { "keyword": "便签 widget", "self_rank": 200, "rival_rank": 3, "diff": 197, "popularity": 76 },
        { "keyword": "桌面便签",   "self_rank": 15,  "rival_rank": 5, "diff": 10,  "popularity": 64 }
      ],
      "outrank_count": 12,
      "avg_rank_diff": 8.4,
      "threat_score": 18950
    }
  ]
}
```

Note: in `self_ranks`, `null` represents "not in top 200" (more compact than 200 for the JSON-side; the scoring step normalizes to 200).

### 9.3 `data/competitors_<slug>.json` (final, downstream-facing)

```json
{
  "app": "...",
  "app_id": "...",
  "market": "CHN",
  "primary_genre_id": 6007,
  "generated_at": "...",
  "tokens": ["..."],
  "self_ranks": { "...": ... },
  "filtered": [
    {
      "itunes_id": "1234567890",
      "bundle_id": "com.foo.bar",
      "name": "XX 便签",
      "primary_genre_id": 6007,
      "rating": 4.7,
      "review_count": 12340,
      "description_short": "...",
      "outranked_keywords": [ ... full list ... ],
      "outrank_count": 12,
      "avg_rank_diff": 8.4,
      "threat_score": 18950,
      "relevance_keep": true,
      "relevance_reason": "「XX便签」描述同样主打桌面快速记事,目标用户重叠"
    }
  ],
  "dropped_by_relevance": [
    {
      "itunes_id": "...",
      "name": "心情打卡 X",
      "threat_score": 4200,
      "drop_reason": "描述显示是情绪记录工具,跟便签场景不重叠"
    }
  ]
}
```

This is the **downstream contract**. Future iterations of `feature-ideation`, `growth-strategy`, and `aso-optimize` can read this file as their canonical competitor source. The shape is intentionally stable: once shipped, `filtered[*]` fields are append-only.

---

## 10. Key parameters

| Parameter | Value | Where defined |
|---|---|---|
| `SERP_LIMIT` | 200 | reuse `aso_report.ITUNES_BASE` constant |
| `MIN_OUTRANK_COUNT` | 3 | new constant in `competitor_research.py` |
| `MAX_CANDIDATES_BEFORE_LLM` | 25 | new constant |
| `DESCRIPTION_TRUNCATE` | 200 | new constant |
| `TOP_N_RIVALS` | 10 | upper bound; actual count depends on LLM keep |
| `MIN_RIVALS_FOR_REPORT` | 3 | below this, markdown shows ⚠️ evidence-thin warning |
| `TOP_K_KEYWORDS_PER_CARD` | 3 | markdown-only display limit |
| `SELF_NORANK_CEILING` | 200 | unranked-self normalization for scoring |
| `RANK_CACHE_TTL_DAYS` | 7 | iTunes Search `rank_cache` reuse window (existing mechanism, not specific to this skill) |

**Cache lifetimes**:
- `data/itunes_lookup_cache.json` (new): no TTL. App categories are stable; one cached entry per `itunes_id` indefinitely.
- `data/rank_cache.json` (existing): 7-day reuse, shared with `aso-daily` / `aso-optimize`.
- `data/competitors_<slug>.json` (new): **no TTL — overwritten on every run**. Freshness is the consumer's responsibility; the `generated_at` field is the canonical timestamp to check.
- `data/phase_a_competitors_<slug>.json` and `data/phase_b_competitors_<slug>.json` (new): intermediate artifacts, overwritten on every run.

---

## 11. Boundary with existing skills

| | `competitor-research` (this spec) | `feature-ideation` / `growth-strategy` |
|---|---|---|
| Primary signal | iTunes Search SERP overlap + strict outrank | AppMate RAG semantic similarity |
| Selection | top 5–10 by threat score | fixed 8–10 by RAG `S` score |
| Role of output | the deliverable itself | transient input evidence |
| Persistence | `competitors_<slug>.json` (7-day cache) | not cached |
| Relevance check | LLM reads name + description | trusts RAG semantic similarity |
| Genre filter | hard | none |
| RAG dependency | none | required |

`aso-optimize` mentions competitors in its methodology text but does not call any source. Not touched in this iteration.

---

## 12. File and command additions

### New files
- `commands/appmate-competitors.md` — slash command definition (follows pattern of existing `commands/appmate-*.md`)
- `skills/competitor-research/SKILL.md` — skill process documentation (mirrors the structure of `skills/feature-ideation/SKILL.md`)
- `scripts/competitor_research.py` — data layer (subcommands `analyze`, `rank`, `show-a`, `show-b`)
- `tests/test_competitor_research.py` — pytest cases

### Modified files
- `.claude-plugin/plugin.json` — no change needed (skills/commands are auto-discovered)
- `README.md` — add a row to the "6 workflows" table → "7 workflows"

### No changes to
- `skills/feature-ideation/SKILL.md`
- `skills/growth-strategy/SKILL.md`
- `skills/aso-optimize/SKILL.md`
- `scripts/feature_ideate.py`, `scripts/growth_strategy.py`, `scripts/aso_optimize_v2.py`
- `scripts/appmate_rag_client.py`

---

## 13. Testing checklist

### Unit / integration (pytest)
- [ ] `find_app` integration: fuzzy / bundle / SKU / itunes_id all resolve correctly (reused, but a sanity test in this script's test file)
- [ ] `rank_keyword_with_details` returns full metadata for each SERP entry; respects 4-retry policy on 429/5xx; reuses rank_cache
- [ ] `aggregate_rivals`: cross-token aggregation correctness on a fixture SERP
- [ ] `score_threat`: known-input correctness (e.g. one rival at #3 on popularity-76 word, self unranked → contribution 14,972)
- [ ] `filter_by_genre_and_density`: removes cross-genre, removes outrank_count < 3
- [ ] Phase A JSON shape validation (all required fields present)
- [ ] Phase B JSON shape validation
- [ ] Final JSON shape validation
- [ ] `keyword_local.lookup_popularity` failure → falls back to popularity=1, scoring still runs
- [ ] Credentials gate: missing config → exit 2 with the standard message

### End-to-end (manual one-off)
- [ ] Run against a real app with ≥ 10 keywords; verify markdown structure
- [ ] Run against an app with 0 outranking rivals (all hard-filters reject) → markdown shows "no rivals" state
- [ ] Run twice within 7 days; second run reuses rank_cache (no Apple call)

### Layout / content (markdown)
- [ ] Each rival is its own `## N. <name>`
- [ ] Keywords are wrapped in backticks
- [ ] **No** `T/S/K/X` single-letter abbreviations
- [ ] Each rival's table shows exactly 3 keywords (full set in JSON)
- [ ] `dropped_by_relevance` does NOT appear in markdown
- [ ] Closing "重点 N 个" + "详细看哪个" present
- [ ] Full markdown is pasted back into the conversation, not just "saved to <path>"

---

## 14. Known limits

- Tokenization is LLM-dependent — same caveat as `aso-daily-report`. Cannot run unattended via cron.
- SERP changes hourly; a 7-day cache reuse can show stale ranks. Acceptable for a research deliverable (this is not a daily monitor).
- An app with very few keywords (e.g. only 1–2 distinct tokens) cannot reach `MIN_OUTRANK_COUNT = 3`, so will produce empty results. The empty-state markdown explains why.
- LLM batched relevance: drop reasons are subjective. Repeat runs vary on borderline cases (the `dropped_by_relevance` JSON record lets the user audit).
- `primary_genre_id` from iTunes Search is the app's primary; cross-listed apps (multiple genres) are filtered only on the primary.
- The score formula assumes `popularity` is comparable across regions. `keyword_local` already partitions by region (`keyword_reference_<region>.json`), so this holds within a single market.

---

## 15. Out of scope (deferred)

The following are intentionally left for a follow-up spec:

- **Downstream integration**: making `feature-ideation` / `growth-strategy` / `aso-optimize` consume `competitors_<slug>.json` instead of (or in addition to) RAG. The JSON contract in §9.3 is shaped to make this future integration straightforward, but the actual wiring is not in this iteration.
- **Continuous monitoring**: daily diffs of competitor movement. Possible v2 if there is demand.
- **Multi-market view**: an app with traffic in CN + US + JP currently produces three separate runs. A multi-market consolidated view is future work.
- **Competitor keyword layout exposure**: a "show me how this rival arranges their title/subtitle" feature. iTunes Search returns the rival's `trackName`; full keyword field is not available via public API (it is private to App Store Connect).
