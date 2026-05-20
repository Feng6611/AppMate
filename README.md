# AppMate

**Open-standard [Agent Skills](https://agentskills.io/) for App Store Connect** — a toolkit for indie developers that works in **Claude Code, Cursor, Codex, GitHub Copilot, Gemini CLI, Goose, OpenCode, and 50+ other AI coding agents**. Python data-layer scripts plus LLM-driven skills covering **sales reporting, ASO optimization, ASO daily monitoring, competitor research, feature ideation, and growth strategy**.

Design pattern: scripts do the deterministic data work (API calls, caching, rank lookups); the LLM does everything that needs semantic judgment (CJK / Latin tokenization of App Store metadata, candidate generation, strategy reasoning, report rendering). Each workflow involves you only at the start and the end.

The 7 skills are defined in standard `SKILL.md` format under `skills/` — every compatible agent finds them automatically. Same files, same Python data layer, same reports. Only the invocation syntax differs by agent.

---

## Install (any AI coding agent — recommended)

One command, works for Cursor, Codex, Copilot, Gemini CLI, Goose, OpenCode, Cline, and 40+ more:

```bash
npx skills add fengyiqicoder/AppMate
```

Then install the Python data-layer dependencies (PyJWT + cryptography + requests):

```bash
pip install -r requirements.txt
```

Trigger any skill by natural language — say **"跑日报"** / **"run my sales report"** / **"优化 ASO"** and the agent will match the request against each skill's `description` and pick the right one. No slash commands needed.

> See [skills.sh](https://www.skills.sh/) and [agentskills.io](https://agentskills.io/) for the full agent compatibility matrix.

---

## Install (Claude Code)

Two steps, run them **one at a time** inside Claude Code — wait for step 1 to finish before pasting step 2.

**Step 1** — register this repo as a plugin marketplace:

```
/plugin marketplace add fengyiqicoder/AppMate
```

Wait until Claude Code confirms the marketplace was added.

**Step 2** — install the `appmate` plugin from that marketplace:

```
/plugin install appmate@appmate-marketplace
```

That's the whole install. The plugin pulls itself from GitHub, registers the seven `/appmate-*` slash commands, and loads the seven skills.

Then install the Python data-layer dependencies (App Store Connect API client uses PyJWT + cryptography + requests):

```bash
# in the plugin repo directory that Claude Code cloned for you
pip install -r requirements.txt
```

To find that directory, run `/plugin` inside Claude Code and look at the path next to `appmate`. The default is `~/.claude/plugins/marketplaces/appmate-marketplace/plugins/appmate/`.

> **Python**: tested on 3.10+. No virtualenv required — the three dependencies are tiny.

---

## Install (Codex CLI)

Two steps, run them **one at a time** inside Codex CLI — wait for step 1 to finish before running step 2.

**Step 1** — register this repo as a plugin marketplace:

```
codex plugin marketplace add fengyiqicoder/appmate
```

Wait until Codex confirms the marketplace was added.

**Step 2** — install the `appmate` plugin from that marketplace:

```
codex plugin install appmate
```

Codex pulls the repo, reads `.codex-plugin/plugin.json`, and registers all seven skills. There are no slash commands on Codex — Codex deprecated custom prompts in favor of skills. Invoke a skill either explicitly (`$sales-daily-report`, `$aso-optimize Sticky Note Pro`) or by asking in natural language ("跑下今天的销量日报", "帮我优化 Sticky Note Pro 的 ASO") — Codex matches against each skill's `description` frontmatter to route the request.

Install the Python data-layer dependencies the same way:

```bash
# in the plugin repo directory Codex cloned for you, default ~/.codex/plugins/appmate/
pip install -r requirements.txt
```

The repo also ships an `AGENTS.md` at the root, so running `codex` inside a clone of the repo (without going through the marketplace) also works — Codex auto-loads the agent context and finds skills under `skills/`.

### What's different vs Claude Code

| Aspect | Claude Code | Codex CLI |
|---|---|---|
| Invocation | `/appmate-sales`, `/appmate-aso-optimize Sticky Note Pro` | `$sales-daily-report`, `$aso-optimize Sticky Note Pro`, or natural language |
| Skills | `skills/` (7 SKILL.md, same files) | `skills/` (7 SKILL.md, same files) |
| Credentials gate | Inline in each skill's Step 0 | Inline in each skill's Step 0 (same) |
| Reports | Identical | Identical |
| Setup walkthrough | `/appmate-setup` | `$appmate-setup` or "set up AppMate" |

Wherever a `SKILL.md` says "run `/appmate-setup`", on Codex that means "invoke the `appmate-setup` skill" — same workflow, different invocation syntax.

---

## Staying up to date

**Claude Code:** AppMate ships a `SessionStart` hook (`hooks/hooks.json` → `scripts/check_for_update.py`) that runs once at the start of each Claude Code session. It compares your installed commit against the latest commit on `master` at [github.com/fengyiqicoder/AppMate](https://github.com/fengyiqicoder/AppMate) and, when you're behind, surfaces a one-line banner that points you at `/plugin` to upgrade. The check is cached for 24 h in `${CLAUDE_PLUGIN_DATA}/update_check.json`, network failures are silent, and the hook never blocks the session.

Force a fresh check (ignore cache) for debugging:

```bash
python3 scripts/check_for_update.py check
```

To pull the new version, open `/plugin` in Claude Code and update `appmate` from the marketplace listing — that re-clones the latest `master` into `~/.claude/plugins/marketplaces/appmate-marketplace/`.

**Codex CLI:** no auto-check (Codex plugins don't expose a session-start hook). Run `codex plugin update appmate` when you want the latest version, or watch the [Releases page](https://github.com/fengyiqicoder/appmate/releases).

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
| `/appmate-competitors <app>` | Find the top 5-10 rivals outranking one app on its own core keywords. Pure iTunes Search SERP overlap, hard-filtered by category + outrank density, LLM relevance pass on name+description. Outputs a markdown report (in the user's conversation language) + a stable JSON (`data/competitors_<slug>.json`) for future downstream skills to consume. | ~1 min |
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

### Output language

Reports are **rendered in the same language the user has been using in this conversation** (English by default; Claude switches automatically if the user has been writing in Chinese, Japanese, Spanish, etc.). The source code, commit messages, this README, and the Python scripts' raw template strings are all in English; Claude translates the headers / labels / prose on the fly when pasting the final report back.

App Store metadata strings (proposed title / subtitle / keywords from `/appmate-aso-optimize`, competitor app names, the keyword tokens themselves) stay in the **target App Store's locale** — e.g. zh-Hans strings for the CN store remain zh-Hans regardless of the conversation language. Only the surrounding explanation, table headers, and verdict labels follow the user.

Apple sales report dates lag 1-2 days — every workflow auto-anchors to the most recent day with data.

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
.codex-plugin/    plugin.json — Codex CLI plugin manifest (points at the same skills/)
AGENTS.md         project context auto-loaded by Codex (and other AGENTS.md-aware agents)
commands/         7 /appmate-* slash commands (Claude Code only — Codex uses skills directly)
skills/           7 skills (English process docs; aso-optimize ships
                  a 671-line methodology reference in references/) — shared by both CLIs
scripts/          16 Python scripts (data layer + entry points) + appmate_config.py
                  + check_for_update.py (SessionStart auto-update notifier)
hooks/            hooks.json — wires check_for_update.py into Claude Code's SessionStart
config/           gitignored — credentials + .p8 keys (ships only the example + README)
data/             gitignored except for the two keyword_reference tables
docs/             ASC API reference + design specs / plans
tests/            pytest suite (175 cases, runs in <0.5s)
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
| `/appmate-*` commands not appearing in Claude Code | Install didn't finish. Re-run the two steps from "Install (Claude Code)" above one at a time: first `/plugin marketplace add fengyiqicoder/AppMate`, wait for the confirmation, then `/plugin install appmate@appmate-marketplace`. Or check `/plugin` to confirm the plugin is enabled. |
| `$<skill>` not matched / skills not loading in Codex | Install didn't finish. Re-run the two steps from "Install (Codex CLI)" above one at a time: first `codex plugin marketplace add fengyiqicoder/appmate`, wait for the confirmation, then `codex plugin install appmate`. Or check that `~/.codex/plugins/appmate/.codex-plugin/plugin.json` exists. Try `$skills` (or `/skills`) inside Codex to confirm the seven appmate skills are listed. |
| `ModuleNotFoundError: No module named 'jwt'` | `pip install -r requirements.txt` from the plugin directory. |
| `analytics report request returned 403` | App Analytics sharing is not enabled in your App Store Connect web UI — separate authorization step. |
| Apple sales report shows "N/A" / "no data" for today | Apple's daily report lags 1-2 days; the script auto-anchors to the most recent day with data. Re-run tomorrow. |
| `fuzzy match` finds the wrong app | Pass the exact App Store ID or bundle ID instead of a name. |
| `AppMate refuses to run — the configured API key has write access` | Your API key has Developer / Finance / Admin (caught by the probe) or App Manager (caught by the docs). Revoke the key in App Store Connect, generate a new one with **only read-only roles** (Sales / Access to Reports / Customer Support / Marketing), replace the `.p8` and `key_id`, delete `data/key_safety.json`, re-run `python3 scripts/appmate_config.py check`. |
| `Could not reach App Store Connect to verify key roles` | Network error during the role probe. AppMate will not start without a successful probe — fix connectivity and retry. |
| Update-available banner doesn't show up even though `master` has new commits | The verdict is cached for 24 h. Delete `${CLAUDE_PLUGIN_DATA}/update_check.json` (or `data/update_check.json` if `CLAUDE_PLUGIN_DATA` is not set) and start a new Claude Code session, or run `python3 scripts/check_for_update.py check` to force a fresh check. |

---

## License & contributing

Personal project by [@fengyiqicoder](https://github.com/fengyiqicoder). PRs welcome for new ASO tactics, additional data sources, or workflow polish. Open an issue first for anything large.
