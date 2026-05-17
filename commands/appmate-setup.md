---
description: Set up or troubleshoot AppMate credentials and config (App Store Connect API).
---

Run the AppMate setup walkthrough. Invoke the `appmate-setup` skill and follow it end-to-end.

**Critical step you must surface to the user before they generate the API key**: AppMate is read-only and the API key it uses must NOT have any write role. When generating the key in App Store Connect, instruct the user to check ONLY read-only roles (**Sales / 销售**, **Access to Reports / 访问报告**, **Customer Support / 客户支持**, **Marketing / 营销**), and **NEVER** check **Admin / 管理**, **Developer / 开发者**, **App Manager / App 管理**, or **Finance / 财务** — those grant write access to live App Store data, build uploads, app metadata, or banking. AppMate runs a runtime role probe (against `/v1/bundleIds` and `/v1/financeReports`) on every startup and refuses to start if Developer / Finance / Admin is detected. The probe cannot distinguish App Manager from read-only roles, so the role-selection warning is the *only* defense against an accidental App Manager key — surface it upfront.

The user's only physical-world steps are: (1) generate the key in App Store Connect and (2) drop the `.p8` file into `config/`. Do **not** ask them to copy templates or edit `config/credentials.txt` themselves — ask them inline for the four values (`issuer_id`, `key_id`, the `.p8` filename, `vendor_number`) and write `config/credentials.txt` yourself. Then confirm with `python3 scripts/appmate_config.py check` (must exit 0 — runs offline credential validation + online key-role probe) plus the rest of the skill's self-check.
