---
description: Find the most valuable competitors for an app — rivals who outrank you on your own keywords.
---

Run the `competitor-research` skill for the app specified as an argument.

**Argument**: `$ARGUMENTS` — App Store ID / bundle ID / SKU / fuzzy app name (one app).

**Process**:

1. Verify credentials by running `python3 scripts/appmate_config.py check`. If exit code ≠ 0, stop and instruct the user to run `/appmate-setup`.
2. Run `python3 scripts/competitor_research.py analyze "$ARGUMENTS"` to write `data/phase_a_competitors_<slug>.json`.
3. Read phase_a, perform LLM keyword tokenization per `skills/competitor-research/SKILL.md` Stage 2 rules.
4. Run `python3 scripts/competitor_research.py rank "$ARGUMENTS" --tokens "<comma-separated tokens>"` to write `data/phase_b_competitors_<slug>.json`.
5. Read phase_b, perform the batched LLM relevance filter per Stage 3 rules.
6. Write `data/competitors_<slug>.json` and render `data/competitors_<slug>.md` per the markdown template.
7. **Paste the full markdown back into the conversation.** Do not say "saved" alone.

Refer to `skills/competitor-research/SKILL.md` for the full rules, prompts, and checklist.
