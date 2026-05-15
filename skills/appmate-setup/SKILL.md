---
name: appmate-setup
description: Set up or troubleshoot AppMate plugin credentials and config. Use when the user wants to install, configure, or self-check AppMate, set up App Store Connect API access, or fix "config missing" errors from AppMate scripts.
---

# AppMate Setup

> Infrastructure for the whole plugin. Every other AppMate workflow depends on the credentials configured here.

## One-line summary

Install two external data-source credentials into a gitignored `config/` folder, then call them through the Python clients in `scripts/`. Keyword popularity / difficulty come from the static reference table shipped with the plugin (`data/keyword_reference_<region>.json`) — no extra setup.

## The 2 data sources

| # | Data source | Provides | Credential file | Client | Status |
|---|---|---|---|---|---|
| 1 | **Apple App Store Connect API** | Metadata / sales & download reports / IAP & subscriptions / reviews / builds | `config/credentials.txt` + a `.p8` key in `config/` | `scripts/asc_client.py` | Primary |
| 2 | **AppMate RAG API** (remote HTTPS) | App Store competitor semantic search + AppMate S score | none (public BETA) | `scripts/appmate_rag_client.py` | Optional |

> Note: **SoloMax RAG MCP has been removed** from this project. Growth methodology was distilled offline into the `growth-strategy` skill's static "methodology cheat-sheet".

## ⚠ API key role selection (read this BEFORE generating the key)

AppMate is a **read-only** analytics tool. The App Store Connect API key it uses must NOT have any write-capable role, otherwise a buggy script or a hallucinated tool call could damage live App Store data, builds, or banking. AppMate enforces this with a runtime role probe (`scripts/key_safety.py`); a key with the wrong roles will be refused on the first invocation.

When creating the API key in **App Store Connect → Users and Access → Integrations → App Store Connect API**, check **ONLY** these three role checkboxes:

| Allowed role | Why AppMate needs it | Apple's UI label |
|---|---|---|
| ✅ Sales and Reports | reads `/v1/salesReports` for the daily report | "Sales and Reports" / "销售和报告" |
| ✅ Customer Support | reads `/v1/customerReviews` for the feature ideation flow | "Customer Support" / "客户支持" |
| ✅ Marketing | reads analytics surface used by the growth flow | "Marketing" / "营销" |

**Do NOT check any of these** — they grant write access to live App Store data and AppMate will refuse to start:

| Refused role | Why it is dangerous |
|---|---|
| ❌ Admin / 管理 | full write to every ASC surface — including users, billing, app data |
| ❌ Developer / 开发者 | can upload builds, modify certificates and provisioning profiles |
| ❌ App Manager / App 管理 | can modify app metadata, screenshots, pricing, ratings |
| ❌ Finance / 财务 | can modify banking, tax, financial routing |

The runtime probe runs `GET /v1/users`, `GET /v1/builds`, and `GET /v1/financeReports` on first startup, caches the verdict in `data/key_safety.json` for 7 days, and stops every workflow if any of the four refused roles is detected. If you regenerate the key, delete the cache file to force a fresh probe.

## Config model

All secrets and account-specific constants live in a **gitignored `config/` directory**. The repo ships only `config/credentials.example.txt` and `config/README.md`. Scripts read everything through `scripts/appmate_config.py`.

### Setup steps

1. Copy the template:
   ```bash
   cp config/credentials.example.txt config/credentials.txt
   ```
2. **Generate the API key** with only the three safe roles checked (see the "API key role selection" section above). Download the `.p8` file Apple gives you — Apple does not let you re-download it later.
3. Fill in `config/credentials.txt`:
   - `issuer_id`, `key_id` — from App Store Connect → Users and Access → Integrations → App Store Connect API
   - `private_key_path` — path to your `.p8` key; drop the `.p8` file into `config/` and use a repo-relative path like `config/AuthKey_XXXXXXXX.p8`
   - `vendor_number` — from App Store Connect → Payments and Financial Reports
   - `rag_base_url` — optional; default is filled in if omitted
4. Place the `.p8` private key file inside `config/` (it is gitignored).
5. Install Python dependencies: `pip install -r requirements.txt`

`appmate_config.py` resolves paths eagerly and loads credentials lazily — a missing `config/credentials.txt` will not crash imports, but any script that actually needs a credential raises a clear error pointing back here.

## App Store Connect API reference

- **Auth**: ES256 JWT, `kid = key_id`, `iss = issuer_id`, `aud = appstoreconnect-v1`, 1200s lifetime, regenerated per request.
- **Common endpoints**: `/v1/apps`, `/v1/apps/{id}/appInfos`, `/v1/apps/{id}/appStoreVersions`, `/v1/apps/{id}/customerReviews`, `/v1/salesReports` (gzipped TSV), `/v1/financeReports`.
- **Known limits**: `analyticsReportRequests` POST returns 403 unless App Analytics sharing is enabled in the ASC web UI; `perfPowerMetrics` works for iOS only.

See `docs/ASC_API_REFERENCE.md` for the full endpoint reference.

## Self-check (4 checks — all green means the plugin is ready)

Run from the plugin repo root:

```bash
# 0. Universal gate — offline credential validation + online key-role probe.
#    Exits 0 only when every required field is set, the .p8 file exists,
#    AND the API key has none of the refused roles. The role probe hits
#    /v1/users, /v1/builds, /v1/financeReports and caches the verdict in
#    data/key_safety.json for 7 days.
python3 scripts/appmate_config.py check

# 1. ASC API — should print a JWT prefix
python3 scripts/asc_client.py token | head -c 30 && echo "..."

# 2. ASC API live call — should list the account's apps
python3 -c "import sys; sys.path.insert(0,'scripts'); from asc_client import apps; print(f'{len(apps())} apps')"

# 3. AppMate RAG — should return {"status":"ok"}
python3 scripts/appmate_rag_client.py health
```

Check 0 is the **universal gate**: every downstream workflow script (`sales_report.py`, `aso_daily.py`, `aso_optimize_v2.py`, `growth_strategy.py`, `feature_ideate.py`) calls `key_safety.require_safe_key_or_exit()` at the top of `main()`, which combines the offline credential check and the role probe. Each `/appmate-*` command also runs this check before invoking its skill.

If check 0 reports the key as **UNSAFE**, stop immediately: revoke the key in App Store Connect, generate a new one with only Sales and Reports / Customer Support / Marketing, replace the `.p8` + `key_id`, delete `data/key_safety.json`, and re-run check 0. AppMate will not run a single workflow while an unsafe key is configured.

All 4 green = every downstream workflow (`sales-daily-report`, `aso-daily-report`, `aso-optimize`, `feature-ideation`, `growth-strategy`) can run.

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
