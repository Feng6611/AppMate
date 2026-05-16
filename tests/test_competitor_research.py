"""Tests for competitor_research."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import statistics
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


def _fake_serp_response(entries):
    """entries: list of (track_id, bundle_id, name, genre_id, rating, count, desc)"""
    class FakeResp:
        status_code = 200
        ok = True
        def __init__(self, results):
            self._results = results
        def json(self):
            return {"resultCount": len(self._results), "results": self._results}
        def raise_for_status(self):
            pass
    results = []
    for tid, bid, name, gid, rating, rcount, desc in entries:
        results.append({
            "trackId": tid, "bundleId": bid, "trackName": name,
            "primaryGenreId": gid, "averageUserRating": rating,
            "userRatingCount": rcount, "description": desc,
        })
    return FakeResp(results)


def test_rank_keyword_with_details_parses_serp(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: _fake_serp_response([
        (100, "com.a", "App A", 6007, 4.5, 1000, "desc A here"),
        (101, "com.b", "App B", 6007, 4.7, 5000, "desc B here"),
    ]))

    out = cr.rank_keyword_with_details("便签", country="CN", entity="software")
    assert len(out) == 2
    assert out[0] == {
        "itunes_id": "100", "bundle_id": "com.a", "name": "App A",
        "primary_genre_id": 6007, "rating": 4.5, "review_count": 1000,
        "description": "desc A here", "rank_in_serp": 1,
    }
    assert out[1]["rank_in_serp"] == 2


def test_rank_keyword_with_details_uses_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    cache_path.write_text(json.dumps({
        "software|cn|便签": {
            "fetched_at": "2026-05-16T00:00:00Z",
            "entries": [{
                "itunes_id": "100", "bundle_id": "com.a", "name": "App A",
                "primary_genre_id": 6007, "rating": 4.5, "review_count": 1000,
                "description": "desc", "rank_in_serp": 1,
            }],
        },
    }))
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)

    def fail_get(*a, **kw):
        raise AssertionError("must not call network when cached")
    monkeypatch.setattr(cr.requests, "get", fail_get)

    out = cr.rank_keyword_with_details("便签", country="CN", entity="software")
    assert len(out) == 1
    assert out[0]["itunes_id"] == "100"


def test_rank_keyword_with_details_persists_cache(tmp_path, monkeypatch):
    import competitor_research as cr

    cache_path = tmp_path / "serp.json"
    monkeypatch.setattr(cr, "SERP_DETAILS_CACHE_PATH", cache_path)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **kw: _fake_serp_response([
        (100, "com.a", "App A", 6007, 4.5, 1000, "desc"),
    ]))

    cr.rank_keyword_with_details("便签", country="CN", entity="software")
    on_disk = json.loads(cache_path.read_text())
    assert "software|cn|便签" in on_disk
    assert on_disk["software|cn|便签"]["entries"][0]["itunes_id"] == "100"


def _serp_entry(tid, bid, name, rank, genre=6007, rating=4.0, rcount=100, desc="d"):
    return {
        "itunes_id": str(tid), "bundle_id": bid, "name": name,
        "primary_genre_id": genre, "rating": rating, "review_count": rcount,
        "description": desc, "rank_in_serp": rank,
    }


def test_collect_outrankers_when_self_ranked():
    import competitor_research as cr
    serp = [
        _serp_entry(10, "com.rivalA", "Rival A", rank=1),
        _serp_entry(11, "com.rivalB", "Rival B", rank=2),
        _serp_entry(99, "com.self",   "Self",   rank=5),
        _serp_entry(12, "com.below",  "Below",  rank=6),
    ]
    out = cr.collect_outrankers_for_token(serp, self_bundle_id="com.self")
    assert out["self_rank"] == 5
    assert {r["bundle_id"] for r in out["outrankers"]} == {"com.rivalA", "com.rivalB"}


def test_collect_outrankers_when_self_unranked():
    import competitor_research as cr
    serp = [
        _serp_entry(10, "com.a", "A", rank=1),
        _serp_entry(11, "com.b", "B", rank=2),
    ]
    out = cr.collect_outrankers_for_token(serp, self_bundle_id="com.missing")
    assert out["self_rank"] is None
    assert len(out["outrankers"]) == 2  # both higher than ceiling 200


def test_collect_outrankers_returns_empty_for_empty_serp():
    import competitor_research as cr
    out = cr.collect_outrankers_for_token([], self_bundle_id="com.self")
    assert out == {"self_rank": None, "outrankers": []}


def test_aggregate_rivals_combines_across_tokens():
    import competitor_research as cr

    per_token = {
        "便签": {
            "self_rank": 10,
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=3),
                _serp_entry(101, "com.b", "App B", rank=5),
            ],
            "popularity": 80,
        },
        "桌面便签": {
            "self_rank": None,  # self unranked -> ceiling 200
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=2),
            ],
            "popularity": 60,
        },
    }

    rivals = cr.aggregate_rivals(per_token)
    by_id = {r["itunes_id"]: r for r in rivals}

    a = by_id["100"]
    assert a["name"] == "App A"
    assert a["outrank_count"] == 2
    assert sorted([k["keyword"] for k in a["outranked_keywords"]]) == ["便签", "桌面便签"]
    # 便签: self=10, rival=3, diff=7, pop=80
    # 桌面便签: self=200, rival=2, diff=198, pop=60
    assert a["threat_score"] == 80 * 7 + 60 * 198
    # avg diff = (7 + 198) / 2
    assert a["avg_rank_diff"] == statistics.mean([7, 198])

    b = by_id["101"]
    assert b["outrank_count"] == 1
    assert b["outranked_keywords"][0]["self_rank"] == 10
    assert b["outranked_keywords"][0]["rival_rank"] == 5


def test_aggregate_rivals_truncates_description_to_200_chars():
    import competitor_research as cr
    long_desc = "x" * 500
    per_token = {
        "k": {
            "self_rank": 10,
            "outrankers": [
                _serp_entry(100, "com.a", "App A", rank=3, desc=long_desc),
            ],
            "popularity": 50,
        }
    }
    rivals = cr.aggregate_rivals(per_token)
    assert len(rivals[0]["description_short"]) == 200


def test_threat_score_formula_pin():
    """Pin the formula: sum(popularity * diff) over outranked_keywords."""
    import competitor_research as cr
    rival = {
        "outranked_keywords": [
            {"popularity": 76, "diff": 197},   # unranked self vs rival #3
            {"popularity": 64, "diff": 10},    # self #15 vs rival #5
            {"popularity": 53, "diff": 6},     # self #8 vs rival #2
        ],
    }
    expected = 76 * 197 + 64 * 10 + 53 * 6
    assert cr.score_threat(rival) == expected


def _rival(itunes_id, genre, outrank_count, threat=100):
    return {
        "itunes_id": str(itunes_id),
        "name": f"R{itunes_id}",
        "primary_genre_id": genre,
        "outrank_count": outrank_count,
        "threat_score": threat,
        "outranked_keywords": [{"keyword": "k", "popularity": 1, "diff": 1,
                                "self_rank": 200, "rival_rank": 1}
                               for _ in range(outrank_count)],
    }


def test_filter_drops_cross_genre():
    import competitor_research as cr
    rivals = [
        _rival(1, genre=6007, outrank_count=5),
        _rival(2, genre=6014, outrank_count=5),  # games
    ]
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert [r["itunes_id"] for r in out] == ["1"]


def test_filter_drops_below_density_threshold():
    import competitor_research as cr
    rivals = [
        _rival(1, genre=6007, outrank_count=2),  # below 3
        _rival(2, genre=6007, outrank_count=3),  # exactly 3
        _rival(3, genre=6007, outrank_count=10),
    ]
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert {r["itunes_id"] for r in out} == {"2", "3"}


def test_filter_sorts_by_threat_desc_and_truncates_to_max_candidates():
    import competitor_research as cr
    rivals = [_rival(i, genre=6007, outrank_count=3, threat=i * 10)
              for i in range(1, 31)]  # 30 rivals
    out = cr.filter_by_genre_and_density(rivals, self_genre_id=6007)
    assert len(out) == cr.MAX_CANDIDATES_BEFORE_LLM  # 25
    # Sorted desc by threat
    threats = [r["threat_score"] for r in out]
    assert threats == sorted(threats, reverse=True)
    # The top should be itunes_id "30" (highest threat)
    assert out[0]["itunes_id"] == "30"


def test_build_phase_b_happy_path(monkeypatch):
    import competitor_research as cr

    phase_a = {
        "app": "Demo", "app_id": "111", "bundle_id": "com.self",
        "market": "CN", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }
    tokens = ["便签", "桌面便签", "记事本"]

    serps = {
        "便签": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=1, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=2, genre=6007),
            _serp_entry(99, "com.self",   "Self",   rank=10, genre=6007),
            _serp_entry(12, "com.gameX",  "GameX",  rank=3, genre=6014),  # cross-genre
        ],
        "桌面便签": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=1, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=3, genre=6007),
            _serp_entry(13, "com.rivalC", "Rival C", rank=5, genre=6007),
            # self not present
        ],
        "记事本": [
            _serp_entry(10, "com.rivalA", "Rival A", rank=2, genre=6007),
            _serp_entry(11, "com.rivalB", "Rival B", rank=4, genre=6007),
            _serp_entry(99, "com.self",   "Self",   rank=8, genre=6007),
        ],
    }
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": serps[k])
    monkeypatch.setattr(cr, "_lookup_popularity",
                        lambda kw, region: 50)

    out = cr.build_phase_b(phase_a, tokens)
    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "market", "primary_genre_id",
        "generated_at", "tokens", "self_ranks", "candidates",
    }
    assert out["tokens"] == tokens
    assert out["self_ranks"] == {"便签": 10, "桌面便签": None, "记事本": 8}
    cand_by_id = {c["itunes_id"]: c for c in out["candidates"]}
    # Rival A outranks self on both tokens (rank 1 < 10, rank 1 < 200)
    assert "10" in cand_by_id
    # Rival B outranks self on both (rank 2 < 10, rank 3 < 200)
    assert "11" in cand_by_id
    # Rival C only outranks on 桌面便签 (count=1, below MIN_OUTRANK_COUNT=3) -> dropped
    assert "13" not in cand_by_id
    # GameX is cross-genre -> dropped
    assert "12" not in cand_by_id


def test_build_phase_b_empty_when_no_rivals_pass_filters(monkeypatch):
    """Spec §13 edge case: an app whose SERPs yield no qualifying rivals.
    Result is an empty candidates list — Claude will render the
    'evidence-thin' warning. The script does not crash."""
    import competitor_research as cr
    phase_a = {
        "app": "Lonely", "app_id": "111", "bundle_id": "com.lonely",
        "market": "US", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": [])
    monkeypatch.setattr(cr, "_lookup_popularity", lambda kw, region: 50)
    out = cr.build_phase_b(phase_a, tokens=["a", "b"])
    assert out["candidates"] == []
    assert out["self_ranks"] == {"a": None, "b": None}


def test_cmd_rank_writes_phase_b(monkeypatch, tmp_path):
    import competitor_research as cr

    phase_a_path = tmp_path / "phase_a_competitors_demo_us.json"
    phase_a_path.write_text(json.dumps({
        "app": "Demo", "app_id": "111", "bundle_id": "com.self",
        "market": "US", "primary_genre_id": 6007,
        "generated_at": "2026-05-16T00:00:00Z",
    }))
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cr, "rank_keyword_with_details",
                        lambda k, country, entity="software": [
                            _serp_entry(10, "com.r", "R", rank=1, genre=6007),
                            _serp_entry(99, "com.self", "Self", rank=20, genre=6007),
                        ])
    monkeypatch.setattr(cr, "_lookup_popularity", lambda kw, region: 50)

    rc = cr.cmd_rank("Demo", tokens=["a", "b", "c"])
    assert rc == 0
    out = tmp_path / "phase_b_competitors_demo_us.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["tokens"] == ["a", "b", "c"]
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["itunes_id"] == "10"
    assert data["candidates"][0]["outrank_count"] == 3


def test_main_dispatches_analyze(monkeypatch):
    import competitor_research as cr
    captured = {}
    def fake_analyze(q):
        captured["analyze"] = q
        return 0
    monkeypatch.setattr(cr, "cmd_analyze", fake_analyze)
    rc = cr.main(["analyze", "Demo"])
    assert rc == 0
    assert captured["analyze"] == "Demo"


def test_main_dispatches_rank_with_tokens(monkeypatch):
    import competitor_research as cr
    captured = {}
    def fake_rank(q, tokens):
        captured["q"] = q
        captured["tokens"] = tokens
        return 0
    monkeypatch.setattr(cr, "cmd_rank", fake_rank)
    rc = cr.main(["rank", "Demo", "--tokens", "便签,桌面便签,memo"])
    assert rc == 0
    assert captured["q"] == "Demo"
    assert captured["tokens"] == ["便签", "桌面便签", "memo"]


def test_main_help_when_no_args(capsys):
    import competitor_research as cr
    rc = cr.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "Usage" in captured.out or "Usage" in captured.err


def test_show_a_prints_summary(monkeypatch, tmp_path, capsys):
    import competitor_research as cr
    phase_a_path = tmp_path / "phase_a_competitors_demo_us.json"
    phase_a_path.write_text(json.dumps({
        "app": "Demo", "market": "US", "primary_genre_id": 6007,
        "raw": {"title": "Demo App", "subtitle": "sub", "keywords": "a,b,c"},
    }))
    monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path)
    rc = cr.cmd_show_a("Demo")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Demo" in out
    assert "6007" in out
