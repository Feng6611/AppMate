"""Thin client for the AppMate RAG API.

Per RAG_API.md (2026-05-13), only two endpoints are exposed:
  - GET  /api/health           — liveness probe
  - POST /api/rag/search       — vector search + filters + AppMate S scoring

All other endpoints (app / reviews / itunes) have been removed (404).
"""
from __future__ import annotations

import time
from typing import Any

import requests

import appmate_config

BASE_URL = appmate_config.rag_base_url()


def _get(path: str, retries: int = 4) -> Any:
    url = f"{BASE_URL}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"GET {url} failed: {last_exc}")


def _post(path: str, body: dict[str, Any], retries: int = 4) -> Any:
    url = f"{BASE_URL}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(url, json=body, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"POST {url} failed: {last_exc}")


def health() -> dict[str, Any]:
    """Liveness probe. Returns `{"status": "ok"}` when the service is up."""
    return _get("/api/health")


def search(
    query: str,
    top_k: int = 15,
    category: str | None = None,
    region: str | None = None,
    min_rating: float | None = None,
    min_review_count: int | None = None,
    max_review_count: int | None = None,
    min_S: float | None = None,
    max_S: float | None = None,
    sort_by: str = "similarity",
    sort_order: str = "desc",
) -> list[dict[str, Any]]:
    """Semantic search across the App Store via RAG.

    Returns list of {product_id, itunes_id, name, category_slug, region,
    rank, rating, review_count, appmate_F/M/P/S, appmate_reason, description}.
    """
    filters: dict[str, Any] = {}
    if category:
        filters["category"] = category
    if region:
        filters["region"] = region
    if min_rating is not None:
        filters["min_rating"] = min_rating
    if min_review_count is not None:
        filters["min_review_count"] = min_review_count
    if max_review_count is not None:
        filters["max_review_count"] = max_review_count
    if min_S is not None:
        filters["min_S"] = min_S
    if max_S is not None:
        filters["max_S"] = max_S
    body: dict[str, Any] = {
        "query": query,
        "top_k": top_k,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    if filters:
        body["filters"] = filters
    res = _post("/api/rag/search", body)
    return res.get("results", [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  appmate_rag_client.py health")
        print("  appmate_rag_client.py search <query> [region]")
        sys.exit(0)

    cmd = args[0]
    if cmd == "health":
        print(health())
    elif cmd == "search":
        if len(args) < 2:
            print("Usage: appmate_rag_client.py search <query> [region]")
            sys.exit(2)
        q = args[1]
        region = args[2] if len(args) > 2 else None
        for r in search(q, top_k=5, region=region):
            print(
                f"  · {r['name']} ({r['itunes_id']})  region={r['region']}  "
                f"rank=#{r['rank']}  ★{r['rating']} ({r['review_count']})  "
                f"S={r.get('appmate_S')}"
            )
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(2)
