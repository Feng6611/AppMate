---
description: Generate the ASO keyword-ranking daily report for the top-3 apps by downloads.
---

**Step 0 — credentials gate.** From the plugin root, run:

```bash
python3 scripts/appmate_config.py check
```

If the exit code is **not 0**, STOP immediately. Do NOT invoke the `aso-daily-report` skill or run any further scripts. Tell the user that AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup` to finish configuration.

**Only on exit 0**, proceed: invoke the `aso-daily-report` skill and follow it end-to-end, then paste the full markdown report back into the conversation. **Render the report in the same language the user has been using in this conversation** (English by default; switch to Chinese / Japanese / etc. if the user has been writing in that language). Translate the script's English template strings on the fly when rendering — do not paste raw English headers when the user is conversing in another language.
