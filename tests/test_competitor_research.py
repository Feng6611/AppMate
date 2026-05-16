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


def _stub_app(itunes_id="111", bundle_id="com.demo", name="Demo",
              primary_locale="en-US", title="Demo App", subtitle="Demo sub",
              keywords="alpha,beta,gamma") -> dict:
    return {
        "id": itunes_id,
        "core": {"name": name, "bundleId": bundle_id, "primaryLocale": primary_locale},
        "appInfo": {
            "localizations": [
                {"locale": primary_locale, "name": title, "subtitle": subtitle},
            ],
        },
        "versions": [{
            "attributes": {"createdDate": "2026-05-01T00:00:00Z", "platform": "IOS"},
            "localizations": [
                {"locale": primary_locale, "keywords": keywords,
                 "name": title, "subtitle": subtitle},
            ],
        }],
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }


def _row(app_id, country, ptid="1F", units="1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def test_build_phase_a_returns_full_schema(monkeypatch):
    import competitor_research as cr

    monkeypatch.setattr(cr, "fetch_primary_genre_id", lambda iid, c: 6007)

    app = _stub_app()
    sales_cache = {"2026-05-10": [_row("111", "US"), _row("111", "US")]}
    out = cr.build_phase_a(app, sales_cache, today=dt.date(2026, 5, 13))

    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "platform", "market",
        "primary_genre_id", "locale", "downloads_30d_in_market",
        "generated_at", "raw",
    }
    assert out["app"] == "Demo"
    assert out["app_id"] == "111"
    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "US"
    assert out["primary_genre_id"] == 6007
    assert out["locale"] == "en-US"
    assert out["downloads_30d_in_market"] == 2
    assert out["raw"]["title"] == "Demo App"
    assert out["raw"]["subtitle"] == "Demo sub"
    assert out["raw"]["keywords"] == "alpha,beta,gamma"


def test_cmd_analyze_writes_phase_a_file(monkeypatch, tmp_path):
    import competitor_research as cr

    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"
    apps_full.write_text(json.dumps({"apps": [_stub_app(name="Demo")]}))
    sales.write_text("{}")

    monkeypatch.setattr(cr, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(cr, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cr, "fetch_primary_genre_id", lambda iid, c: 6007)

    rc = cr.cmd_analyze("Demo")
    assert rc == 0

    out_path = tmp_path / "phase_a_competitors_demo_us.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["primary_genre_id"] == 6007


def test_cmd_analyze_returns_2_when_app_not_found(monkeypatch, tmp_path):
    import competitor_research as cr

    apps_full = tmp_path / "apps_full.json"
    apps_full.write_text(json.dumps({"apps": []}))
    sales = tmp_path / "sales_cache.json"
    sales.write_text("{}")
    monkeypatch.setattr(cr, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(cr, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)

    assert cr.cmd_analyze("NoSuchApp") == 2
