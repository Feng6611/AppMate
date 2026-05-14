"""Thin Python client for the local Astro MCP server (tryastro.app).

Astro exposes Apple Search Ads–grade ASO data:
  - popularity (1-99 search volume index, same scale as Apple Search Ads)
  - difficulty (1-99 ranking difficulty)
  - currentRanking / previousRanking / rankingChange
  - appsCount (how many apps compete for that keyword)
  - history, statistics, competitor extraction

The MCP server uses JSON-RPC 2.0 over HTTP at http://127.0.0.1:8089/mcp.

Astro charges by tracked-keyword slots. To query popularity for arbitrary words
without permanently consuming a slot, use `lookup_popularity()` which adds the
keyword to an anchor app's tracking, captures the data, then removes it.
Results are cached on disk so the same (keyword, store) is only hit once.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import time
from typing import Any

import requests

import appmate_config

ENDPOINT = appmate_config.astro_endpoint()
_id_counter = itertools.count(1)


def _rpc(method: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": next(_id_counter),
        "method": method,
        "params": params or {},
    }
    r = requests.post(
        ENDPOINT,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body and body["error"]:
        raise RuntimeError(f"MCP error: {body['error']}")
    return body.get("result")


def _tool_call(name: str, args: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    result = _rpc("tools/call", {"name": name, "arguments": args or {}}, timeout=timeout)
    if not result:
        return None
    contents = result.get("content", [])
    for c in contents:
        if c.get("type") == "text":
            text = c["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return result


def list_tools() -> list[dict[str, Any]]:
    result = _rpc("tools/list", {})
    return result.get("tools", []) if result else []


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------
def list_apps() -> list[dict[str, Any]]:
    return _tool_call("list_apps") or []


def get_app_keywords(app_id: str | None = None, app_name: str | None = None, store: str | None = None) -> list[dict[str, Any]]:
    args: dict[str, Any] = {}
    if app_id:
        args["appId"] = app_id
    if app_name:
        args["appName"] = app_name
    if store:
        args["store"] = store
    return _tool_call("get_app_keywords", args) or []


def search_rankings(
    keyword: str,
    store: str,
    app_id: str | None = None,
    include_history: bool = False,
    include_statistics: bool = False,
    period: str | None = None,
) -> list[dict[str, Any]]:
    args: dict[str, Any] = {"keyword": keyword, "store": store}
    if app_id:
        args["appId"] = app_id
    if include_history:
        args["includeHistory"] = True
    if include_statistics:
        args["includeStatistics"] = True
    if period:
        args["period"] = period
    return _tool_call("search_rankings", args) or []


def get_keyword_suggestions(app_id: str, store: str | None = None) -> list[dict[str, Any]]:
    args: dict[str, Any] = {"appId": app_id}
    if store:
        args["store"] = store
    return _tool_call("get_keyword_suggestions", args, timeout=60) or []


def search_app_store(keyword: str, store: str, limit: int = 20) -> list[dict[str, Any]]:
    return _tool_call("search_app_store", {"keyword": keyword, "store": store, "limit": limit}) or []


def get_app_ratings(app_id: str | None = None, store: str | None = None, include_history: bool = False) -> Any:
    args: dict[str, Any] = {}
    if app_id:
        args["appId"] = app_id
    if store:
        args["store"] = store
    if include_history:
        args["includeHistory"] = True
    return _tool_call("get_app_ratings", args)


def add_keywords(app_id: str, keywords: list[str], store: str) -> Any:
    return _tool_call(
        "add_keywords",
        {"appId": app_id, "keywords": keywords, "store": store},
        timeout=120,
    )


def extract_competitors_keywords(keyword: str, store: str) -> list[dict[str, Any]]:
    return _tool_call(
        "extract_competitors_keywords",
        {"keyword": keyword, "store": store},
        timeout=120,
    ) or []


def remove_keywords(app_id: str, keywords: list[str], store: str) -> Any:
    return _tool_call(
        "remove_keywords",
        {"appId": app_id, "keywords": keywords, "store": store},
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Arbitrary-keyword popularity lookup
# ---------------------------------------------------------------------------
POP_CACHE_PATH = appmate_config.data_path("astro_popularity_cache.json")
# Use the "iPhone" placeholder app (appId=10) as anchor so transient lookups
# don't pollute real apps' tracking lists.
DEFAULT_ANCHOR_APP_ID = "10"


def _load_pop_cache() -> dict[str, Any]:
    if POP_CACHE_PATH.exists():
        return json.loads(POP_CACHE_PATH.read_text())
    return {}


def _save_pop_cache(c: dict[str, Any]) -> None:
    POP_CACHE_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2))


def lookup_popularity(
    keyword: str,
    store: str,
    anchor_app_id: str = DEFAULT_ANCHOR_APP_ID,
    use_cache: bool = True,
    cache_ttl_hours: int = 24,
) -> dict[str, Any] | None:
    """Get popularity + difficulty for any (keyword, store) pair.

    Strategy:
      1. Check on-disk cache (TTL `cache_ttl_hours`).
      2. Check if already tracked on the anchor app — if so, reuse.
      3. Otherwise: add → capture → remove → cache.

    Returns {keyword, store, popularity, difficulty, was_tracked, fetched_at}
    or None on failure.
    """
    cache_key = f"{store.lower()}|{keyword.lower()}"
    cache = _load_pop_cache() if use_cache else {}
    if cache_key in cache:
        rec = cache[cache_key]
        age = time.time() - rec.get("fetched_at", 0)
        if age < cache_ttl_hours * 3600:
            return rec

    # If already tracked under anchor, just read it
    existing = get_app_keywords(app_id=anchor_app_id, store=store)
    for rec in existing:
        if rec.get("keyword", "").lower() == keyword.lower():
            out = {
                "keyword": rec.get("keyword"),
                "store": store,
                "popularity": rec.get("popularity"),
                "difficulty": rec.get("difficulty"),
                "currentRanking": rec.get("currentRanking"),
                "appsCount": rec.get("appsCount"),
                "was_tracked": True,
                "fetched_at": time.time(),
            }
            cache[cache_key] = out
            _save_pop_cache(cache)
            return out

    # Not tracked — add transiently
    added = add_keywords(app_id=anchor_app_id, keywords=[keyword], store=store) or {}
    results = added.get("results") or []
    if not results:
        return None
    r0 = results[0]
    if not r0.get("success") or r0.get("skipped"):
        return None

    # Capture data — note: add_keywords doesn't return appsCount.
    # If we need it, immediately query get_app_keywords before remove.
    enriched: dict[str, Any] | None = None
    try:
        kws = get_app_keywords(app_id=anchor_app_id, store=store)
        for rec in kws:
            if rec.get("keyword", "").lower() == keyword.lower():
                enriched = rec
                break
    except Exception:
        pass

    out = {
        "keyword": r0.get("keyword", keyword),
        "store": store,
        "popularity": r0.get("popularity"),
        "difficulty": r0.get("difficulty"),
        "currentRanking": (enriched or {}).get("currentRanking"),
        "appsCount": (enriched or {}).get("appsCount"),
        "was_tracked": False,
        "fetched_at": time.time(),
    }

    # Remove to free the slot
    try:
        remove_keywords(anchor_app_id, [keyword], store)
    except Exception:
        pass  # best-effort; cache already populated

    cache[cache_key] = out
    _save_pop_cache(cache)
    return out


def lookup_popularity_batch(
    keywords: list[str],
    store: str,
    anchor_app_id: str = DEFAULT_ANCHOR_APP_ID,
    use_cache: bool = True,
    batch_size: int = 50,
    cache_ttl_hours: int = 24,
) -> dict[str, dict[str, Any]]:
    """Look up popularity for many keywords efficiently.

    1. Filter to ones not in cache.
    2. Of those, partition by already-tracked vs need-to-add.
    3. add_keywords accepts up to 100 in one call — batch them.
    4. Capture data, remove the just-added ones.
    """
    cache = _load_pop_cache() if use_cache else {}
    out: dict[str, dict[str, Any]] = {}
    pending: list[str] = []

    for kw in keywords:
        key = f"{store.lower()}|{kw.lower()}"
        if use_cache and key in cache:
            rec = cache[key]
            if time.time() - rec.get("fetched_at", 0) < cache_ttl_hours * 3600:
                out[kw] = rec
                continue
        pending.append(kw)

    if not pending:
        return out

    # Find already-tracked from pending
    already = {r.get("keyword", "").lower(): r for r in get_app_keywords(app_id=anchor_app_id, store=store)}
    to_add: list[str] = []
    for kw in pending:
        if kw.lower() in already:
            rec = already[kw.lower()]
            data = {
                "keyword": rec.get("keyword"),
                "store": store,
                "popularity": rec.get("popularity"),
                "difficulty": rec.get("difficulty"),
                "currentRanking": rec.get("currentRanking"),
                "appsCount": rec.get("appsCount"),
                "was_tracked": True,
                "fetched_at": time.time(),
            }
            cache[f"{store.lower()}|{kw.lower()}"] = data
            out[kw] = data
        else:
            to_add.append(kw)

    # Batch-add and capture
    for i in range(0, len(to_add), batch_size):
        chunk = to_add[i : i + batch_size]
        res = add_keywords(app_id=anchor_app_id, keywords=chunk, store=store) or {}
        results = {r.get("keyword", "").lower(): r for r in res.get("results", [])}
        # Enrich with appsCount from the just-added tracking
        try:
            tracked_now = {
                r.get("keyword", "").lower(): r
                for r in get_app_keywords(app_id=anchor_app_id, store=store)
            }
        except Exception:
            tracked_now = {}
        for kw in chunk:
            r0 = results.get(kw.lower())
            if not r0 or not r0.get("success") or r0.get("skipped"):
                continue
            enriched = tracked_now.get(kw.lower(), {})
            data = {
                "keyword": r0.get("keyword", kw),
                "store": store,
                "popularity": r0.get("popularity"),
                "difficulty": r0.get("difficulty"),
                "currentRanking": enriched.get("currentRanking"),
                "appsCount": enriched.get("appsCount"),
                "was_tracked": False,
                "fetched_at": time.time(),
            }
            cache[f"{store.lower()}|{kw.lower()}"] = data
            out[kw] = data
        # Remove the just-added batch
        if chunk:
            try:
                remove_keywords(anchor_app_id, chunk, store)
            except Exception:
                pass

    _save_pop_cache(cache)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  astro_client.py probe                       # list tools + tracked apps")
        print("  astro_client.py pop <keyword> [<store>]     # look up one keyword's popularity")
        print("  astro_client.py pop-batch <store> kw1 kw2…  # look up many at once")
        sys.exit(0)

    cmd = args[0]
    if cmd == "probe":
        print("=== tools ===")
        for t in list_tools():
            print(f"  {t['name']}")
        print()
        print("=== tracked apps ===")
        for a in list_apps():
            if a.get("keywordCount", 0) > 0:
                print(
                    f"  {a['name']} ({a['platform']}) [{','.join(a.get('stores', []))}] · "
                    f"{a['keywordCount']} keywords  appId={a['appId']}"
                )
    elif cmd == "pop":
        kw = args[1]
        store = args[2] if len(args) > 2 else "cn"
        r = lookup_popularity(kw, store)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == "pop-batch":
        store = args[1]
        kws = args[2:]
        results = lookup_popularity_batch(kws, store)
        print(f"{'keyword':<25} {'pop':>4}  {'diff':>4}  {'rank':>5}  cache?")
        print("-" * 60)
        for kw in kws:
            r = results.get(kw)
            if not r:
                print(f"{kw:<25}   ?")
                continue
            tag = "TRK" if r.get("was_tracked") else "new"
            rk = r.get("currentRanking") or "-"
            print(f"{kw:<25} {r['popularity']:>4}  {r['difficulty']:>4}  {rk!s:>5}  {tag}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(2)
