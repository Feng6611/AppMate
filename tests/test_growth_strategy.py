"""Tests for growth_strategy (Step 1 aggregator)."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def _row(app_id: str, country: str, ptid: str = "1F", units: str = "1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def _review(rating, body, days_ago, title="", territory="USA"):
    today = dt.date(2026, 5, 13)
    created = today - dt.timedelta(days=days_ago)
    return {
        "id": f"r{rating}{days_ago}",
        "rating": rating,
        "title": title,
        "body": body,
        "territory": territory,
        "createdDate": created.isoformat() + "T00:00:00-07:00",
    }


def test_module_imports():
    import growth_strategy  # noqa: F401


# --- _downloads_in_window ----------------------------------------------

def test_downloads_in_window_filters_by_date_country_ptid():
    from growth_strategy import _downloads_in_window
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-13": [_row("111", "CN", units="3")],
        "2026-05-10": [_row("111", "CN"), _row("111", "US")],
        "2026-03-01": [_row("111", "CN", units="999")],
        "2026-05-12": [_row("111", "CN", ptid="7", units="50")],
        "2026-05-11": [_row("222", "CN", units="50")],
    }
    out = _downloads_in_window("111", cache, "CN", today - dt.timedelta(days=29), today)
    assert out == 4


def test_downloads_in_window_country_none_sums_all_countries():
    from growth_strategy import _downloads_in_window
    today = dt.date(2026, 5, 13)
    cache = {"2026-05-10": [_row("111", "CN", units="3"), _row("111", "US", units="2")]}
    out = _downloads_in_window("111", cache, None, today - dt.timedelta(days=29), today)
    assert out == 5


# --- compute_sales_trend -----------------------------------------------

def test_compute_sales_trend_basic():
    from growth_strategy import compute_sales_trend
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-10": [_row("111", "CN", units="5"), _row("111", "US", units="1")],
        "2026-04-10": [_row("111", "CN", units="2")],
    }
    s = compute_sales_trend("111", cache, "CN", today)
    assert s["D30"] == 5
    assert s["D30_prev"] == 2
    assert s["slope"] == 2.5
    assert s["market_concentration"] == round(5 / 6, 2)


def test_compute_sales_trend_zero_prev_uses_div1_floor():
    from growth_strategy import compute_sales_trend
    today = dt.date(2026, 5, 13)
    cache = {"2026-05-10": [_row("111", "CN", units="5")]}
    s = compute_sales_trend("111", cache, "CN", today)
    assert s["slope"] == 5.0
    assert s["D30_prev"] == 0


def test_compute_sales_trend_zero_market_concentration_when_no_total():
    from growth_strategy import compute_sales_trend
    s = compute_sales_trend("111", {}, "CN", dt.date(2026, 5, 13))
    assert s["market_concentration"] == 0.0
    assert s["D30"] == 0


# --- determine_stage ---------------------------------------------------

def test_determine_stage_cold_by_low_reviews():
    from growth_strategy import determine_stage
    sales = {"D30": 500, "D30_prev": 400, "slope": 1.25}
    stage, ev = determine_stage(sales, total_reviews=10)
    assert stage == "冷启动"
    assert any("评价" in s for s in ev)


def test_determine_stage_cold_by_low_d30():
    from growth_strategy import determine_stage
    sales = {"D30": 50, "D30_prev": 30, "slope": 1.67}
    stage, ev = determine_stage(sales, total_reviews=100)
    assert stage == "冷启动"
    assert any("D30=50" in s for s in ev)


def test_determine_stage_decline():
    from growth_strategy import determine_stage
    sales = {"D30": 200, "D30_prev": 300, "slope": 0.67}
    stage, ev = determine_stage(sales, total_reviews=50)
    assert stage == "衰退"
    assert any("跌" in s for s in ev)


def test_determine_stage_growth():
    from growth_strategy import determine_stage
    sales = {"D30": 500, "D30_prev": 200, "slope": 2.5}
    stage, ev = determine_stage(sales, total_reviews=100)
    assert stage == "早期增长"
    assert any("涨" in s for s in ev)


def test_determine_stage_plateau_at_boundaries():
    """slope = 0.8 / 1.0 / 1.2 should all be 平台期 (strict boundaries)."""
    from growth_strategy import determine_stage
    for slope in (0.8, 1.0, 1.2):
        sales = {"D30": 200, "D30_prev": 200, "slope": slope}
        stage, _ = determine_stage(sales, total_reviews=50)
        assert stage == "平台期", f"slope={slope} should be 平台期, got {stage}"


# --- extract_aso_state -------------------------------------------------

def test_extract_aso_state_current_locales_dedupes_and_sorts():
    from growth_strategy import extract_aso_state
    app = {
        "id": "111",
        "core": {"bundleId": "com.x"},
        "appInfo": {"localizations": [
            {"locale": "en-US"}, {"locale": "zh-Hans"}, {"locale": "en-US"}
        ]},
    }
    s = extract_aso_state(app, {}, {}, "CN", dt.date(2026, 5, 13))
    assert s["current_locales"] == ["en-US", "zh-Hans"]


def test_extract_aso_state_counts_top10_keywords_from_latest_snapshot():
    from growth_strategy import extract_aso_state
    app = {"id": "111", "core": {"bundleId": "com.x"}, "appInfo": {"localizations": []}}
    snaps = {
        "2026-05-12": {"com.x": {"CN": {"kw1": 5, "kw2": 50}}},
        "2026-05-13": {"com.x": {"CN": {"kw1": 3, "kw2": 8, "kw3": 25}}},
    }
    s = extract_aso_state(app, snaps, {}, "CN", dt.date(2026, 5, 13))
    assert s["primary_market_top10_keywords"] == 2  # kw1=3 and kw2=8 in latest


def test_extract_aso_state_top10_zero_when_no_snapshot_for_market():
    from growth_strategy import extract_aso_state
    app = {"id": "111", "core": {"bundleId": "com.x"}, "appInfo": {"localizations": []}}
    snaps = {"2026-05-13": {"com.x": {"US": {"kw1": 1}}}}
    s = extract_aso_state(app, snaps, {}, "CN", dt.date(2026, 5, 13))
    assert s["primary_market_top10_keywords"] == 0


def test_extract_aso_state_missing_locale_for_high_volume_country():
    from growth_strategy import extract_aso_state
    app = {
        "id": "111",
        "core": {"bundleId": "com.x"},
        "appInfo": {"localizations": [{"locale": "en-US"}, {"locale": "zh-Hans"}]},
    }
    cache = {"2026-05-10": [
        _row("111", "CN", units="100"),
        _row("111", "MX", units="50"),
        _row("111", "BR", units="20"),
    ]}
    s = extract_aso_state(app, {}, cache, "CN", dt.date(2026, 5, 13))
    assert "es-MX" in s["missing_locales_in_top_markets"]
    assert "pt-BR" in s["missing_locales_in_top_markets"]
    # CN is covered by zh-Hans → not in missing
    assert "zh-Hans-CN" not in s["missing_locales_in_top_markets"]


def test_extract_aso_state_no_missing_when_all_top_markets_have_locale():
    from growth_strategy import extract_aso_state
    app = {
        "id": "111",
        "core": {"bundleId": "com.x"},
        "appInfo": {"localizations": [{"locale": "en-US"}, {"locale": "zh-Hans"}]},
    }
    cache = {"2026-05-10": [
        _row("111", "CN", units="100"),
        _row("111", "US", units="50"),
    ]}
    s = extract_aso_state(app, {}, cache, "CN", dt.date(2026, 5, 13))
    assert s["missing_locales_in_top_markets"] == []


# --- summarize_reviews -------------------------------------------------

def test_summarize_reviews_counts_and_avg():
    from growth_strategy import summarize_reviews
    today = dt.date(2026, 5, 13)
    reviews = [
        _review(5, "great app", 5),
        _review(1, "极差极差极差极差极差", 5),
        _review(5, "希望加分组功能", 5),
    ]
    s = summarize_reviews(reviews, today)
    assert s["total"] == 3
    assert s["rating_avg"] == round((5 + 1 + 5) / 3, 2)
    assert s["negative_count_90d"] == 1
    assert s["wishlist_count_90d"] == 1
    assert s["top_negative_themes"] == ["极差极差极差极差极差"]


def test_summarize_reviews_handles_empty():
    from growth_strategy import summarize_reviews
    s = summarize_reviews([], dt.date(2026, 5, 13))
    assert s["total"] == 0
    assert s["rating_avg"] == 0.0
    assert s["negative_count_90d"] == 0
    assert s["wishlist_count_90d"] == 0
    assert s["top_negative_themes"] == []


# --- fetch_competitors -------------------------------------------------

def test_fetch_competitors_uses_top_k_8(monkeypatch):
    import growth_strategy as gs
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [{
            "name": "X", "rating": 4.5, "review_count": 100,
            "description": "d", "appmate_reason": "r", "extra_field": "drop me",
        }]

    monkeypatch.setattr(gs, "_rag_search", fake_search)
    out = gs.fetch_competitors("seed", country="CN")
    assert captured == {
        "query": "seed",
        "region": "cn",
        "top_k": 8,
        "min_review_count": 50,
        "sort_by": "S",
    }
    assert len(out) == 1
    assert set(out[0].keys()) == {"name", "rating", "review_count", "description", "appmate_reason"}


def test_fetch_competitors_returns_empty_on_exception(monkeypatch):
    import growth_strategy as gs

    def boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(gs, "_rag_search", boom)
    assert gs.fetch_competitors("seed", "CN") == []


# --- build_phase_a -----------------------------------------------------

def test_build_phase_a_full_schema(monkeypatch):
    import growth_strategy as gs
    app = {
        "id": "111",
        "core": {"name": "Demo", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": [{"locale": "en-US", "name": "Demo App"}]},
        "reviews": {"count": 2, "averageRating": 3.0, "reviews": [
            _review(5, "great great great", 5),
            _review(1, "bad bad bad bad bad", 5),
        ]},
    }
    cache = {"2026-05-10": [_row("111", "US", units="50")]}
    snaps = {"2026-05-13": {"com.demo": {"US": {"demo": 5, "app": 12}}}}

    monkeypatch.setattr(gs, "_rag_search", lambda **kw: [])
    out = gs.build_phase_a(app, cache, snaps, today=dt.date(2026, 5, 13))

    expected_keys = {
        "app", "app_id", "bundle_id", "market", "generated_at",
        "sales", "stage", "stage_evidence", "aso", "reviews",
        "competitor_seed", "competitors",
    }
    assert set(out.keys()) == expected_keys
    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "US"
    assert "D30" in out["sales"]
    assert out["stage"] in {"冷启动", "衰退", "早期增长", "平台期"}
    assert out["aso"]["primary_market_top10_keywords"] == 1  # demo=5, app=12 → only demo


def test_build_phase_a_cold_start_with_zero_reviews(monkeypatch):
    import growth_strategy as gs
    app = {
        "id": "111",
        "core": {"name": "Demo", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }
    monkeypatch.setattr(gs, "_rag_search", lambda **kw: [])
    out = gs.build_phase_a(app, {}, {}, today=dt.date(2026, 5, 13))
    assert out["stage"] == "冷启动"
    assert out["sales"]["D30"] == 0


# --- main --------------------------------------------------------------

def test_main_writes_phase_a_file(monkeypatch, tmp_path):
    import growth_strategy as gs
    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"
    snaps = tmp_path / "snaps.json"
    apps_full.write_text(json.dumps({"apps": [{
        "id": "111",
        "core": {"name": "Demo", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }]}))
    sales.write_text("{}")
    snaps.write_text("{}")
    monkeypatch.setattr(gs, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(gs, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(gs, "ASO_SNAPSHOTS_PATH", snaps)
    monkeypatch.setattr(gs, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gs, "_rag_search", lambda **kw: [])

    rc = gs.main(["Demo"])
    assert rc == 0
    expected = tmp_path / "phase_a_growth_demo_us.json"
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["stage"] == "冷启动"


def test_main_returns_nonzero_when_app_not_found(monkeypatch, tmp_path):
    import growth_strategy as gs
    apps_full = tmp_path / "apps_full.json"
    apps_full.write_text(json.dumps({"apps": []}))
    sales = tmp_path / "sales_cache.json"
    sales.write_text("{}")
    snaps = tmp_path / "snaps.json"
    snaps.write_text("{}")
    monkeypatch.setattr(gs, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(gs, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(gs, "ASO_SNAPSHOTS_PATH", snaps)
    monkeypatch.setattr(gs, "OUTPUT_DIR", tmp_path)
    rc = gs.main(["NoSuchApp"])
    assert rc != 0
