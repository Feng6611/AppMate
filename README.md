# AppMate

A **Claude Code plugin** — an App Store Connect operations toolkit for indie developers. Python data-layer scripts plus LLM-driven skills that cover **sales reporting, ASO optimization, ASO daily monitoring, feature ideation, competitor research, and growth strategy**.

Design pattern: scripts do the deterministic data work (API calls, caching, rank lookups); the LLM does everything that needs semantic judgment (Chinese tokenization, candidate generation, strategy reasoning, report rendering). Each workflow involves you only at the start and the end.

---

## Install (Claude Code)

Inside Claude Code, run:

```
/plugin marketplace add fengyiqicoder/AppMate
/plugin install appmate@appmate-marketplace
```

That's the whole install. The plugin pulls itself from GitHub, registers the seven `/appmate-*` slash commands, and loads the seven skills.

Then install the Python data-layer dependencies (App Store Connect API client uses PyJWT + cryptography):

```bash
# in the plugin repo directory that Claude Code cloned for you
pip install -r requirements.txt
```

To find that directory, run `/plugin` inside Claude Code and look at the path next to `appmate`. The default is `~/.claude/plugins/marketplaces/appmate-marketplace/plugins/appmate/`.

> **Python**: tested on 3.10+. No virtualenv required — the three dependencies are tiny.

---

## Setup (one-time, ~3 min)

Run `/appmate-setup` inside Claude Code. It walks you through the four credential fields and runs a 4-point self-check.

> ### ⚠ API key role selection — read this before generating the key
>
> AppMate is a read-only analytics tool. **The key you create must NOT have any write access to App Store Connect**, or one buggy script / hallucinated tool call could damage your live app data, builds, or banking info.
>
> When generating the key in App Store Connect → Users and Access → Integrations → App Store Connect API, **check ONLY read-only roles**:
>
> - ☑ **Sales / 销售** (read sales / downloads)
> - ☑ **Access to Reports / 访问报告** (read sales + analytics + finance reports)
> - ☑ **Customer Support / 客户支持** (read reviews)
> - ☑ **Marketing / 营销** (read analytics)
>
> **Do NOT check** any of: **Admin · Developer · App Manager · Finance**. These grant write access to live App Store data, build uploads, app metadata, or banking.
>
> AppMate enforces this in two layers:
> 1. A runtime **role probe** (`scripts/key_safety.py`) checks `GET /v1/bundleIds` and `GET /v1/financeReports`. The probe catches Developer / Finance / Admin and refuses to start any workflow with that key. **It cannot catch App Manager** — Apple's permission model gates App Manager writes but not metadata reads — so the role checkbox guidance above is the only defense against an accidental App Manager key.
> 2. A code-level **write block** in `scripts/asc_client.py`: POST/PUT/PATCH/DELETE methods refuse to fire unless `APPMATE_ALLOW_WRITES=1` is set in the environment. None of AppMate's workflows ever set this, so even an over-privileged key cannot trigger a write call from our code.

If you want to do setup by hand instead:

```bash
# from the plugin directory
cp config/credentials.example.txt config/credentials.txt
```

Then edit `config/credentials.txt` and fill in:

| Field | Where to get it |
|---|---|
| `issuer_id` | App Store Connect → Users and Access → Integrations → App Store Connect API → "Issuer ID" at the top |
| `key_id` | Same page → the Key ID column of the API key you create (with **only read-only roles** checked — see the warning above) |
| `private_key_path` | Drop the `.p8` file you downloaded when creating the API key into `config/`, then point this field at it (e.g. `config/AuthKey_XXXXXXXX.p8`) |
| `vendor_number` | App Store Connect → Payments and Financial Reports → vendor number near the top |

Run the self-check from the plugin root to confirm everything works:

```bash
# 0. Universal gate — offline credential validation + online key-role probe.
#    Returns exit 0 only when credentials are complete AND the key has no
#    write-capable App Store Connect roles. The probe result is cached for 7 days.
python3 scripts/appmate_config.py check

# 1. ASC API JWT — should print "..." after a JWT prefix
python3 scripts/asc_client.py token | head -c 30 && echo "..."

# 2. ASC API live call — should list your account's apps
python3 -c "import sys; sys.path.insert(0,'scripts'); from asc_client import apps; print(f'{len(apps())} apps')"
```

All three green = every workflow can run.

> **What's gitignored**: everything under `config/` (your credentials + .p8 key) and most of `data/` (caches + generated reports). The two static `data/keyword_reference_<region>.json` tables that ship with the plugin are the only exceptions. To keep `config/` and `data/` outside the plugin directory, set `APPMATE_HOME` to a folder you control.

---

## The 7 workflows

| Command | What it does | Typical runtime |
|---|---|---|
| `/appmate-setup` | Set up / troubleshoot credentials. Run once. | ~3 min |
| `/appmate-sales` | Sales & downloads daily report — all live apps, 5 time dimensions (yesterday / 7d / 30d / this week / this month). Auto-anchors to the last day Apple actually has data for. | ~30 s |
| `/appmate-aso-optimize <app>` | Deep ASO optimization for one app. Produces three paste-ready strings (title 30 char / subtitle 30 char / keywords 100 char) per a ten-section methodology with §-numbered rules. Outputs an OLD vs NEW table and an addition/deletion checklist with `pop / diff / rank` columns. | ~2 min |
| `/appmate-aso-daily` | Keyword-ranking daily report for your top-3 apps by 30-day downloads. LLM-tokenizes each app's title / subtitle / keywords, checks rank via iTunes Search Top-200, filters to rank ≤ 20, diffs against yesterday's snapshot. | ~1 min |
| `/appmate-feature-ideas <app>` | Prioritized feature recommendations for one app, built from raw last-90-days reviews (LLM classifies complaint / suggestion / praise on its own) + the curated rival set from `/appmate-competitors` (auto-chained on first run for an app, then cached — you get both reports out of one ask). Two sentences per idea (what + why), no jargon, no scores shown. | ~1 min (or +1 min on first run for the chained `/appmate-competitors`) |
| `/appmate-competitors <app>` | Find the top 5-10 rivals outranking one app on its own core keywords. Pure iTunes Search SERP overlap, hard-filtered by category + outrank density, LLM relevance pass on name+description. Outputs a Chinese markdown report + a stable JSON (`data/competitors_<slug>.json`) for future downstream skills to consume. | ~1 min |
| `/appmate-growth <app>` | Stage-diagnosed growth strategy (cold start / early growth / plateau / decline). 3-5 strategies, each with 4 executable steps and a measurement step. | ~1 min |

App arguments accept **App Store ID / bundle ID / SKU / fuzzy name match**.

### Concrete usage

```
/appmate-sales
/appmate-aso-optimize Sticky Note Pro
/appmate-aso-optimize com.fengyiqi.PostItnoteForMac
/appmate-aso-optimize 1482080766
/appmate-aso-daily
/appmate-feature-ideas Sticky Note Pro
/appmate-competitors Sticky Note Pro
/appmate-growth 1482080766
```

All reports are rendered as **Chinese markdown** by design (the formatting conventions are tuned for Chinese ASO and Chinese App Store reporting). The source code, commit messages, and this README are in English so any maintainer can read them.

---

## Data sources

| Source | Provides | Setup |
|---|---|---|
| **Apple App Store Connect API** | Metadata / sales & download reports / IAP & subscriptions / reviews / builds | Required — the four credentials above |
| **iTunes Search API** (public, no key) | Genre classification + per-keyword SERP rankings, consumed by `/appmate-aso-daily` and `/appmate-competitors` | None |
| **Static keyword reference** | Keyword popularity (1-99) + difficulty (1-99) + apps_count | Ships with the plugin — `data/keyword_reference_<region>.json` |

Current static reference coverage:

| Region | Keywords | Real signal |
|---|---:|---:|
| CN | 2417 | 1025 |
| US | 2093 | 1485 |

See `docs/ASC_API_REFERENCE.md` for the full endpoint reference.

---

## Repository layout

```
.claude-plugin/   plugin.json + marketplace.json — Claude Code plugin manifests
commands/         7 /appmate-* slash commands
skills/           7 skills (English process docs; aso-optimize ships
                  a 671-line methodology reference in references/)
scripts/          14 Python scripts (data layer + entry points) + appmate_config.py
config/           gitignored — credentials + .p8 keys (ships only the example + README)
data/             gitignored except for the two keyword_reference tables
docs/             ASC API reference + design specs / plans
tests/            pytest suite (159 cases, runs in <0.5s)
```

---

## Development

```bash
pip install pytest
python3 -m pytest
```

`scripts/appmate_config.py` resolves paths eagerly but loads credentials lazily — a missing `config/credentials.txt` will not crash imports or the test suite. A workflow that actually needs a credential raises a clear error pointing back to setup.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/appmate-*` commands not appearing in Claude Code | `/plugin install appmate@appmate-marketplace` did not finish; re-run it. Or check `/plugin` to confirm the plugin is enabled. |
| `ModuleNotFoundError: No module named 'jwt'` | `pip install -r requirements.txt` from the plugin directory. |
| `analytics report request returned 403` | App Analytics sharing is not enabled in your App Store Connect web UI — separate authorization step. |
| Apple sales report shows "暂无" for today | Apple's daily report lags 1-2 days; the script auto-anchors to the most recent day with data. Re-run tomorrow. |
| `fuzzy match` finds the wrong app | Pass the exact App Store ID or bundle ID instead of a name. |
| `AppMate refuses to run — the configured API key has write access` | Your API key has Developer / Finance / Admin (caught by the probe) or App Manager (caught by the docs). Revoke the key in App Store Connect, generate a new one with **only read-only roles** (Sales / Access to Reports / Customer Support / Marketing), replace the `.p8` and `key_id`, delete `data/key_safety.json`, re-run `python3 scripts/appmate_config.py check`. |
| `Could not reach App Store Connect to verify key roles` | Network error during the role probe. AppMate will not start without a successful probe — fix connectivity and retry. |

---

## License & contributing

Personal project by [@fengyiqicoder](https://github.com/fengyiqicoder). PRs welcome for new ASO tactics, additional data sources, or workflow polish. Open an issue first for anything large.
