# AppMate `config/` directory

Everything in this folder is **gitignored** except `credentials.example.txt` and this `README.md`. Real credentials and private keys never leave your machine.

## Setup

1. Copy the template:
   ```bash
   cp config/credentials.example.txt config/credentials.txt
   ```
2. Fill in `config/credentials.txt` (see the field guide below).
3. Drop your App Store Connect `.p8` private key file into this `config/` folder.
4. From the plugin repo root, install dependencies: `pip install -r requirements.txt`
5. Run the self-check (the `/appmate-setup` command, or the commands in the `appmate-setup` skill).

## Field guide

| Field | Required | Where to get it |
|---|---|---|
| `issuer_id` | yes | App Store Connect → Users and Access → Integrations → App Store Connect API → the "Issuer ID" at the top of the page |
| `key_id` | yes | App Store Connect → same page → the Key ID column for the API key you generate |
| `private_key_path` | yes | Download the `.p8` key when you generate the API key (it can only be downloaded once). Put the file in `config/` and point this at it. A repo-relative path like `config/AuthKey_XXXXXXXX.p8` is resolved against the plugin root; an absolute path also works. |
| `vendor_number` | yes | App Store Connect → Payments and Financial Reports → the vendor number shown near the top |
| `rag_base_url` | no | Defaults to `https://appmate.000ooo.ooo` (the public AppMate RAG BETA). Only set this to override. |

## Notes

- `appmate_config.py` loads this file lazily: a missing `credentials.txt` will not crash imports or the test suite. A workflow that actually needs a credential raises a clear error pointing back here.
- To keep `data/` and `config/` somewhere other than the plugin repo (e.g. when AppMate is installed as a plugin), set the `APPMATE_HOME` environment variable to that directory.
