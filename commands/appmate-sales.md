---
description: Generate the App Store sales & downloads daily report for all live apps.
---

**Step 0 — credentials gate.** From the plugin root, run:

```bash
python3 scripts/appmate_config.py check
```

If the exit code is **not 0**, STOP immediately. Do NOT invoke the `sales-daily-report` skill or run any further scripts. Tell the user that AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup` to finish configuration.

**Only on exit 0**, proceed: invoke the `sales-daily-report` skill and follow it end-to-end — run `python3 scripts/sales_report.py` from the plugin root, then paste the full Chinese markdown report back into the conversation.
