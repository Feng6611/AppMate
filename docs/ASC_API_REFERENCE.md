# App Store Connect API Reference

Reference material for the data sources AppMate calls. For the step-by-step credential setup, use the `appmate-setup` skill (or the `/appmate-setup` command) instead.

AppMate uses two external data sources, called through Python clients in `scripts/`:

| # | Data source | Provides | Client |
|---|---|---|---|
| 1 | Apple App Store Connect API | Metadata / sales & download reports / IAP & subscriptions / reviews / builds | `scripts/asc_client.py` |
| 2 | AppMate RAG API (remote HTTPS) | App Store competitor semantic search + AppMate S score | `scripts/appmate_rag_client.py` |

Keyword popularity (1-99) and difficulty (1-99) come from a static reference table shipped with the plugin (`data/keyword_reference_<region>.json`), looked up via `scripts/keyword_local.py`.

---

## 1. App Store Connect API

### Authentication (`scripts/asc_client.py`)

1. ES256 JWT:
   - header: `{alg: "ES256", kid: <key_id>, typ: "JWT"}`
   - payload: `{iss: <issuer_id>, iat: now, exp: now+1200, aud: "appstoreconnect-v1"}`
2. Every request: `Authorization: Bearer <jwt>`
3. The token lasts 1200 seconds and is regenerated per request (cheap).

Credentials are loaded lazily via `appmate_config` from `config/credentials.txt` (`issuer_id`, `key_id`, `private_key_path`, `vendor_number`).

### Common endpoints

```
GET  /v1/apps                              list all apps
GET  /v1/apps/{id}/appInfos                app metadata + localizations
GET  /v1/apps/{id}/appStoreVersions        version history + localized copy
GET  /v1/apps/{id}/inAppPurchasesV2        IAPs
GET  /v1/apps/{id}/subscriptionGroups      subscription groups
GET  /v1/apps/{id}/customerReviews         reviews
GET  /v1/apps/{id}/builds                  builds
GET  /v1/salesReports                      sales daily report (gzipped TSV)
GET  /v1/financeReports                    finance monthly report
```

### Known limits

- `analyticsReportRequests` POST → 403 unless App Analytics sharing is additionally authorized in the App Store Connect web UI.
- `perfPowerMetrics` for the macOS platform → 400 (iOS only).
- `diagnosticSignatures` returns empty for most apps (no data).

### Data files (under `data/`, gitignored)

| File | Content | Produced by |
|---|---|---|
| `apps_full.json` | Full per-app metadata (localizations / IAP / subscriptions / reviews) | `scripts/fetch_full.py` |
| `apps_metadata.json` | Lightweight version (no reviews) | `scripts/fetch_metadata.py` |
| `app_icons.json` | Icon URLs from the iTunes Lookup API | `scripts/fetch_icons.py` |
| `sales_cache.json` | Daily sales report cache (TSV rows keyed by date) | `scripts/sales_report.py` (auto-maintained) |

---

## 2. AppMate RAG API

See `docs/APPMATE_RAG_API.md` for the full endpoint and schema reference. In short:

- Base URL: `https://appmate.000ooo.ooo` (override via `rag_base_url` in `config/credentials.txt`).
- Endpoints: `GET /api/health`, `POST /api/rag/search`.
- `scripts/appmate_rag_client.py` exposes `health()` and `search(query, region=..., top_k=..., min_review_count=..., sort_by=...)`.

```python
from appmate_rag_client import search

results = search(
    query="sticky note widget",
    region="us",
    top_k=10,
    min_review_count=50,
    sort_by="S",
)
```

> ⚠️ `appmate_*` fields in the response are internal scores — do not display them directly to end users.
