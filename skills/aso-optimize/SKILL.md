---
name: aso-optimize
description: Deep ASO optimization for a single app — produce new App Store title, subtitle, and keyword strings. Use when the user wants to optimize or rewrite an app's ASO metadata, improve keyword rankings, run an ASO optimization pass for a specific app, or "跑 ASO 优化".
---

# ASO Optimization Workflow v3

> This skill is the single authoritative reference for the ASO optimization flow. Re-read it before every run.

## Step 0 — Prerequisites (credentials must be configured)

Every step in this skill calls App Store Connect APIs. **Before any other step**, run:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Do not invoke any other part of this skill, do not run `scripts/aso_optimize_v2.py`. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and tell them to invoke the `appmate-setup` skill. The downstream script also enforces this gate (exits 2 with the same message).

## Input / Output

| Item | Content |
|---|---|
| User input | An app identifier (bundle id / App Store id / SKU / fuzzy name match — any one) |
| Final output | 3 paste-ready strings for App Store Connect: title, subtitle, keywords |
| Stage artifacts | `data/phase_a_<slug>.json` · `data/phase_b_<slug>.json` · `data/aso_optimize_<slug>.md` |

## Toolchain

| Tool | Purpose | Called by |
|---|---|---|
| `data/apps_full.json` | Static metadata | script |
| `data/sales_cache.json` | Sales report (find the main market) | script |
| **iTunes Search Top-200** | Keyword ranking (same source as the App Store web page) | script |
| **Keyword reference table** | popularity (1-99) + difficulty (1-99) | script |
| **LLM (Claude)** | CJK / Chinese-Japanese-Korean tokenization (when the App Store metadata is in those languages) / candidate generation / comparison / synthesis | conversation layer |
| `references/aso-methodology.md` | Full methodology (§1-§12) | LLM reference |

## User intervention points (only 2)

1. **Start**: the user gives you an `<app>` identifier.
2. **End**: you deliver the 3 strings.

Everything in between runs automatically without interruption.

---

# Step 1 · Anchor (script, one-shot)

```bash
python3 scripts/aso_optimize_v2.py analyze <app>
```

- Find the app (fuzzy match).
- Split the last-30-day downloads by country, take the largest market.
- Pick the locale (`pick_locales_for_country`).
- Output the raw `title / subtitle / keywords`.

**Artifact**: `data/phase_a_<slug>.json` (metadata + tokens cut by the script's basic tokenizer).

---

# Step 2 · LLM tokenization (you, conversation layer)

Read the `current_metadata` field of `data/phase_a_<slug>.json` and **cut real ASO words** — apply CJK / Chinese-Japanese-Korean tokenization when the App Store metadata is in those languages (the metadata's own locale, independent of what language you're conversing in with the user):

- Do not rely on jieba (its boundaries are often wrong).
- Do not emit long CJK mashed runs (e.g. `网络翻译邮箱地图地球`).
- Tag each token with its source: **Title / Subtitle / Keywords** (write the full word, never the single letters T/S/K).

**Typical output**: 30-40 real tokens covering all the semantics of the existing metadata.

---

# Step 3 · Score the current state (script, may take multiple runs, cap = 30)

```bash
python3 scripts/aso_optimize_v2.py validate <app> --candidates <Step 2 output>
```

- Each token → iTunes rank + popularity + difficulty.
- **No rank ≤ 20 filter** — full data.
- Cap of 30 candidates per run; split into batches if you exceed it.

**Artifact**: `data/phase_b_<slug>.json`

---

# Step 4 · Classify the current state (you, by the §10.1 four quadrants)

| Quadrant | Marker | Condition | Handling |
|---|---|---|---|
| Tier 1 — high relevance, high heat | 🟢 Target | rank ≤ 20 **AND** pop ≥ 40 | **Keep / promote to Title or Subtitle** |
| Tier 2 — high relevance, low heat | ⚪ Niche | rank ≤ 20 **AND** pop < 40 | Long-tail placeholder, keep in Keywords |
| Tier 3 — low relevance, low heat | 💀 Junk | pop ≤ 10 **OR** (rank > 100 AND pop ≤ 20) | **Must remove** |
| Tier 4 — low relevance, high heat | 🟡 Push | pop ≥ 40 **AND** rank > 50 | diff ≤ 60 push; > 60 skip |

---

# Step 5 · Generate candidates (you, by §10.1 + the 7 strategies)

**Selection priority (§10.1)**: brand words > industry words > competitor words.

**§10.1 industry-word tree expansion** (core word + business association / generic suffix, 4 angles): common words, media-related, transaction-related, software platform.

**The 7 strategies**:

| # | Strategy | § basis |
|---|---|---|
| 1 | Synonym expansion | §10.1 |
| 2 | Long-tail combination (core + suffix) | §10.4 |
| 3 | Hypernyms / hyponyms | §10.1 |
| 4 | Spelling variants / plurals | §2.4 (English only) |
| 5 | Brand-ecosystem association | §10.1 |
| 6 | Similar-competitor inspiration | §10.1 |
| 7 | Plural / compound completion | §2.4 |

## 5.0 Silent reference consultation (mandatory, never surfaced)

Before producing candidates, **read** the indie keyword reference for the
target app's primary market:

- main market locale ∈ `zh-Hans / zh-Hant / cn` → `data/keyword_reference_cn.json`
- main market locale ∈ `en-US / en-GB / us` → `data/keyword_reference_us.json`

Each row carries `{keyword, popularity, popularity_is_floor, difficulty,
apps_count, source_apps_count, source_apps, top_category}`. This is a static
table built from the top-100 indie apps in that store — it is **internal
context only**.

Use it as:

1. **Candidate seeding** — filter to rows whose `top_category` matches the
   target app's category (or adjacent). Promote those whose semantics overlap
   the app's Step-2 tokens into the candidate pool before running the 7
   strategies. Reason: indie-validated words have a higher prior of being
   worth real estate.
2. **Tie-breaker in Step 7** — between two candidates with similar pop/diff,
   prefer the one with higher `source_apps_count` (indie-validated). When
   `popularity_is_floor: true`, treat `popularity` as "no signal" (don't use
   the literal 5) and decide via difficulty + indie evidence alone.
3. **Red-ocean awareness** — `source_apps_count ≥ 8` means ≥ 8% of all indie
   top-100 apps target the word. Still usable, but reserve for Title /
   Subtitle star slot; avoid as Keywords filler (saturated; low marginal CVR).
4. **Blue-ocean signal** — `popularity ≥ 40 AND source_apps_count ≤ 1 AND
   difficulty < 60` is the most valuable bucket. Seed these aggressively.

**Output discipline (do NOT do)**:

- Do not mention "indie reference", "source_apps_count", "top_category", or
  the file path in any user-facing section (deliverable, OLD vs NEW table,
  deletion / addition § basis, §10.5 note, conversation).
- Do not add new columns to any output table.
- Cite the official methodology (§10.1 / §10.4 / etc.) in all § basis
  columns — never the reference table.

The user sees the standard `pop / diff / rank` numbers; the candidate set is
just smarter.

Produce **10-15 candidates** per round.

---

# Step 6 · Validate candidates (script, automatically each round)

Same as Step 3 — each round automatically runs `validate`, overwriting `data/phase_b_<slug>.json`.

---

# Step 7 · Automatic comparison & decision (you, rule-based, no user confirmation needed)

## 7.1 Candidate four-quadrant classification (§10.1)

Every validated candidate must land in a quadrant and be handled per its rule (same table as Step 4).

## 7.2 Position admission thresholds (§5.2)

| Field | Admission condition |
|---|---|
| Title (≤30 char) | pop ≥ 40 **OR** rank ≤ 5 |
| Subtitle (≤30 char) | pop ≥ 30 **OR** rank ≤ 10; **no duplicates of Title (§6.2)** |
| Keywords (≤100 char) | pop ≥ 20 **OR** rank ≤ 20; **no duplicates of Title / Subtitle tokens (§7.3 #3)** |
| Long-tail combo (pop=5 rank≤5) | enters Keywords only when replacing a weaker token |

## 7.3 Candidate vs weakest existing token — replacement conditions

Candidate `X` replaces existing `Y` only when:

```
pop(X) ≥ pop(Y) × 1.5
  OR
rank(X) ≤ 50 AND rank(Y) > 100
  OR
pop(X) ≥ 20 AND pop(Y) ≤ 5
```

## 7.4 §7.3 mandatory rules (9 rules for the keyword field)

| Rule | Application |
|---|---|
| ① Comma-separated | Keywords forced to `,` |
| ② No duplicate tokens | case-insensitive dedup |
| ③ No duplicates of Title / Subtitle tokens | ✓ |
| ④ Order does not affect weight | (sort by pop descending for maintainability) |
| ⑤ Split phrases into words | Apple does mix-and-match automatically |
| ⑥ Singular form | English only; not applicable to Chinese |
| ⑦ Skip free words | reject: `app, the, by, free, best, top, leading, 最, 免费, 工具, 软件` |
| ⑧ Use all 100 chars | utilization ≥ 95% |
| ⑨ Fill by pop descending | ✓ |

## 7.5 Banned-word list (mandatory)

- **§5.4 title/subtitle banned words**: `best / top / #1 / leading / free / install now / 最 / 推荐`
- **Full competitor brand names** (violates Apple TOS): `有道云笔记 / 印象笔记 / 滴答清单 / Notion / Evernote / Bear / Obsidian / Workflowy / Logseq`
- **§2.3 category-derived words (free words)**: `Health & Fitness / Utilities / Productivity / 工具 / 软件 / 免费 / 应用` (used alone as placeholders)

## 7.6 §2.4 plural/compound rule (English only)

- If `|rank(singular) - rank(plural)| / rank(singular) > 15%` → keep both forms.
- Not applicable to Chinese.

## 7.7 Iteration loop (automatic)

```
loop:
  candidates = LLM_generate(rejected_pool, 10-15)
  validated = script_validate(candidates)
  passed = filter(validated, by 7.1-7.5)

  if len(passed) >= 3:
    proceed to Step 8

  rejected_pool ∪= candidates
  iteration += 1
  if iteration >= 3:
    proceed to Step 8 (with the current passed set)
  else:
    back to loop (avoiding rejected_pool)
```

---

# Step 8 · Synthesize new metadata (you, per §5/§6/§7/§10)

## 8.1 Title design (§5.2 / §5.3 / §5.5)

| Rule | Application |
|---|---|
| Embedded token count | **3-5** (more hurts CVR §5.5) |
| Must contain a §4.2 star keyword | at least 1 with pop ≥ 40 AND rank ≤ 10 |
| Separator strategy (§5.3) | `:` separates brand + description; `&` replaces `and`; prefer word roots |
| Banned (§5.4) | `best / top / #1 / leading / free / install now / 最` |
| Preserve brand recognition (§5.3) | a strong brand word must not be dropped |

### 8.1.1 Title token order (§5.3 + §9.5 CVR perspective)

**Premise**: the algorithm weight is insensitive to order, but **order indirectly affects ranking strength through CVR**.

| Position | What goes here | § basis |
|---|---|---|
| **1st** | weak brand → descriptive core word first; strong brand → brand word first | §5.3 STARZ vs Down Dog example |
| **2nd-3rd** | high-pop keywords (≥ 40) | §9.5 visual recognition → CVR |
| **End** | long-tail / modifiers / platform qualifiers | §5.3 space-saving technique |

**Judging brand strength**: the app's current rank on its own brand keyword. Already #1 → strong brand → brand word first. Not #1, or a category word is more famous → weak brand → descriptive word first.

## 8.2 Subtitle design (§6.2)

| Rule | Application |
|---|---|
| No duplicates of Title tokens | ✓ §6.2 rule 1 |
| Avoid vague words | banned: `most popular / social networking / 强大的 / 优秀的 / 极致 / 简洁` |
| Token count | **3-5 tokens with pop ≥ 30 across different dimensions** |
| Dimension suggestions | function words / internationalized brand / competitor-adjacent / synonyms |

### 8.2.1 Subtitle token order (§6.1 + §9.5 CVR perspective)

| Position | What goes here |
|---|---|
| **1st** | the word that best explains the core function (the user's "one decisive sentence") |
| **2nd-3rd** | synonyms / internationalized category words (English category words like `Memo / Stickies`) |
| **End** | long-tail placeholders / competitor-adjacent words |

## 8.3 Keywords field (§7.3 full 9 rules + §10.4)

| Rule | Application |
|---|---|
| ①-⑨ all 9 rules apply | see 7.4 |
| §10.4 CJK compression (zh/ja/ko metadata) | high-pop words may form a 3-5 word comma-free run |
| Character utilization | ≥ 95/100 char |
| **Order has no effect** (§7.3 #4 explicit) | sort by pop descending for readability only |

## 8.4 §10.2 dual-locale expansion audit

**Must check**: does the app have both `zh-Hans + en-GB` (or a same-region dual locale) enabled? If only one → Step 8 **also** outputs a second keyword-field suggestion (no duplicate words, expanding to 200 char).

## 8.5 §10.5 long-term weight note

The output footer **must include**:
- The list of newly added words with pop ≥ 50, rendered as a table with **`pop` AND `diff` columns** (diff is needed to flag which words are diff<60 "short-term reachable" vs diff>60 "long-term weight only").
- A suggestion to keep 1-2 versions unchanged to accumulate Apple's implicit weight.
- A suggestion to re-run `analyze` every 30 days to watch the rank trend.

## 8.6 Output format (must contain all 6 sections)

> **⚠️ Wording rule (must follow)**: in the deliverable document, **every position / field reference must use the full name** — `Title / Subtitle / Keywords` (or the user's-language equivalent, e.g. `主标题 / 副标题 / 关键词`). **The single letters T / S / K / X are not allowed** (this applies to section rule text and checklists too). Reason: an abbreviation has no context when the user reviews it.

```markdown
# <App> · ASO Optimization Suggestions

**Generated at** / **Main market** / **App info**

## Three strings (paste-ready)

Title    (X/30 char): <NEW>
Subtitle (X/30 char): <NEW>
Keywords (X/100 char): <NEW>

## OLD vs NEW comparison

| Field | OLD | NEW | Δ |

## Deletion list

| Word | Original position | pop | diff | rank | Reason |
("Original position" column: write `Title` / `Subtitle` / `Keywords`, not T/S/K)
**Column rules**:
- `pop` / `diff` / `rank` are mandatory — all three numbers are needed to verify §10.1 Tier / §10.4 / §7.2 decisions.
- `Reason` column must be a **plain-language sentence** explaining why the word is being deleted — written so a non-technical reader understands. Cite specific evidence (pop / diff / rank values, Apple behavior, semantic reasoning) instead of `§` shortcuts. The official `§` rule may be cited inline as supporting context, but the bulk of the cell is a readable sentence, not a code-like reference. Bad: `§10.1 Tier 3`. Good: `Zero search volume (pop=5), and Apple's CJK tokenizer already splits "组件" out of the Title's "桌面小组件" — repeating it wastes 2 chars`.

## Addition list

| Word | New position | pop | diff | rank | Reason |
(same: `Title` / `Subtitle` / `Keywords`)
**Column rules**: same as the Deletion list. The `Reason` column is a plain-language sentence stating (a) why this word is worth a slot, (b) which evidence drives the decision (pop / diff / rank), (c) what the expected outcome is (short-term rank push vs long-term weight accumulation). Bad: `§10.1 Tier 4 push`. Good: `pop 65 high + diff 48 unusually low; OneSearch can also surface system SMS; placing it in the Title should reach top 20 in 30-60 days`.

## §10.2 dual-locale expansion audit (if applicable)

## §10.5 long-term weight tracking

## 📌 Post-delivery suggestions (required — user-facing options)
```

**Rendered in the same language the user has been using in this conversation.** Default to English; if the user has been writing in Chinese / Japanese / Spanish / etc., translate the template headers, labels and prose accordingly. The proposed App Store metadata strings (title / subtitle / keywords) must remain in the target App Store's locale (e.g. zh-Hans for the CN store) regardless — only the surrounding explanation follows the user's conversation language.

## 8.7 Post-delivery suggestions (must include — 2 options for the user)

After delivering the 3 strings, **always** append these two suggestions for the user to choose from:

### Suggestion ① · CJK comma-free compression (§10.4)

**Trigger condition**: the main-market locale ∈ `{zh-Hans, zh-Hant, ja, ko}`.

Output template (translate into the user's conversation language; this English version is the source):
```markdown
### 📌 Suggestion ① · CJK comma-free compression

If your main market is CN/JP/KR/TW/HK, you can drop the commas in the Keywords field
and let Apple's CJK tokenizer mix-and-match automatically:

- **Gain**: frees N characters (1 per comma), letting you cram N more tokens
- **Risk**: loses the "explicit target word" boundary, relies on Apple's auto-tokenization
- **Recommended strategy**: keep commas around high-pop words (≥ 40); compress the low-pop long-tail at the end

Comparison:
  Comma version    (X/100, N words):  A,B,C,D,E,F,...
  Compressed       (Y/100, M words):  A,B,CDE,FGH,...  ← tail compressed

Apply the compressed version? (yes / no / partial)
```

**When not to output**: if the main market is an English/Latin-script market, skip this suggestion.

### Suggestion ② · Whether to use the full character limit

**Always output** (regardless of market). Translate into the user's conversation language; this English version is the source:

```markdown
### 📌 Suggestion ② · Whether to fill the character limit

Current utilization:
  · Title    X/30 char (X%)
  · Subtitle X/30 char (X%)
  · Keywords X/100 char (X%)

Options:
- **A. Keep as is** (tight, high-confidence word set)
- **B. Fill Title/Subtitle too** → I'll add more §10.1 second-tier long-tail words
- **C. Fill Keywords only to 100 char** → top up to 99-100 char
- **D. Fill everything** (max coverage but mixes in mid-pop words)

Which one? (A / B / C / D)
```

**After the user chooses**: re-output the 3 strings per the chosen option; leave the other sections unchanged.

---

# Command quick reference

```bash
# Step 1: anchor
python3 scripts/aso_optimize_v2.py analyze <app>

# Step 3 / Step 6: validate (each round)
python3 scripts/aso_optimize_v2.py validate <app> --candidates kw1,kw2,kw3,...

# Inspect
python3 scripts/aso_optimize_v2.py show-a <app>
python3 scripts/aso_optimize_v2.py show-b <app>
```

Steps 2 / 4 / 5 / 7 / 8 are all done by the LLM (Claude in the conversation).

# Key parameters / thresholds

| Parameter | Value | Source |
|---|---|---|
| Title max length | 30 char | §5.1 |
| Subtitle max length | 30 char | §6.1 |
| Keywords max length | 100 char | §7.1 |
| Keywords utilization floor | ≥ 95% | §7.3 #8 |
| Title embedded token count | 3-5 | §5.5 |
| Subtitle embedded token count | 3-5 | §6.2 |
| Single validate cap | 30 candidates | tool limit |
| Auto-iteration cap | 3 rounds | Step 7.7 |
| Passed-candidate threshold | ≥ 3 | Step 7.7 |
| Title pop admission | ≥ 40 OR rank ≤ 5 | Step 7.2 |
| Subtitle pop admission | ≥ 30 OR rank ≤ 10 | Step 7.2 |
| Keywords pop admission | ≥ 20 OR rank ≤ 20 | Step 7.2 |
| Replacement ratio (pop) | new ≥ old × 1.5 | Step 7.3 |
| §10.1 Tier 1 | rank ≤ 20 AND pop ≥ 40 | §10.1 |
| §10.1 Tier 3 | pop ≤ 10 must remove | §10.1 |

# Note on CJK / Chinese-Japanese-Korean tokenization (parsing CN/JP/KR-store metadata)

This is about tokenizing App Store metadata that is itself in CJK languages — independent of the language you're conversing in with the user.

**Do not use jieba or any automatic tokenizer.** Reasons: jieba boundaries are often wrong (e.g. `便利贴` cut into `便利` + `贴`); long CJK mashed runs produce noise; the LLM has semantic understanding and can recognize complete ASO words. LLM tokenization features: realistic word length (mostly 2-4 chars for Chinese), no long mashed runs, recognizes compound words (`桌面便签` is one ASO word, not `桌面` + `便签`), brand variants (`便笺` ≠ `便签`), typos / homophones.

# Checklist (must pass before executing Step 8)

## The 3 strings themselves
- [ ] Title ≤ 30 char
- [ ] Subtitle ≤ 30 char
- [ ] Keywords ≤ 100 char and ≥ 95% utilization
- [ ] Subtitle does not duplicate Title tokens (§6.2)
- [ ] Keywords do not duplicate Title / Subtitle tokens (§7.3 #3)
- [ ] No §7.3 #7 free words
- [ ] No §5.4 banned words (best / top / #1 / leading / 最 / 推荐)
- [ ] No full competitor brand names (§4.1)
- [ ] All §10.1 Tier 3 tokens removed
- [ ] Title order follows §8.1.1 (weak brand → descriptive first; strong brand → brand first)
- [ ] Subtitle 1st position is the core-function explainer word (§8.2.1)

## Section completeness
- [ ] OLD vs NEW comparison table generated
- [ ] Deletion list includes § basis
- [ ] Addition list includes § basis
- [ ] §10.2 dual-locale audit done
- [ ] §10.5 long-term weight note attached
- [ ] **All position references use full names** (Title/Subtitle/Keywords, or the user's-language equivalent such as 主标题/副标题/关键词; **no single-letter T/S/K abbreviations**)
- [ ] **No mention of indie reference, `source_apps_count`, `top_category`, or `data/keyword_reference_*` anywhere in the deliverable (§5.0 consultation must stay silent)**

## Post-delivery suggestions (§8.7 required)
- [ ] Suggestion ① CJK comma-free compression (only when the main-market locale ∈ CJK)
- [ ] Suggestion ② whether to use the full character limit (always output)

---

# Connection to other workflows

- The `aso-daily-report` skill finds an app's keyword dropping out of the top 20 → trigger this workflow (`aso_optimize_v2.py analyze <app>`) for a deep optimization.
- This workflow's new metadata → the user updates App Store Connect → a few days later the daily report shows the rank change.
