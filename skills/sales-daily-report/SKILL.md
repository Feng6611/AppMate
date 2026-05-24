---
name: sales-daily-report
description: Generate the App Store sales & downloads daily report for all live apps. Use when the user asks for a sales report, a revenue/downloads summary, daily numbers across their apps, or "跑日报".
---

# Sales & Downloads Daily Report

> Run one sales & download report covering every live app, output as markdown.

## Step 0 — Prerequisites (credentials must be configured)

Every step in this skill calls App Store Connect APIs. **Before any other step**, run:

```bash
python3 scripts/appmate_config.py check
```

If exit code ≠ 0, STOP. Do not invoke any other part of this skill, do not run `scripts/sales_report.py`. Tell the user AppMate credentials are not configured, show the precheck output verbatim, and tell them to invoke the `appmate-setup` skill. The downstream script also enforces this gate (exits 2 with the same message), but the explicit precheck saves you from spinning up the full 65-day fetch.

## One-line summary

Pull ~65 days of daily reports from App Store Connect → aggregate across 5 time dimensions → totals + Top-3 apps + share + percentage change → markdown report.

## Input / Output / Trigger

| Item | Content |
|---|---|
| **Trigger** | `python3 scripts/sales_report.py` (0 args, 0 user intervention) |
| **Input** | `data/apps_full.json` (live-app list) + `data/sales_cache.json` (historical daily reports) |
| **Output** | stdout markdown + `data/report.md` file + **Claude pastes the full markdown back into the conversation** |

## User intervention points

**Zero.** Fully automatic. The script generates the report → the file lands → **Claude must paste the complete report into the conversation reply. It must not just say "saved to report.md" or post only a summary.** The file is a side product; the conversation reply is the primary delivery.

## The 5 time dimensions (fixed order, do not reorder)

| Dimension | Current range | Compared to |
|---|---|---|
| Yesterday | DATA_TODAY (most recent day with data) | the day before |
| Last 7 days | DATA_TODAY back 7 days | the prior 7 days |
| Last 30 days | DATA_TODAY back 30 days | the prior 30 days |
| This week | this Monday → DATA_TODAY | (shows "Data not yet published by Apple" if this week's data is not in yet) |
| This month | the 1st → DATA_TODAY | **the entire previous month** (not the same day range) |

## Workflow (the script does this automatically in one pass)

1. **Load `data/sales_cache.json`** — missing dates are fetched from ASC `/v1/salesReports`; gzipped TSV is decoded and cached; failed dates are recorded as `_error` and retried next run; empty caches for the last 3 days are auto-refreshed (Apple data can be delayed).
2. **Anchor DATA_TODAY** — scan backward from today for the first date that actually has data (Apple's daily report usually lags 1-2 days).
3. **Aggregate by day** — parse each TSV row (Title / Country Code / Units / Developer Proceeds × FX → USD); classify downloads by Product Type Identifier; merge IAP rows into their parent app via Parent Identifier (SKU).
4. **Slice + sum across the 5 dimensions, compute delta** — per dimension: total revenue + total downloads + previous-period percentage change + Top-3 (by revenue / by downloads).
5. **Render markdown** per the template below.

## Report template (v1 — follow exactly)

**Rendered in Chinese by default for this fork.** If the user explicitly asks for another language, translate the template headers, labels and prose accordingly. App / SKU / country names stay in their original form. The script itself emits Chinese Markdown.

### Top one-liner (required)

```
**昨日 ({MM-DD}) 收入 ${X}** · 本周 ${X} · 本月 ${X}
```

If Apple has not published a range's data yet, that slot shows `N/A` and the per-dimension block prints `> ⏳ Apple 尚未发布该时间段数据`.

### Totals block (5 dimensions, fixed order)

```markdown
## 🧮 汇总

### {dimension} ({range-compact})

- 💰 收入: **{current revenue}**  ·  {↑↓ N%}
    1. **{revenue}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
    2. **{revenue}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
    3. **{revenue}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
- 📥 下载量: **{current downloads}**  ·  {↑↓ N%}
    1. **{downloads}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
    2. **{downloads}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
    3. **{downloads}** ({share}%)  ·  {↑↓ N%}  ·  {app name}
```

### Footer note (required)

```
> ⓘ 收入包含多币种，并使用粗略汇率换算为 USD，仅用于趋势判断，不作为财务对账。Apple 日报通常延迟 1-2 天。
> 本月与**完整上个月**对比；近 7/30 天分别与前一个 7/30 天窗口对比。
```

## 10 inviolable rules

1. **Headings stay in a single language** — match the user's conversation language; don't mix languages within a heading.
2. **No bar charts** — change is shown only as `↑↓ N%`.
3. **No "current X vs previous Y"** — dates go only in the H3 heading parentheses.
4. **No "previous N"** — show only the current value plus the percentage change.
5. **Keep indentation** — the Top-3 list uses 4-space indentation, nested under the downloads/revenue bullet.
6. **Value first, app name last** — `{rank}. **{value}** ({share}) · {change} · {app name}`.
7. **Revenue before downloads.**
8. **App names** keep their full original form, not truncated.
9. Fixed emoji set: 📊 title / 🕐 time / 📅 date / 📱 app / 🧮 totals / 💰 revenue / 📥 downloads / ⏳ data not in / ⓘ note.
10. **Must paste back into the conversation** — after running the script, Claude must paste the complete markdown report into the reply; "report.md generated" alone or a summary alone is not allowed.

## Data handling details

- **Revenue**: each row's `Units × Developer Proceeds`, converted to USD via a static 40+ currency FX table. This is an estimate (not accounting-grade — finance reconciliation uses `/v1/financeReports`), but cross-app relative comparison is reliable.
- **IAP merging**: an IAP row's `Title` is the IAP product name; `Parent Identifier` is the parent app's SKU. IAP units go to `iap_units`; IAP revenue is folded into the app's `revenue_usd`.
- **Download classification** (by `Product Type Identifier`): `1*` / `F1` / `FI1` count as installs; `7*` updates do not count; `IA*` IAP/subscription rows count toward revenue and `iap_units` but not downloads.
- **Sorting**: Top-3 is descending by current downloads / revenue within each dimension.

## CLI

```bash
# from the plugin repo root
python3 scripts/sales_report.py
```

No arguments. All logic runs automatically.

## Known limits

- Apple's daily sales reports lag 1-2 days (the script auto-anchors to the most recent day with data).
- Revenue is converted via a static FX table (not a reconciliation value).
- "This week" shows "data not in" early in the week before data arrives.
- Multi-currency refunds (negative Units) are subtracted automatically but not highlighted separately.

## Connection to other workflows

- Upstream dependency: the `appmate-setup` skill's ASC API credentials.
- Downstream: if an app's downloads/revenue drop sharply → trigger `aso-daily-report` to investigate the ASO side, or `aso-optimize` to redo the metadata.
