"""Smoke tests for keyword_local — the static-table-backed pop/diff estimator."""
from __future__ import annotations

import json

import keyword_local


def _seed_table(tmp_path, rows, region="cn", monkeypatch=None):
    """Write a fake reference table at tmp_path and point keyword_local at it."""
    import appmate_config
    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    keyword_local._TABLES.clear()
    (tmp_path / f"keyword_reference_{region}.json").write_text(
        json.dumps({"region": region, "rows": rows}, ensure_ascii=False)
    )


def test_exact_match_returns_stored_values(tmp_path, monkeypatch):
    _seed_table(tmp_path, [
        {"keyword": "便签", "popularity": 48, "difficulty": 68,
         "apps_count": 216, "popularity_is_floor": False},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(["便签"], "cn")
    rec = out["便签"]
    assert rec["popularity"] == 48
    assert rec["difficulty"] == 68
    assert rec["appsCount"] == 216
    assert rec["popularity_is_floor"] is False
    assert rec["was_tracked"] is False  # local table; no live tracking concept


def test_long_tail_extension_inherits_with_discount(tmp_path, monkeypatch):
    """kw 'Pro 便签' contains table word '便签' → discounted long-tail pop."""
    _seed_table(tmp_path, [
        {"keyword": "便签", "popularity": 50, "difficulty": 60, "apps_count": 200},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(["Pro 便签"], "cn")
    rec = out["Pro 便签"]
    assert rec["popularity"] == int(50 * 0.7)
    assert rec["difficulty"] == 60


def test_broader_query_inherits_with_bump(tmp_path, monkeypatch):
    """kw '便签' is contained in table word '云便签' → bumped pop."""
    _seed_table(tmp_path, [
        {"keyword": "云便签", "popularity": 40, "difficulty": 55, "apps_count": 180},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(["便签"], "cn")
    rec = out["便签"]
    assert rec["popularity"] == min(int(40 * 1.1), 99)
    assert rec["difficulty"] == 55


def test_no_match_returns_default_floor(tmp_path, monkeypatch):
    _seed_table(tmp_path, [
        {"keyword": "便签", "popularity": 48, "difficulty": 68, "apps_count": 216},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(["完全不相关xyz"], "cn")
    rec = out["完全不相关xyz"]
    assert rec["popularity"] == keyword_local.DEFAULT_POP
    assert rec["difficulty"] == keyword_local.DEFAULT_DIFF
    assert rec["popularity_is_floor"] is True
    assert rec["appsCount"] is None


def test_missing_reference_file_falls_back_to_default(tmp_path, monkeypatch):
    import appmate_config
    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    keyword_local._TABLES.clear()
    out = keyword_local.lookup_popularity_batch(["anything"], "jp")
    rec = out["anything"]
    assert rec["popularity"] == keyword_local.DEFAULT_POP
    assert rec["difficulty"] == keyword_local.DEFAULT_DIFF
    assert rec["popularity_is_floor"] is True


def test_return_shape_includes_all_consumer_fields(tmp_path, monkeypatch):
    """The estimator's record must carry every field downstream code reads."""
    _seed_table(tmp_path, [
        {"keyword": "便签", "popularity": 48, "difficulty": 68, "apps_count": 216},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(["便签"], "cn")
    expected_keys = {
        "keyword", "store", "popularity", "difficulty", "currentRanking",
        "appsCount", "popularity_is_floor", "was_tracked", "fetched_at",
    }
    assert expected_keys.issubset(out["便签"].keys())


def test_extra_kwargs_silently_accepted(tmp_path, monkeypatch):
    """Drop-in compat: callers pass anchor_app_id / batch_size / etc — must not raise."""
    _seed_table(tmp_path, [
        {"keyword": "便签", "popularity": 48, "difficulty": 68, "apps_count": 216},
    ], monkeypatch=monkeypatch)
    out = keyword_local.lookup_popularity_batch(
        ["便签"], "cn",
        anchor_app_id="10", use_cache=True, batch_size=5,
        cache_ttl_hours=24, add_timeout=300,
    )
    assert "便签" in out
