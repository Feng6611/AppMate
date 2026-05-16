---
description: Deep ASO optimization for one app — produce new title, subtitle, and keyword strings.
---

Run the AppMate ASO optimization workflow for the app: **$ARGUMENTS**

**Step 0 — credentials gate.** From the plugin root, run:

```bash
python3 scripts/appmate_config.py check
```

If the exit code is **not 0**, STOP immediately. Do NOT invoke the `aso-optimize` skill or run any further scripts. Tell the user that AppMate credentials are not configured, show the precheck output verbatim, and tell them to run `/appmate-setup` to finish configuration.

**Only on exit 0**, proceed: invoke the `aso-optimize` skill and follow it end-to-end, starting with `python3 scripts/aso_optimize_v2.py analyze "$ARGUMENTS"`. If no app was given, ask the user which app to optimize (accepts App Store ID / bundle ID / SKU / fuzzy name).

**Render the deliverable in the same language the user has been using in this conversation** (English by default; switch to Chinese / Japanese / etc. if the user has been writing in that language). The proposed title / subtitle / keyword *strings themselves* must remain in the App Store's target-market language (e.g. zh-Hans for the CN store) — only the surrounding explanation, table headers, and verdict labels follow the user's conversation language.
