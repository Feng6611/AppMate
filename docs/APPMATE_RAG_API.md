# AppMate RAG API Reference

A public RAG retrieval API that gives external consumers (such as the AppMate plugin) semantic search over App Store data.

- **Base URL (production)**: `https://appmate.000ooo.ooo`
- **Base URL (local dev)**: `http://127.0.0.1:8001`
- **Service process**: `backend/main.py` (FastAPI + Uvicorn, listening on `127.0.0.1:8001`), reverse-proxied by nginx at `appmate.000ooo.ooo` from `/api/*` to port 8001.
- **OpenAPI**: `GET /openapi.json` (mounted on both base URLs).

The AppMate plugin calls this API through `scripts/appmate_rag_client.py`. The base URL is read from `config/credentials.txt` (`rag_base_url`, optional — defaults to the production URL).

---

## Endpoints

Only two public endpoints remain; all others have been retired (return 404).

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| POST | `/api/rag/search` | Semantic competitor search (vector retrieval + filters + AppMate S scoring) |

---

## Authentication

The `Authorization` header on `/api/rag/search` is **optional** (BETA phase).

| Case | Behavior |
|---|---|
| No `Authorization` header | Passed through directly |
| `Authorization: Bearer ampk_xxx` | Registered key: passed through, call count incremented |
| `Authorization: Bearer ampk_anon_xxx` | Anonymous key: row auto-created, count incremented |
| Unknown / malformed token | Silently ignored, still passed through |

> Currently `ENFORCE_LIMITS = False`, so quotas do not take effect. When later enabled, `monthly_limit` will act as the monthly cap.

`/api/health` does no authentication.

---

## 1. GET `/api/health`

Liveness probe.

**Response 200:**
```json
{ "status": "ok" }
```

**cURL:**
```bash
curl https://appmate.000ooo.ooo/api/health      # production
curl http://127.0.0.1:8001/api/health           # local
```

---

## 2. POST `/api/rag/search`

Vector retrieval by natural-language query, with filtering and sorting by category / region / rating / review count / internal AppMate S score.

**Request body:**
```json
{
  "query": "meditation app",
  "top_k": 15,
  "filters": {
    "category": "health-and-fitness",
    "region": "us",
    "min_S": 50,
    "max_S": 90,
    "min_rating": 4.0,
    "min_review_count": 100,
    "max_review_count": 300000
  },
  "sort_by": "similarity",
  "sort_order": "desc"
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Natural-language search term, length 1-2000 |
| `top_k` | int | no | 15 | 1-50 |
| `filters.category` | string | no | — | Category slug, e.g. `health-and-fitness` |
| `filters.region` | string | no | — | Country/region code, e.g. `us`, `cn` |
| `filters.min_S` / `max_S` | float | no | — | Internal AppMate S score bounds (0-100) |
| `filters.min_rating` | float | no | — | Minimum App Store average rating |
| `filters.min_review_count` / `max_review_count` | int | no | — | Review count bounds |
| `sort_by` | enum | no | `similarity` | `similarity` \| `S` \| `rating` \| `review_count` \| `rank` |
| `sort_order` | enum | no | `desc` | `desc` \| `asc` |

**Response 200:**
```json
{
  "results": [
    {
      "product_id": "5996573",
      "itunes_id": "337472899",
      "name": "Insight Timer: Meditate, Sleep",
      "category_slug": "health-and-fitness",
      "region": "us",
      "rank": 90,
      "rating": 4.9,
      "review_count": 863,
      "appmate_F": 25,
      "appmate_M": 75,
      "appmate_P": 65,
      "appmate_S": 55.0,
      "appmate_reason": "...",
      "description": "..."
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `product_id` | string | Internal Appfigures product ID (DB primary key) |
| `itunes_id` | string | Apple iTunes Track ID — used to build `apps.apple.com` links |
| `name` | string | App name |
| `category_slug` | string | Primary-chart category slug |
| `region` | string | Primary-chart region code (lowercase) |
| `rank` | int | Current primary-chart rank |
| `rating` | float | Average rating |
| `review_count` | int | Review count |
| `appmate_F` / `M` / `P` | int | Internal three sub-scores (Feasibility / Market / Profitability) |
| `appmate_S` | float | Internal composite score |
| `appmate_reason` | string | Internal scoring note |
| `description` | string | Full app description |

> ⚠️ `appmate_*` are internal scores — do not display them directly to end users.

**cURL:**
```bash
curl -X POST https://appmate.000ooo.ooo/api/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"meditation app","top_k":2}'

curl -X POST https://appmate.000ooo.ooo/api/rag/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query":"habit tracker",
    "top_k":10,
    "filters":{"region":"us","min_rating":4.5,"min_review_count":500},
    "sort_by":"S",
    "sort_order":"desc"
  }'
```

---

## Common errors

| Code | Meaning |
|---|---|
| 200 | Success |
| 404 | Unregistered path (all other endpoints retired) |
| 422 | Request body / parameter schema validation failed (FastAPI standard `HTTPValidationError`) |
| 500 | Uncaught backend exception |
