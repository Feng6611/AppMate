"""Tests for astro_client — popularity_is_floor flag + timeout recovery."""
from __future__ import annotations

import json

import pytest
import requests

import astro_client


def test_shape_record_marks_floor_at_5():
    rec = {"keyword": "节油", "popularity": 5, "difficulty": 11, "appsCount": 190}
    out = astro_client._shape_record(rec, "cn", was_tracked=False)
    assert out["popularity"] == 5
    assert out["popularity_is_floor"] is True
    assert out["difficulty"] == 11
    assert out["appsCount"] == 190


def test_shape_record_marks_floor_below_5():
    rec = {"keyword": "x", "popularity": 1, "difficulty": 10, "appsCount": 100}
    assert astro_client._shape_record(rec, "cn", was_tracked=False)["popularity_is_floor"] is True


def test_shape_record_does_not_mark_floor_above_5():
    rec = {"keyword": "倒数日", "popularity": 83, "difficulty": 76, "appsCount": 213}
    out = astro_client._shape_record(rec, "cn", was_tracked=False)
    assert out["popularity_is_floor"] is False


def test_shape_record_handles_none_popularity():
    rec = {"keyword": "x", "popularity": None, "difficulty": None}
    out = astro_client._shape_record(rec, "cn", was_tracked=False)
    assert out["popularity_is_floor"] is False


def test_batch_recovers_when_add_keywords_times_out(monkeypatch, tmp_path):
    """ReadTimeout from add_keywords must not lose data — server-side state
    is harvested via the tracked_now query."""
    monkeypatch.setattr(astro_client, "POP_CACHE_PATH", tmp_path / "cache.json")

    def fake_get_app_keywords(app_id, store):
        if not getattr(fake_get_app_keywords, "called", False):
            # First call: returns nothing tracked yet (initial check)
            fake_get_app_keywords.called = True
            return []
        # Second call (after timeout): Astro processed the chunk server-side
        return [
            {"keyword": "便签", "popularity": 48, "difficulty": 68, "appsCount": 216},
            {"keyword": "笔记", "popularity": 69, "difficulty": 80, "appsCount": 231},
        ]

    def fake_add_keywords(app_id, keywords, store, timeout=300):
        raise requests.exceptions.ReadTimeout("simulated read timeout")

    remove_calls = []
    def fake_remove_keywords(app_id, keywords, store):
        remove_calls.append(list(keywords))
        return {"ok": True}

    monkeypatch.setattr(astro_client, "get_app_keywords", fake_get_app_keywords)
    monkeypatch.setattr(astro_client, "add_keywords", fake_add_keywords)
    monkeypatch.setattr(astro_client, "remove_keywords", fake_remove_keywords)

    out = astro_client.lookup_popularity_batch(
        ["便签", "笔记"], store="cn", use_cache=False, batch_size=10
    )
    assert set(out.keys()) == {"便签", "笔记"}
    assert out["便签"]["popularity"] == 48
    assert out["笔记"]["popularity"] == 69
    assert out["便签"]["popularity_is_floor"] is False
    # Cleanup must still run even on timeout
    assert remove_calls == [["便签", "笔记"]]


def test_batch_uses_already_tracked_without_adding(monkeypatch, tmp_path):
    """If anchor already tracks a keyword, skip add/remove entirely."""
    monkeypatch.setattr(astro_client, "POP_CACHE_PATH", tmp_path / "cache.json")

    def fake_get_app_keywords(app_id, store):
        return [{"keyword": "小红书", "popularity": 96, "difficulty": 92, "appsCount": 233}]

    add_calls = []
    def fake_add_keywords(app_id, keywords, store, timeout=300):
        add_calls.append(list(keywords))
        return {"results": []}

    remove_calls = []
    def fake_remove_keywords(app_id, keywords, store):
        remove_calls.append(list(keywords))

    monkeypatch.setattr(astro_client, "get_app_keywords", fake_get_app_keywords)
    monkeypatch.setattr(astro_client, "add_keywords", fake_add_keywords)
    monkeypatch.setattr(astro_client, "remove_keywords", fake_remove_keywords)

    out = astro_client.lookup_popularity_batch(["小红书"], store="cn", use_cache=False)
    assert out["小红书"]["popularity"] == 96
    assert out["小红书"]["was_tracked"] is True
    # No add or remove for already-tracked keyword
    assert add_calls == []
    assert remove_calls == []


def test_batch_hits_cache(monkeypatch, tmp_path):
    """Cached fresh entries must short-circuit before any RPC."""
    cache_path = tmp_path / "cache.json"
    import time
    cache_path.write_text(json.dumps({
        "cn|倒数日": {
            "keyword": "倒数日", "store": "cn", "popularity": 83, "difficulty": 76,
            "appsCount": 213, "popularity_is_floor": False, "was_tracked": False,
            "fetched_at": time.time(),
        }
    }))
    monkeypatch.setattr(astro_client, "POP_CACHE_PATH", cache_path)

    def boom(*a, **kw):
        raise AssertionError("RPC should not be called on cache hit")

    monkeypatch.setattr(astro_client, "get_app_keywords", boom)
    monkeypatch.setattr(astro_client, "add_keywords", boom)

    out = astro_client.lookup_popularity_batch(["倒数日"], store="cn")
    assert out["倒数日"]["popularity"] == 83


def test_batch_chunks_into_batch_size(monkeypatch, tmp_path):
    """10 keywords with batch_size=3 must produce 4 add_keywords calls."""
    monkeypatch.setattr(astro_client, "POP_CACHE_PATH", tmp_path / "cache.json")

    def fake_get_app_keywords(app_id, store):
        return []

    add_calls = []
    def fake_add_keywords(app_id, keywords, store, timeout=300):
        add_calls.append(list(keywords))
        return {"results": [
            {"keyword": k, "success": True, "popularity": 30, "difficulty": 50}
            for k in keywords
        ]}

    monkeypatch.setattr(astro_client, "get_app_keywords", fake_get_app_keywords)
    monkeypatch.setattr(astro_client, "add_keywords", fake_add_keywords)
    monkeypatch.setattr(astro_client, "remove_keywords", lambda *a, **kw: None)

    kws = [f"kw{i}" for i in range(10)]
    out = astro_client.lookup_popularity_batch(kws, store="cn", use_cache=False, batch_size=3)
    assert len(out) == 10
    assert [len(c) for c in add_calls] == [3, 3, 3, 1]
