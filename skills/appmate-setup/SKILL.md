---
name: appmate-setup
description: Set up or troubleshoot AppMate plugin credentials and config. Use when the user wants to install, configure, or self-check AppMate, set up App Store Connect API access, or fix "config missing" errors from AppMate scripts.
---

# AppMate Setup

> Infrastructure for the whole plugin. Every other AppMate workflow depends on the credentials configured here.

## One-line summary

Install App Store Connect API credentials into a gitignored `config/` folder, then call them through `scripts/asc_client.py`. Keyword popularity / difficulty come from the static reference table shipped with the plugin (`data/keyword_reference_<region>.json`) — no extra setup. Competitor data is produced locally by the `competitor-research` skill (iTunes Search SERP overlap, no remote service).

## The data source

| # | Data source | Provides | Credential file | Client |
|---|---|---|---|---|
| 1 | **Apple App Store Connect API** | Metadata / sales & download reports / IAP & subscriptions / reviews / builds | `config/credentials.txt` + a `.p8` key in `config/` | `scripts/asc_client.py` |

> Note: **SoloMax RAG MCP and AppMate RAG API have both been removed** from this project. Growth methodology was distilled offline into the `growth-strategy` skill's static "methodology cheat-sheet"; competitor evidence now comes from the `competitor-research` skill (iTunes Search SERP overlap, run locally).

## ⚠ API key role selection (read this BEFORE generating the key)

AppMate is a **read-only** analytics tool. The App Store Connect API key it uses must NOT have any write-capable role, otherwise a buggy script or a hallucinated tool call could damage live App Store data, builds, or banking.

Two layers of defense enforce this:
1. **Setup-time:** the runtime probe in `scripts/key_safety.py` refuses to start any workflow if it detects a Developer / Finance / Admin role on the key.
2. **Runtime:** `scripts/asc_client.py` blocks every non-GET HTTP method (POST / PUT / PATCH / DELETE) unless `APPMATE_ALLOW_WRITES=1` is set — workflows never set this, so writes are physically impossible from AppMate's own code.

When creating the API key in **App Store Connect → Users and Access → Integrations → App Store Connect API**, check **ONLY** read-only roles:

| Allowed role (Apple UI label) | Why AppMate needs it |
|---|---|
| ✅ Sales / 销售 | reads `/v1/salesReports` for the daily report |
| ✅ Access to Reports / 访问报告 | broader read access (sales + analytics + finance reports) |
| ✅ Customer Support / 客户支持 | reads `/v1/customerReviews` for the feature ideation flow |
| ✅ Marketing / 营销 | reads marketing / analytics surface used by the growth flow |

**Do NOT check any of these** — they grant write access to live App Store data and AppMate will refuse to start:

| Refused role | Why it is dangerous |
|---|---|
| ❌ Admin / 管理 | full write to every ASC surface — users, billing, app data, banking |
| ❌ Developer / 开发者 | can upload builds, modify certificates / identifiers / provisioning profiles |
| ❌ App Manager / App 管理 | can modify app metadata, screenshots, pricing, in-app purchases |
| ❌ Finance / 财务 | can modify banking, tax, financial routing |

### How the probe works

`scripts/key_safety.py` runs two GETs on startup and caches the verdict in `data/key_safety.json` for 7 days:

| Probe | Status → conclusion |
|---|---|
| `GET /v1/bundleIds` | 200 → key has Developer or Admin (refuse); 403 → does not |
| `GET /v1/financeReports` | 200 / 404 → key has Finance or Admin (refuse); 403 → does not |

If you regenerate the key, delete `data/key_safety.json` to force a fresh probe.

### Known limitation — the App Manager probe gap

Apple's role permissions gate **writes**, not reads. Most GET endpoints (including `/v1/users` and `/v1/builds`) are readable by any role that has any API access at all, so they're useless as Admin / App Manager probes. The two probes above target endpoints that *are* gated at the read layer (Developer / Finance domain endpoints) — they correctly catch Developer, Finance, and Admin.

**App Manager cannot be distinguished from read-only roles through GET endpoints.** An App Manager-only key would pass the probe but could still modify app metadata. Two compensating defenses cover the gap:
- The role-selection guidance above (always-on documentation at the only point where it matters — key creation).
- The `APPMATE_ALLOW_WRITES` block in `asc_client.py`: even if an App Manager key slips through, AppMate's own scripts cannot issue a single write call.

## Config model

All secrets and account-specific constants live in a **gitignored `config/` directory**. The repo ships only `config/credentials.example.txt` and `config/README.md`. Scripts read everything through `scripts/appmate_config.py`.

### Setup steps

The user only does the two physical-world steps (generate the key in ASC, drop the `.p8` file into `config/`). Everything else — copying the template, filling in fields, running the self-check — Claude does for them.

1. **User generates the API key** with only the safe roles checked (see the "API key role selection" section above). Apple shows the `.p8` once; download it.
2. **User drops the `.p8` file into `config/`** (it is gitignored). Claude cannot do this — the file lives on the user's machine.
3. **Claude asks the user for the 4 values inline (do NOT tell them to edit `credentials.txt` themselves):**
   - `issuer_id` — UUID at the top of ASC → Users and Access → Integrations → App Store Connect API
   - `key_id` — the 10-character Key ID of the key they just generated (same page)
   - `.p8` filename — what they named the file they dropped into `config/` (e.g. `AuthKey_ABC1234567.p8`)
   - `vendor_number` — the 8-digit Vendor # in the top-left of ASC → Payments and Financial Reports

   Then Claude writes `config/credentials.txt` directly (copying `config/credentials.example.txt` first if it doesn't exist) with the four values filled in and `private_key_path = config/<their .p8 filename>`. Never instruct the user to open or edit `credentials.txt` themselves.
4. Claude installs Python dependencies: `pip install -r requirements.txt`

`appmate_config.py` resolves paths eagerly and loads credentials lazily — a missing `config/credentials.txt` will not crash imports, but any script that actually needs a credential raises a clear error pointing back here.

## App Store Connect API reference

- **Auth**: ES256 JWT, `kid = key_id`, `iss = issuer_id`, `aud = appstoreconnect-v1`, 1200s lifetime, regenerated per request.
- **Common endpoints**: `/v1/apps`, `/v1/apps/{id}/appInfos`, `/v1/apps/{id}/appStoreVersions`, `/v1/apps/{id}/customerReviews`, `/v1/salesReports` (gzipped TSV), `/v1/financeReports`.
- **Known limits**: `analyticsReportRequests` POST returns 403 unless App Analytics sharing is enabled in the ASC web UI; `perfPowerMetrics` works for iOS only.

See `docs/ASC_API_REFERENCE.md` for the full endpoint reference.

## Self-check (3 checks — all green means the plugin is ready)

Run from the plugin repo root:

```bash
# 0. Universal gate — offline credential validation + online key-role probe.
#    Exits 0 only when every required field is set, the .p8 file exists,
#    AND the API key has none of Developer / Finance / Admin (probed via
#    /v1/bundleIds and /v1/financeReports). Verdict cached for 7 days in
#    data/key_safety.json.
python3 scripts/appmate_config.py check

# 1. ASC API — should print a JWT prefix
python3 scripts/asc_client.py token | head -c 30 && echo "..."

# 2. ASC API live call — should list the account's apps
python3 -c "import sys; sys.path.insert(0,'scripts'); from asc_client import apps; print(f'{len(apps())} apps')"
```

Check 0 is the **universal gate**: every downstream workflow script (`sales_report.py`, `aso_daily.py`, `aso_optimize_v2.py`, `growth_strategy.py`, `feature_ideate.py`) calls `key_safety.require_safe_key_or_exit()` at the top of `main()`, which combines the offline credential check and the role probe. Each AppMate skill also runs this check at Step 0 before doing any other work.

If check 0 reports the key as **UNSAFE**, stop immediately: revoke the key in App Store Connect, generate a new one with only read-only roles (Sales / Access to Reports / Customer Support / Marketing), replace the `.p8` + `key_id`, delete `data/key_safety.json`, and re-run check 0. AppMate will not run a single workflow while an unsafe key is configured.

All 3 green = every downstream workflow (`sales-daily-report`, `aso-daily-report`, `aso-optimize`, `feature-ideation`, `competitor-research`, `growth-strategy`) can run.

## Config file inventory (paths relative to the plugin repo root)

| Path | Role |
|---|---|
| `config/credentials.txt` | ASC credentials + account constants (gitignored) |
| `config/AuthKey_*.p8` | ASC private key (gitignored) |
| `config/credentials.example.txt` | Shipped template |
| `data/apps_full.json` | Full metadata snapshot (generated by `scripts/fetch_full.py`) |
| `data/sales_cache.json` | Sales report cache (maintained by `scripts/sales_report.py`) |
| `data/keyword_reference_<region>.json` | Static keyword popularity / difficulty reference (shipped with the plugin) |
| `data/key_safety.json` | Cached role-probe verdict (refreshed every 7 days; delete to force a fresh probe) |
