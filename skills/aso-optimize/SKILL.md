---
name: aso-optimize
description: Deep ASO optimization for a single app — produce new App Store title, subtitle, and keyword strings. Use when the user wants to optimize or rewrite an app's ASO metadata, improve keyword rankings, or "跑 ASO 优化" for a specific app.
---

# ASO Optimization Workflow v3

> This skill is the single authoritative reference for the ASO optimization flow. Re-read it before every run.

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
| **Astro MCP** | popularity (1-99) + difficulty (1-99) | script |
| **LLM (Claude)** | Chinese tokenization / candidate generation / comparison / synthesis | conversation layer |
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

Read the `current_metadata` field of `data/phase_a_<slug>.json` and **cut real ASO words using Chinese semantics**:

- Do not rely on jieba (its boundaries are often wrong).
- Do not emit long CJK mashed runs (e.g. `网络翻译邮箱地图地球`).
- Tag each token with its source: **Title / Subtitle / Keywords** (write the full word, never the single letters T/S/K).

**Typical output**: 30-40 real tokens covering all the semantics of the existing metadata.

---

# Step 3 · Score the current state (script, may take multiple runs, cap = 30)

```bash
python3 scripts/aso_optimize_v2.py validate <app> --candidates <Step 2 output>
```

- Each token → iTunes rank + Astro popularity + Astro difficulty.
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
| §10.4 Chinese compression | high-pop words may form a 3-5 word comma-free run |
| Character utilization | ≥ 95/100 char |
| **Order has no effect** (§7.3 #4 explicit) | sort by pop descending for readability only |

## 8.4 §10.2 dual-locale expansion audit

**Must check**: does the app have both `zh-Hans + en-GB` (or a same-region dual locale) enabled? If only one → Step 8 **also** outputs a second keyword-field suggestion (no duplicate words, expanding to 200 char).

## 8.5 §10.5 long-term weight note

The output footer **must include**:
- The list of newly added words with pop ≥ 50.
- A suggestion to keep 1-2 versions unchanged to accumulate Apple's implicit weight.
- A suggestion to re-run `analyze` every 30 days to watch the rank trend.

## 8.6 Output format (must contain all 6 sections)

> **⚠️ Wording rule (must follow)**: in the deliverable document, **every position / field reference must use the full name** — `主标题 / 副标题 / 关键词` or English `Title / Subtitle / Keywords`. **The single letters T / S / K / X are not allowed** (this applies to section rule text and checklists too). Reason: an abbreviation has no context when the user reviews it.

```markdown
# <App> · ASO 优化建议

**生成时间** / **主市场** / **App 信息**

## 三段建议（直接可粘贴）

主标题  (X/30 char): <NEW>
副标题  (X/30 char): <NEW>
关键词 (X/100 char): <NEW>

## OLD vs NEW 对照

| 字段 | OLD | NEW | Δ |

## 删除清单

| 词 | 原位置 | 旧 pop | §删除依据 |
("原位置" column: write `主标题` / `副标题` / `关键词`, not T/S/K)

## 新增清单

| 词 | 新位置 | pop | §加入依据 |
(same: `主标题` / `副标题` / `关键词`)

## §10.2 双 locale 扩容审计（如适用）

## §10.5 长期权重追踪

## 📌 交付后建议（必含 — 给用户的可选项）
```

The deliverable document is written in **Chinese** by design — do not translate the rendered deliverable.

## 8.7 Post-delivery suggestions (must include — 2 options for the user)

After delivering the 3 strings, **always** append these two suggestions for the user to choose from:

### Suggestion ① · CJK comma-free compression (§10.4)

**Trigger condition**: the main-market locale ∈ `{zh-Hans, zh-Hant, ja, ko}`.

Output template:
```markdown
### 📌 建议 ① · 中日韩场景去逗号压缩

如果你的主市场是 CN/JP/KR/TW/HK，可去掉关键词字段的逗号，
让 Apple 中文/日文分词器自动 mix-and-match：

- **收益**：腾出 N 个字符（每个逗号 1 字符），多塞 N 个 token
- **风险**：失去"明确目标词"边界，依赖 Apple 自动分词
- **推荐策略**：高 pop 词（≥ 40）保留逗号；尾部低 pop 长尾可压缩

对比示例：
  逗号版 (X/100, N 词):  A,B,C,D,E,F,...
  压缩版 (Y/100, M 词):  A,B,CDE,FGH,...  ← 末尾压缩

要应用压缩版吗？(yes / no / 部分压缩)
```

**When not to output**: if the main market is an English/Latin-script market, skip this suggestion.

### Suggestion ② · Whether to use the full character limit

**Always output** (regardless of market):

```markdown
### 📌 建议 ② · 是否尽量用完字数限额

当前利用率：
  · 主标题  X/30 char (X%)
  · 副标题  X/30 char (X%)
  · 关键词 X/100 char (X%)

可选方案：
- **A. 保持当前**（精炼，高确信度词组合）
- **B. Title/Subtitle 也用满** → 我加更多 §10.1 第二梯队长尾词
- **C. 仅 Keywords 用满 100 char** → 补到 99-100 char
- **D. 全部用满**（最大覆盖但混入中等 pop 词）

要哪个？(A / B / C / D)
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

# Note on Chinese tokenization

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
- [ ] **All position references use full names** (主标题/副标题/关键词 or Title/Subtitle/Keywords; **no single-letter T/S/K abbreviations**)

## Post-delivery suggestions (§8.7 required)
- [ ] Suggestion ① CJK comma-free compression (only when the main-market locale ∈ CJK)
- [ ] Suggestion ② whether to use the full character limit (always output)

---

# Connection to other workflows

- The `aso-daily-report` skill finds an app's keyword dropping out of the top 20 → trigger this workflow (`aso_optimize_v2.py analyze <app>`) for a deep optimization.
- This workflow's new metadata → the user updates App Store Connect → a few days later the daily report shows the rank change.
