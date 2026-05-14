"""Tests for feature_ideate."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def test_module_imports():
    import feature_ideate  # noqa: F401


def _row(app_id: str, country: str, ptid: str = "1F", units: str = "1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def test_pick_primary_market_uses_max_downloads_in_window():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "en-US"}}
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-10": [_row("111", "CN"), _row("111", "CN"), _row("111", "US")],
        "2026-05-09": [_row("111", "CN"), _row("111", "JP")],
    }
    assert pick_primary_market(app, cache, today=today) == "CN"


def test_pick_primary_market_ignores_updates_and_other_apps():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "ja"}}
    today = dt.date(2026, 5, 13)
    cache = {
        "2026-05-10": [
            _row("222", "CN", units="999"),
            _row("111", "JP", ptid="7"),
            _row("111", "US"),
        ],
    }
    assert pick_primary_market(app, cache, today=today) == "US"


def test_pick_primary_market_falls_back_to_primary_locale_country():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {"primaryLocale": "zh-Hans"}}
    today = dt.date(2026, 5, 13)
    cache = {}
    assert pick_primary_market(app, cache, today=today) == "CN"


def test_pick_primary_market_locale_without_region_uses_known_map():
    from feature_ideate import pick_primary_market

    for locale, expected in [("ja", "JP"), ("ko", "KR"), ("de-DE", "DE")]:
        app = {"id": "111", "core": {"primaryLocale": locale}}
        assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == expected


def test_pick_primary_market_ultimate_fallback_is_us():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {}}
    assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == "US"


def _review(rating, body, days_ago, title="", territory="CHN"):
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


def test_bucket_reviews_negative_includes_low_ratings_with_long_body():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(1, "极差极差极差极差极差", 10),
        _review(2, "ok", 10),
        _review(3, "this is decent description here", 20),
        _review(4, "this is decent description here", 20),
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 2
    assert all(r["rating"] <= 3 for r in out["negative"])
    assert all(len(r["body"]) >= 10 for r in out["negative"])


def test_bucket_reviews_wishlist_requires_trigger_word():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(5, "great app overall", 5),
        _review(5, "希望加分组功能", 5),
        _review(4, "please add dark mode support", 5),
        _review(4, "love it ok ok ok", 5),
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["wishlist"]) == 2
    bodies = {r["body"] for r in out["wishlist"]}
    assert "希望加分组功能" in bodies
    assert "please add dark mode support" in bodies


def test_bucket_reviews_drops_reviews_older_than_90_days():
    from feature_ideate import bucket_reviews

    reviews = [
        _review(1, "old complaint that is long enough", 100),
        _review(1, "recent complaint that is long enough", 10),
    ]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 1
    assert "recent" in out["negative"][0]["body"]


def test_bucket_reviews_caps_each_bucket_at_50():
    from feature_ideate import bucket_reviews

    reviews = [_review(1, f"complaint {i} body content here", 1) for i in range(80)]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out["negative"]) == 50


def test_bucket_reviews_records_keep_minimal_schema():
    from feature_ideate import bucket_reviews

    reviews = [_review(2, "this body has enough chars", 1, title="bad", territory="USA")]
    out = bucket_reviews(reviews, today=dt.date(2026, 5, 13))
    r = out["negative"][0]
    assert set(r.keys()) == {"rating", "title", "body", "locale", "created_at"}
    assert r["locale"] == "USA"
    assert r["title"] == "bad"


def test_pick_competitor_seed_uses_title_longest_word():
    from feature_ideate import pick_competitor_seed

    app = {
        "core": {"name": "Sticky Note Pro: Post-it&Memo"},
        "appInfo": {
            "localizations": [
                {"locale": "en-US", "name": "Sticky Note Pro: Post-it&Memo"}
            ]
        },
    }
    assert pick_competitor_seed(app) == "Sticky"


def test_pick_competitor_seed_uses_locale_name_when_available():
    from feature_ideate import pick_competitor_seed

    app = {
        "core": {"name": "X"},
        "appInfo": {
            "localizations": [
                {"locale": "zh-Hans", "name": "便签Pro:备忘录Memo便利贴"}
            ]
        },
    }
    assert pick_competitor_seed(app) == "Memo"


def test_pick_competitor_seed_returns_app_when_everything_fails():
    from feature_ideate import pick_competitor_seed

    app = {"core": {"name": ""}, "appInfo": {"localizations": []}}
    assert pick_competitor_seed(app) == "app"


def test_fetch_competitors_calls_rag_with_spec_params(monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "name": "Notion",
                "rating": 4.7,
                "review_count": 9000,
                "description": "All-in-one workspace",
                "appmate_reason": "high engagement",
                "category_slug": "productivity",
                "extra_field": "drop me",
            }
        ]

    import feature_ideate
    monkeypatch.setattr(feature_ideate, "_rag_search", fake_search)

    out = feature_ideate.fetch_competitors("便签", country="CN")
    assert captured == {
        "query": "便签",
        "region": "cn",
        "top_k": 10,
        "min_review_count": 50,
        "sort_by": "S",
    }
    assert len(out) == 1
    assert set(out[0].keys()) == {"name", "rating", "review_count", "description", "appmate_reason"}
    assert out[0]["name"] == "Notion"


def test_fetch_competitors_returns_empty_on_exception(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("network down")

    import feature_ideate
    monkeypatch.setattr(feature_ideate, "_rag_search", boom)
    out = feature_ideate.fetch_competitors("便签", country="CN")
    assert out == []


def test_build_phase_a_returns_full_schema(monkeypatch):
    from feature_ideate import build_phase_a

    app = {
        "id": "111",
        "core": {
            "name": "DemoApp",
            "bundleId": "com.demo",
            "primaryLocale": "zh-Hans",
        },
        "appInfo": {"localizations": []},
        "reviews": {
            "count": 3,
            "averageRating": 3.0,
            "reviews": [
                _review(1, "极差极差极差极差极差", 1),
                _review(5, "希望加分组功能", 1),
            ],
        },
    }
    sales_cache = {"2026-05-10": [_row("111", "CN")]}

    monkeypatch.setattr("feature_ideate._rag_search",
                        lambda **kw: [{"name": "Notion", "rating": 4.7,
                                       "review_count": 9000,
                                       "description": "all in one",
                                       "appmate_reason": "broad"}])

    out = build_phase_a(app, sales_cache, today=dt.date(2026, 5, 13))
    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "market", "downloads_30d_in_market",
        "generated_at", "competitor_seed",
        "reviews_negative", "reviews_wishlist", "competitors",
    }
    assert "aso_blindspots" not in out  # v2: removed
    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "CN"
    assert out["downloads_30d_in_market"] == 1
    assert len(out["reviews_negative"]) == 1
    assert len(out["reviews_wishlist"]) == 1
    assert out["competitors"][0]["name"] == "Notion"


def test_build_phase_a_handles_empty_inputs(monkeypatch):
    from feature_ideate import build_phase_a

    app = {"id": "111", "core": {"name": "X", "bundleId": "com.x",
           "primaryLocale": "en-US"},
           "appInfo": {"localizations": []},
           "reviews": {"count": 0, "averageRating": 0, "reviews": []}}
    monkeypatch.setattr("feature_ideate._rag_search", lambda **kw: [])
    out = build_phase_a(app, {}, today=dt.date(2026, 5, 13))
    assert out["market"] == "US"
    assert out["reviews_negative"] == []
    assert out["competitors"] == []


def test_main_writes_phase_a_file(monkeypatch, tmp_path, capsys):
    """End-to-end: main() reads cache files, writes phase_a json."""
    import feature_ideate as fi

    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"
    out_dir = tmp_path

    apps_full.write_text(json.dumps({"apps": [{
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }]}))
    sales.write_text("{}")

    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(fi, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(fi, "_rag_search", lambda **kw: [])

    rc = fi.main(["DemoApp"])
    assert rc == 0

    expected = out_dir / "phase_a_feature_demoapp_us.json"
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["market"] == "US"
    assert "aso_blindspots" not in data  # v2: removed


def test_main_returns_nonzero_when_app_not_found(monkeypatch, tmp_path):
    import feature_ideate as fi
    apps_full = tmp_path / "apps_full.json"
    apps_full.write_text(json.dumps({"apps": []}))
    sales = tmp_path / "sales_cache.json"
    sales.write_text("{}")
    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(fi, "OUTPUT_DIR", tmp_path)
    rc = fi.main(["NoSuchApp"])
    assert rc != 0
