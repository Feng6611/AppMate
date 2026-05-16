"""Tests for competitor_research."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))


def test_module_imports():
    import competitor_research  # noqa: F401


def test_constants_match_spec():
    import competitor_research as cr
    assert cr.SERP_LIMIT == 200
    assert cr.MIN_OUTRANK_COUNT == 3
    assert cr.MAX_CANDIDATES_BEFORE_LLM == 25
    assert cr.DESCRIPTION_TRUNCATE == 200
    assert cr.TOP_N_RIVALS == 10
    assert cr.MIN_RIVALS_FOR_REPORT == 3
    assert cr.TOP_K_KEYWORDS_PER_CARD == 3
    assert cr.SELF_NORANK_CEILING == 200


def test_fetch_primary_genre_id_hits_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    cache_path.write_text(json.dumps({
        "1482080766|us": {"primaryGenreId": 6007, "fetched_at": "2026-05-16T00:00:00Z"}
    }))
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    def fail_get(*args, **kwargs):
        raise AssertionError("should not call network when cached")
    monkeypatch.setattr(cr.requests, "get", fail_get)

    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007


def test_fetch_primary_genre_id_calls_lookup_and_caches(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    class FakeResp:
        status_code = 200
        ok = True
        def json(self):
            return {"resultCount": 1, "results": [{"primaryGenreId": 6007}]}
        def raise_for_status(self):
            pass

    calls = []
    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResp()
    monkeypatch.setattr(cr.requests, "get", fake_get)

    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007
    assert len(calls) == 1
    assert "lookup" in calls[0][0]
    assert calls[0][1] == {"id": "1482080766", "country": "US"}

    # Second call hits cache, not network
    calls.clear()
    assert cr.fetch_primary_genre_id("1482080766", "US") == 6007
    assert calls == []

    # Persisted to disk
    on_disk = json.loads(cache_path.read_text())
    assert on_disk["1482080766|us"]["primaryGenreId"] == 6007


def test_fetch_primary_genre_id_raises_when_lookup_empty(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "itunes_lookup_cache.json"
    monkeypatch.setattr(cr, "ITUNES_LOOKUP_CACHE_PATH", cache_path)

    class FakeResp:
        status_code = 200
        ok = True
        def json(self):
            return {"resultCount": 0, "results": []}
        def raise_for_status(self):
            pass

    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: FakeResp())

    import pytest
    with pytest.raises(RuntimeError, match="iTunes Lookup returned no result"):
        cr.fetch_primary_genre_id("9999999999", "US")
