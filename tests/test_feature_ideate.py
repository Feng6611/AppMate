"""Tests for feature_ideate (v3: raw reviews + competitors_<slug>.json consumer)."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


# --- helpers --------------------------------------------------------------

def _row(app_id: str, country: str, ptid: str = "1F", units: str = "1") -> dict:
    return {
        "Apple Identifier": app_id,
        "Country Code": country,
        "Product Type Identifier": ptid,
        "Units": units,
    }


def _review(rating, body, days_ago, title="", territory="CHN"):
    today = dt.date(2026, 5, 13)
    created = today - dt.timedelta(days=days_ago)
    return {
        "id": f"r{rating}_{days_ago}_{abs(hash(body)) % 10_000}",
        "rating": rating,
        "title": title,
        "body": body,
        "territory": territory,
        "createdDate": created.isoformat() + "T00:00:00-07:00",
    }


def _competitors_payload(generated_at="2026-05-01T00:00:00+00:00", filtered=None):
    default_filtered = [
        {
            "itunes_id": "555",
            "bundle_id": "com.other",
            "name": "Rival便签",
            "primary_genre_id": 6007,
            "rating": 4.7,
            "review_count": 9000,
            "description_short": "桌面快速记事工具",
            "outranked_keywords": ["便签", "memo"],
            "outrank_count": 5,
            "avg_rank_diff": 15.0,
            "threat_score": 42,
            "relevance_keep": True,
            "relevance_reason": "目标用户重叠",
        }
    ]
    return {
        "app": "DemoApp",
        "app_id": "111",
        "bundle_id": "com.demo",
        "market": "CN",
        "primary_genre_id": 6007,
        "generated_at": generated_at,
        "tokens": ["便签", "memo"],
        "self_ranks": {"便签": 12},
        "filtered": filtered if filtered is not None else default_filtered,
        "dropped_by_relevance": [],
    }


def _write_competitors_json(out_dir, slug, payload=None):
    payload = payload if payload is not None else _competitors_payload()
    p = pathlib.Path(out_dir) / f"competitors_{slug}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False))
    return p


# --- module import --------------------------------------------------------

def test_module_imports():
    import feature_ideate  # noqa: F401


# --- pick_primary_market --------------------------------------------------

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
    assert pick_primary_market(app, {}, today=today) == "CN"


def test_pick_primary_market_locale_without_region_uses_known_map():
    from feature_ideate import pick_primary_market

    for locale, expected in [("ja", "JP"), ("ko", "KR"), ("de-DE", "DE")]:
        app = {"id": "111", "core": {"primaryLocale": locale}}
        assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == expected


def test_pick_primary_market_ultimate_fallback_is_us():
    from feature_ideate import pick_primary_market

    app = {"id": "111", "core": {}}
    assert pick_primary_market(app, {}, today=dt.date(2026, 5, 13)) == "US"


# --- collect_raw_reviews --------------------------------------------------

def test_collect_raw_reviews_keeps_last_90_days_newest_first():
    from feature_ideate import collect_raw_reviews

    reviews = [
        _review(1, "old beyond window", 100),
        _review(1, "mid window", 30),
        _review(5, "fresh", 1),
        _review(2, "ancient", 1000),
    ]
    out = collect_raw_reviews(reviews, today=dt.date(2026, 5, 13))
    bodies = [r["body"] for r in out]
    assert bodies == ["fresh", "mid window"]


def test_collect_raw_reviews_no_rating_or_trigger_filter():
    """v3 sends everything in window — LLM classifies later."""
    from feature_ideate import collect_raw_reviews

    reviews = [
        _review(1, "x", 1),              # 1-char body (v2 would have dropped)
        _review(5, "great", 1),           # praise no trigger word (v2 would have dropped)
        _review(3, "meh ok ok ok", 1),    # middle rating (v2 dropped from both buckets)
    ]
    out = collect_raw_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out) == 3


def test_collect_raw_reviews_caps_at_150_by_default():
    from feature_ideate import collect_raw_reviews

    reviews = [_review(3, f"review {i}", 1) for i in range(200)]
    out = collect_raw_reviews(reviews, today=dt.date(2026, 5, 13))
    assert len(out) == 150


def test_collect_raw_reviews_respects_explicit_cap():
    from feature_ideate import collect_raw_reviews

    reviews = [_review(3, f"r{i}", 1) for i in range(10)]
    out = collect_raw_reviews(reviews, today=dt.date(2026, 5, 13), cap=5)
    assert len(out) == 5


def test_collect_raw_reviews_slim_schema():
    from feature_ideate import collect_raw_reviews

    reviews = [_review(2, "body content", 1, title="bad", territory="USA")]
    out = collect_raw_reviews(reviews, today=dt.date(2026, 5, 13))
    r = out[0]
    assert set(r.keys()) == {"rating", "title", "body", "locale", "created_at"}
    assert r["locale"] == "USA"
    assert r["title"] == "bad"


# --- load_competitors -----------------------------------------------------

def test_load_competitors_returns_slim_filtered_list(tmp_path):
    from feature_ideate import COMPETITOR_FIELDS, load_competitors, slugify

    slug = slugify("DemoApp", "CN")
    _write_competitors_json(tmp_path, slug)
    out = load_competitors("DemoApp", "CN", data_dir=tmp_path)
    assert out is not None
    assert out["generated_at"] == "2026-05-01T00:00:00+00:00"
    assert len(out["entries"]) == 1
    entry = out["entries"][0]
    assert set(entry.keys()) == set(COMPETITOR_FIELDS)
    assert entry["name"] == "Rival便签"
    assert entry["relevance_reason"] == "目标用户重叠"
    # raw phase_b internals must not leak through
    assert "itunes_id" not in entry
    assert "bundle_id" not in entry
    assert "outrank_count" not in entry


def test_load_competitors_returns_none_when_file_missing(tmp_path):
    from feature_ideate import load_competitors

    assert load_competitors("DemoApp", "CN", data_dir=tmp_path) is None


def test_load_competitors_handles_empty_filtered_list(tmp_path):
    from feature_ideate import load_competitors, slugify

    slug = slugify("DemoApp", "CN")
    _write_competitors_json(tmp_path, slug, _competitors_payload(filtered=[]))
    out = load_competitors("DemoApp", "CN", data_dir=tmp_path)
    assert out is not None
    assert out["entries"] == []


# --- build_phase_a --------------------------------------------------------

def test_build_phase_a_returns_v3_schema(tmp_path):
    from feature_ideate import build_phase_a, slugify

    app = {
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "zh-Hans"},
        "appInfo": {"localizations": []},
        "reviews": {
            "count": 2,
            "averageRating": 3.0,
            "reviews": [
                _review(1, "极差极差极差极差极差", 1),
                _review(5, "希望加分组功能", 1),
            ],
        },
    }
    sales_cache = {"2026-05-10": [_row("111", "CN")]}
    slug = slugify("DemoApp", "CN")
    _write_competitors_json(tmp_path, slug)

    out = build_phase_a(app, sales_cache, today=dt.date(2026, 5, 13), data_dir=tmp_path)
    assert out is not None
    assert set(out.keys()) == {
        "app", "app_id", "bundle_id", "market", "downloads_30d_in_market",
        "generated_at", "reviews",
        "competitors_source", "competitors_generated_at", "competitors",
    }
    # v2 keys must be gone
    assert "reviews_negative" not in out
    assert "reviews_wishlist" not in out
    assert "competitor_seed" not in out
    assert "aso_blindspots" not in out

    assert out["bundle_id"] == "com.demo"
    assert out["market"] == "CN"
    assert out["downloads_30d_in_market"] == 1
    assert len(out["reviews"]) == 2
    assert out["competitors"][0]["name"] == "Rival便签"
    assert out["competitors_generated_at"] == "2026-05-01T00:00:00+00:00"
    assert "competitors_" in out["competitors_source"]  # path string sanity check


def test_build_phase_a_returns_none_when_competitors_missing(tmp_path):
    from feature_ideate import build_phase_a

    app = {
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "zh-Hans"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }
    sales_cache = {"2026-05-10": [_row("111", "CN")]}
    out = build_phase_a(app, sales_cache, today=dt.date(2026, 5, 13), data_dir=tmp_path)
    assert out is None


def test_build_phase_a_handles_empty_reviews(tmp_path):
    from feature_ideate import build_phase_a, slugify

    app = {
        "id": "111",
        "core": {"name": "X", "bundleId": "com.x", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }
    slug = slugify("X", "US")
    _write_competitors_json(tmp_path, slug)
    out = build_phase_a(app, {}, today=dt.date(2026, 5, 13), data_dir=tmp_path)
    assert out is not None
    assert out["market"] == "US"
    assert out["reviews"] == []


# --- main() ---------------------------------------------------------------

def test_main_writes_phase_a_file(monkeypatch, tmp_path):
    """End-to-end: main() reads caches + competitors json, writes phase_a json."""
    import feature_ideate as fi

    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"

    apps_full.write_text(json.dumps({"apps": [{
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }]}))
    sales.write_text("{}")

    slug = fi.slugify("DemoApp", "US")
    _write_competitors_json(tmp_path, slug)

    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(fi, "OUTPUT_DIR", tmp_path)

    rc = fi.main(["DemoApp"])
    assert rc == 0

    expected = tmp_path / f"phase_a_feature_{slug}.json"
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert data["bundle_id"] == "com.demo"
    assert data["market"] == "US"
    assert "reviews" in data
    assert "competitors" in data
    # v2 invariants must stay gone
    assert "competitor_seed" not in data
    assert "reviews_negative" not in data
    assert "reviews_wishlist" not in data


def test_main_exits_2_when_competitors_json_missing(monkeypatch, tmp_path, capsys):
    """No competitors_<slug>.json → exit 2 + clear message pointing at /appmate-competitors."""
    import feature_ideate as fi

    apps_full = tmp_path / "apps_full.json"
    sales = tmp_path / "sales_cache.json"

    apps_full.write_text(json.dumps({"apps": [{
        "id": "111",
        "core": {"name": "DemoApp", "bundleId": "com.demo", "primaryLocale": "en-US"},
        "appInfo": {"localizations": []},
        "reviews": {"count": 0, "averageRating": 0, "reviews": []},
    }]}))
    sales.write_text("{}")

    monkeypatch.setattr(fi, "APPS_FULL_PATH", apps_full)
    monkeypatch.setattr(fi, "SALES_CACHE_PATH", sales)
    monkeypatch.setattr(fi, "OUTPUT_DIR", tmp_path)

    rc = fi.main(["DemoApp"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "competitors JSON not found" in err
    assert "/appmate-competitors" in err


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
