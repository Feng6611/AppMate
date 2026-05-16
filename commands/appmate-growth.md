---
description: Generate a stage-diagnosed growth strategy for an app — phase diagnosis plus 3-5 actionable strategies (auto-chains /appmate-competitors on first run for an app).
---

Run the AppMate growth strategy workflow for the app: **$ARGUMENTS**

**Step 0 — credentials gate.** From the plugin root, run:

```bash
python3 scripts/appmate_config.py check
```

If the exit code is **not 0**, STOP immediately. Do NOT invoke the `growth-strategy` skill or run any further scripts. Tell the user that AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup` to finish configuration.

**Step 1 — ensure competitor data exists (auto-chain if missing).** This workflow consumes `data/competitors_<slug>.json`, the final artifact of `/appmate-competitors`. Both skills compute the slug from the same `slugify(app_name, market)` rule, so passing `"$ARGUMENTS"` to both guarantees the slug matches.

Before invoking `growth_strategy.py`:

- If `data/competitors_<slug>.json` already exists for this app, proceed.
- If it does **not** exist, **first invoke the `competitor-research` skill end-to-end for `"$ARGUMENTS"`** — Stage 1 `analyze`, Stage 2 LLM keyword tokenization, Stage 3 LLM relevance pass, write final JSON + markdown, paste the rivals markdown back into the conversation (per that skill's own rules). Then continue here with Step 2 below. The user gets both reports out of one ask, which is intended — the rivals card is the same competitive evidence the growth plan will reason from.

**No RAG fallback. No placeholder competitors.** The only two paths to competitor evidence are: the cached file, or a fresh `/appmate-competitors` run.

Safety net: `growth_strategy.py` exits 2 with `competitors JSON not found` if the script is invoked before the JSON exists. In normal skill-driven runs you should not hit it because the auto-chain happens first. If you do hit it (e.g. the script was invoked outside the skill), run `/appmate-competitors "$ARGUMENTS"` end-to-end, then re-invoke this command.

**Step 2 — generate the growth strategy.** Invoke the `growth-strategy` skill and follow it end-to-end, starting with `python3 scripts/growth_strategy.py "$ARGUMENTS"`. If no app was given, ask the user which app to analyze (accepts App Store ID / bundle ID / SKU / fuzzy name). Paste the full Chinese markdown report back into the conversation.
