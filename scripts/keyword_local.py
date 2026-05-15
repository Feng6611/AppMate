"""Local pop/diff lookup backed by the static indie keyword reference.

`lookup_popularity_batch(keywords, store) -> dict[str, dict]` returns a record
per keyword with the standard shape consumers expect:

    {keyword, store, popularity, difficulty, currentRanking, appsCount,
     popularity_is_floor, was_tracked, fetched_at}

Lookup strategy per keyword:
  1. Exact match (case-insensitive) against `data/keyword_reference_<store>.json`
     → return the stored popularity / difficulty / apps_count.
  2. Substring relation against any reference row:
       - kw is a long-tail extension of a row (row ⊂ kw)
         → inherit row's diff, popularity * 0.7 (long-tail discount).
       - kw is a broader query of a row (kw ⊂ row)
         → inherit row's diff, popularity * 1.1 (broader heat).
       - When several rows match, take the one with the highest popularity.
  3. No match → low-signal default (popularity 10, difficulty 50, floor=True).

Stores not covered by any reference file (anything other than 'cn' / 'us')
fall straight through to the default estimate.
"""
from __future__ import annotations

import json
import time
from typing import Any

import appmate_config

POP_FLOOR_THRESHOLD = 10
DEFAULT_POP = 10
DEFAULT_DIFF = 50

_TABLES: dict[str, list[dict[str, Any]]] = {}


def _load_table(store: str) -> list[dict[str, Any]]:
    key = store.lower()
    if key in _TABLES:
        return _TABLES[key]
    path = appmate_config.data_path(f"keyword_reference_{key}.json")
    if not path.exists():
        _TABLES[key] = []
        return _TABLES[key]
    payload = json.loads(path.read_text())
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    _TABLES[key] = rows
    return rows


def _shape(
    keyword: str,
    store: str,
    popularity: int,
    difficulty: int,
    apps_count: int | None,
    is_floor: bool,
) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "store": store,
        "popularity": popularity,
        "difficulty": difficulty,
        "currentRanking": None,
        "appsCount": apps_count,
        "popularity_is_floor": is_floor,
        "was_tracked": False,
        "fetched_at": time.time(),
    }


def _estimate(keyword: str, store: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    kw_lower = keyword.lower().strip()
    if not kw_lower:
        return _shape(keyword, store, DEFAULT_POP, DEFAULT_DIFF, None, True)

    # 1. Exact match
    for r in rows:
        if (r.get("keyword") or "").lower() == kw_lower:
            pop = int(r.get("popularity") or DEFAULT_POP)
            return _shape(
                keyword,
                store,
                pop,
                int(r.get("difficulty") or DEFAULT_DIFF),
                r.get("apps_count"),
                bool(r.get("popularity_is_floor")) or pop <= POP_FLOOR_THRESHOLD,
            )

    # 2. Substring relation
    contained: list[dict[str, Any]] = []  # row ⊂ kw
    containing: list[dict[str, Any]] = []  # kw ⊂ row
    for r in rows:
        rk = (r.get("keyword") or "").lower()
        if not rk:
            continue
        if rk == kw_lower:
            continue
        if rk in kw_lower:
            contained.append(r)
        elif kw_lower in rk:
            containing.append(r)

    if contained:
        best = max(contained, key=lambda r: r.get("popularity") or 0)
        base_pop = int(best.get("popularity") or DEFAULT_POP)
        est_pop = max(int(base_pop * 0.7), 5)
        return _shape(
            keyword,
            store,
            est_pop,
            int(best.get("difficulty") or DEFAULT_DIFF),
            best.get("apps_count"),
            est_pop <= POP_FLOOR_THRESHOLD,
        )

    if containing:
        best = max(containing, key=lambda r: r.get("popularity") or 0)
        base_pop = int(best.get("popularity") or DEFAULT_POP)
        est_pop = min(int(base_pop * 1.1), 99)
        return _shape(
            keyword,
            store,
            est_pop,
            int(best.get("difficulty") or DEFAULT_DIFF),
            best.get("apps_count"),
            est_pop <= POP_FLOOR_THRESHOLD,
        )

    # 3. No relation → default low-signal
    return _shape(keyword, store, DEFAULT_POP, DEFAULT_DIFF, None, True)


def lookup_popularity_batch(
    keywords: list[str],
    store: str,
    **_: Any,
) -> dict[str, dict[str, Any]]:
    """Look up popularity / difficulty for many keywords from the local table.

    Extra kwargs (anchor_app_id / use_cache / batch_size / cache_ttl_hours /
    add_timeout) are accepted and ignored — kept for call-site compatibility
    with prior network clients.
    """
    rows = _load_table(store)
    out: dict[str, dict[str, Any]] = {}
    for kw in keywords:
        if not kw:
            continue
        out[kw] = _estimate(kw, store, rows)
    return out


def lookup_popularity(keyword: str, store: str, **_: Any) -> dict[str, Any]:
    """Single-keyword convenience wrapper."""
    rows = _load_table(store)
    return _estimate(keyword, store, rows)
