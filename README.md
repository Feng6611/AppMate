# AppMate

Fork-local App Store Connect operations toolkit for `dev_kkuk`.

This fork keeps the core AppMate design:

- `scripts/`: deterministic data work, including App Store Connect calls, caching, iTunes Search rank checks, keyword reference lookup and report artifacts.
- `skills/`: agent-facing workflows and judgment rules.
- `data/keyword_reference_*`: static keyword reference tables.
- `tests/`: regression tests for the Python data layer.

It intentionally drops the parts that were specific to Claude distribution or the upstream maintainer's development history:

- Claude plugin manifests and slash-command wrappers.
- Session-start update hook and upstream-repo update checker.
- Historical `docs/superpowers/` implementation plans with personal paths and obsolete design notes.

This fork keeps a minimal `.codex-plugin/plugin.json` so Codex can discover the
local skills. It does not restore Claude hooks, commands, or self-update code.

## Workflows

| Skill | Purpose |
| --- | --- |
| `appmate-setup` | One-time App Store Connect credential setup and self-check. |
| `sales-daily-report` | Sales and downloads daily report across live apps. |
| `aso-optimize` | Deep ASO rewrite for one app: title, subtitle, keyword field. |
| `aso-daily-report` | Keyword-rank monitor for top apps. |
| `competitor-research` | SERP-based competitor research for one app. |
| `feature-ideation` | Feature ideas from reviews and competitor evidence. |
| `growth-strategy` | Stage-diagnosed growth plan. |

## Setup

Install Python dependencies from this directory:

```bash
pip install -r requirements.txt
```

Keep credentials and generated caches outside the source tree when running inside `dev_kkuk`:

```bash
export APPMATE_HOME=/Users/chen/Ob/dev_kkuk/.local/appmate
mkdir -p "$APPMATE_HOME/config" "$APPMATE_HOME/data"
```

Then create `$APPMATE_HOME/config/credentials.txt` using `config/credentials.example.txt` as the template and put the `.p8` key in `$APPMATE_HOME/config/`.

Required fields:

| Field | Meaning |
| --- | --- |
| `issuer_id` | App Store Connect API issuer ID. |
| `key_id` | Read-only App Store Connect API key ID. |
| `private_key_path` | Path to the `.p8` key, relative to `APPMATE_HOME` or absolute. |
| `vendor_number` | App Store Connect vendor number for sales reports. |

Use a read-only App Store Connect key only. Do not grant Admin, Developer, App Manager or Finance.

Run the gate before any workflow:

```bash
python3 scripts/appmate_config.py check
```

The check validates local credentials and runs the key-safety probe. Workflows should stop if this fails.

## Running From This Clone

Pass exact App Store IDs or bundle IDs when possible:

```bash
python3 scripts/aso_optimize_v2.py analyze 6757333924
python3 scripts/competitor_research.py analyze 6768068044
python3 scripts/sales_report.py
```

Some workflows require an agent to read the intermediate JSON, do semantic tokenization or judgment, then call the next script step. The authoritative instructions are the matching `skills/<name>/SKILL.md` file.

## Data Policy

- `config/` is for examples only in git. Real credentials stay outside the repo via `APPMATE_HOME`.
- Generated reports, caches and snapshots stay under `APPMATE_HOME/data` unless a workflow intentionally exports a final report into `sale/aso/reports/`.
- The code must remain read-only against App Store Connect. Do not set `APPMATE_ALLOW_WRITES=1`.

## Development

```bash
python3 -m pytest
```

Keep this fork focused on reusable Mac App Store growth workflows for `dev_kkuk`: ASO, sales, competitors, reviews and growth strategy.
