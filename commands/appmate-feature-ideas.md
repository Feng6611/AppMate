---
description: Generate prioritized feature recommendations for an app from reviews + competitor evidence.
---

Run the AppMate feature ideation workflow for the app: **$ARGUMENTS**

**Step 0 — credentials gate.** From the plugin root, run:

```bash
python3 scripts/appmate_config.py check
```

If the exit code is **not 0**, STOP immediately. Do NOT invoke the `feature-ideation` skill or run any further scripts. Tell the user that AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup` to finish configuration.

**Only on exit 0**, proceed: invoke the `feature-ideation` skill and follow it end-to-end, starting with `python3 scripts/feature_ideate.py "$ARGUMENTS"`. If no app was given, ask the user which app to analyze (accepts App Store ID / bundle ID / SKU / fuzzy name). Paste the full Chinese markdown report back into the conversation.
