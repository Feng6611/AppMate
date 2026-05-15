---
description: Set up or troubleshoot AppMate credentials and config (App Store Connect API, AppMate RAG).
---

Run the AppMate setup walkthrough. Invoke the `appmate-setup` skill and follow it end-to-end.

**Critical step you must surface to the user before they generate the API key**: AppMate is read-only and the API key it uses must NOT have any write role. When generating the key in App Store Connect, instruct the user to check ONLY **Sales and Reports** / **Customer Support** / **Marketing**, and **NEVER** check Admin / Developer / App Manager / Finance — those grant write access to live App Store data, build uploads, app metadata, or banking. AppMate runs a runtime role probe on every startup and refuses to start if any refused role is detected; warn the user upfront so they don't have to regenerate the key.

After the user fills in `config/credentials.txt` and drops the `.p8` into `config/`, confirm with `python3 scripts/appmate_config.py check` (must exit 0 — this runs both the offline credential validation and the online key-role probe) plus the rest of the skill's self-check.
