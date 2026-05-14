# AppMate

A **Claude Code plugin** — an App Store Connect operations toolkit for indie developers. Python data-layer scripts plus LLM-driven skills that cover sales reporting, ASO optimization, ASO daily monitoring, feature ideation, and growth strategy.

The design pattern throughout: scripts do the deterministic data work (API calls, caching, rank lookups); the LLM (Claude, via the skills) does everything that needs semantic judgment (Chinese tokenization, candidate generation, strategy reasoning, report rendering). Each workflow involves the user only at the start and the end.

## Workflows

| Command | Skill | What it does |
|---|---|---|
| `/appmate-setup` | `appmate-setup` | Set up / troubleshoot credentials and config; run the self-check |
| `/appmate-sales` | `sales-daily-report` | Sales & downloads daily report for all live apps, across 5 time dimensions |
| `/appmate-aso-optimize <app>` | `aso-optimize` | Deep ASO optimization for one app — new title / subtitle / keyword strings |
| `/appmate-aso-daily` | `aso-daily-report` | Keyword-ranking daily report for the top-3 apps by downloads |
| `/appmate-feature-ideas <app>` | `feature-ideation` | Prioritized feature recommendations from reviews + competitor evidence |
| `/appmate-growth <app>` | `growth-strategy` | Stage-diagnosed growth strategy — phase diagnosis + 3-5 actionable strategies |

## Data sources

| Source | Provides | Client |
|---|---|---|
| Apple App Store Connect API | Metadata / sales reports / IAP / reviews / builds | `scripts/asc_client.py` |
| Astro MCP (local) | Keyword popularity (1-99) + difficulty (1-99) + rank change | `scripts/astro_client.py` |
| AppMate RAG API (remote) | App Store competitor semantic search | `scripts/appmate_rag_client.py` |

See `docs/ASC_API_REFERENCE.md` and `docs/APPMATE_RAG_API.md` for details.

## Install

```bash
# add this repo as a Claude Code plugin marketplace, then enable the "appmate" plugin
claude plugin marketplace add <github-url-of-this-repo>

# install the Python dependencies (from the plugin repo root)
pip install -r requirements.txt
```

## Setup

Run `/appmate-setup` and follow it, or do it manually:

```bash
cp config/credentials.example.txt config/credentials.txt
# fill in issuer_id / key_id / private_key_path / vendor_number,
# and drop your App Store Connect .p8 key into config/
```

`config/` (secrets) and `data/` (caches + generated reports) are gitignored — nothing private ever gets committed. See `config/README.md` for the field guide. To keep `config/` and `data/` outside the plugin repo, set the `APPMATE_HOME` environment variable.

## Usage

```
/appmate-sales
/appmate-aso-optimize Sticky Note Pro
/appmate-feature-ideas com.fengyiqi.PostItnoteForMac
/appmate-growth 1482080766
```

App arguments accept App Store ID / bundle ID / SKU / fuzzy name match.

## Repository layout

```
.claude-plugin/   plugin.json + marketplace.json
skills/           6 skills (English process docs; aso-optimize ships the methodology reference)
commands/         6 /appmate-* slash commands
scripts/          17 Python scripts (data layer) + appmate_config.py
config/           gitignored — credentials + .p8 keys (ships only the example + README)
data/             gitignored — caches, snapshots, generated reports
docs/             API reference docs + superpowers specs/plans
tests/            pytest suite
```

## A note on language

Source code and all repository documentation are in **English**. The **reports the workflows generate are in Chinese by design** — the sales / ASO / feature / growth deliverables follow established Chinese formatting conventions, and the skills instruct Claude (in English) to produce that Chinese output.

## Development

```bash
pip install pytest
python3 -m pytest
```

`appmate_config.py` loads credentials lazily, so the full test suite and a fresh checkout import cleanly with no credentials present.
