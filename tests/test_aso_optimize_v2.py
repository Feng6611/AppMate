"""Tests for aso_optimize_v2."""
from __future__ import annotations

import pathlib
import sys

# Ensure repo root is importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def test_module_imports():
    """Smoke: module imports without errors."""
    import aso_optimize_v2  # noqa: F401


import json


APP_FIXTURES = {
    "apps": [
        {
            "id": "6737885863",
            "core": {
                "name": "GBrowser:Choose Link Openly",
                "bundleId": "com.soloware.opnelink",
                "sku": "OpenLink",
            },
        },
        {
            "id": "1482080766",
            "core": {
                "name": "Sticky Note Pro: Post-it&Memo",
                "bundleId": "com.fengyiqi.PostItnoteForMac",
                "sku": "PostItNote",
            },
        },
    ]
}


def test_find_app_by_app_id():
    from aso_optimize_v2 import find_app
    app = find_app("6737885863", apps=APP_FIXTURES["apps"])
    assert app["id"] == "6737885863"


def test_find_app_by_bundle_id():
    from aso_optimize_v2 import find_app
    app = find_app("com.fengyiqi.PostItnoteForMac", apps=APP_FIXTURES["apps"])
    assert app["id"] == "1482080766"


def test_find_app_by_sku():
    from aso_optimize_v2 import find_app
    app = find_app("OpenLink", apps=APP_FIXTURES["apps"])
    assert app["id"] == "6737885863"


def test_find_app_by_name_substring_case_insensitive():
    from aso_optimize_v2 import find_app
    app = find_app("sticky note", apps=APP_FIXTURES["apps"])
    assert app["id"] == "1482080766"


def test_find_app_returns_none_for_no_match():
    from aso_optimize_v2 import find_app
    assert find_app("nonexistent app xyz", apps=APP_FIXTURES["apps"]) is None


def test_slugify_ascii_name():
    from aso_optimize_v2 import slugify
    assert slugify("GBrowser:Choose Link Openly", "CN") == "gbrowser_cn"


def test_slugify_cjk_name():
    """Pure CJK name → fall back to bundleId-style slug or 'app'."""
    from aso_optimize_v2 import slugify
    # When no ASCII word found, use 'app'
    assert slugify("锁屏头条", "CN") == "app_cn"


def test_slugify_mixed():
    from aso_optimize_v2 import slugify
    assert slugify("Sticky Note Pro: Post-it&Memo", "US") == "sticky_us"


def test_slugify_lowercases_country():
    from aso_optimize_v2 import slugify
    assert slugify("Mirror:Face Camera", "MX") == "mirror_mx"


def _sample_app():
    return {
        "id": "6737885863",
        "core": {
            "name": "GBrowser:Choose Link Openly",
            "bundleId": "com.soloware.opnelink",
        },
        "appInfo": {
            "localizations": [
                {
                    "locale": "zh-Hans",
                    "name": "G浏览器",
                    "subtitle": "多浏览器一键切换",
                }
            ]
        },
        "versions": [
            {
                "attributes": {
                    "createdDate": "2026-04-01T00:00:00Z",
                    "platform": "MAC_OS",
                },
                "localizations": [
                    {
                        "locale": "zh-Hans",
                        "keywords": "谷歌浏览器,chrome,firefox,MacOS,app",
                    }
                ],
            }
        ],
    }


def test_collect_tokens_basic():
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    keys = {t["keyword"].lower() for t in tokens}
    # Should include chrome / firefox / 谷歌浏览器 / G浏览器 / 多浏览器一键切换 broken into parts
    assert "chrome" in keys
    assert "firefox" in keys
    assert "谷歌浏览器" in keys


def test_collect_tokens_filters_junk():
    """MacOS and 'app' should be filtered by _good_token (Latin stopword + 4-char tech words)."""
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    keys = {t["keyword"].lower() for t in tokens}
    # 'app' is a stopword; 'macos' has cjk=0 + len > 2 + lowercase + stopword check passes (5 chars)
    # But it's in our reject set (mac is in the stopword set, but MacOS won't match exactly)
    # We expect 'app' to be filtered
    assert "app" not in keys


def test_collect_tokens_has_source_tags():
    from aso_optimize_v2 import collect_tokens
    tokens = collect_tokens(_sample_app(), info_loc="zh-Hans", ver_loc="zh-Hans")
    chrome = next((t for t in tokens if t["keyword"].lower() == "chrome"), None)
    assert chrome is not None
    assert "K" in chrome["source"]  # came from keywords field


def test_build_phase_a_shape():
    """build_phase_a accepts pre-resolved data and returns the documented JSON shape."""
    from aso_optimize_v2 import build_phase_a

    app = _sample_app()
    captured_pop_store: list[str] = []

    def fake_pop(kws, store):
        captured_pop_store.append(store)
        return {kw: {"popularity": 72, "difficulty": 79} for kw in kws}

    result = build_phase_a(
        app=app,
        market="CN",
        info_loc="zh-Hans",
        ver_loc="zh-Hans",
        downloads_30d=25147,
        rank_fn=lambda kw, country, entity, bid: {"chrome": 1, "firefox": 9, "谷歌浏览器": 1}.get(kw),
        pop_fn=fake_pop,
    )

    # Top-level keys
    for k in ("app", "app_id", "bundle_id", "platform", "market", "locale",
              "downloads_30d_in_market", "current_metadata", "current_tokens",
              "generated_at"):
        assert k in result, f"missing key: {k}"

    # Identity
    assert result["app_id"] == "6737885863"
    assert result["bundle_id"] == "com.soloware.opnelink"
    assert result["platform"] == "macOS"
    assert result["market"] == "CN"
    assert result["locale"] == "zh-Hans"
    assert result["downloads_30d_in_market"] == 25147

    # pop_fn was called with lowercased market
    assert captured_pop_store and captured_pop_store[0] == "cn"

    # current_metadata
    assert result["current_metadata"]["title"] == "G浏览器"
    assert result["current_metadata"]["subtitle"] == "多浏览器一键切换"
    assert "chrome" in result["current_metadata"]["keywords"]

    # current_tokens schema
    chrome_row = next(t for t in result["current_tokens"] if t["keyword"] == "chrome")
    assert chrome_row["rank"] == 1
    assert chrome_row["popularity"] == 72
    assert chrome_row["difficulty"] == 79
    assert isinstance(chrome_row["source"], list)


def test_write_json_round_trip(tmp_path):
    """write_json writes UTF-8 with ensure_ascii=False, round-trips intact."""
    from aso_optimize_v2 import write_json

    p = tmp_path / "out.json"
    data = {"k": "谷歌浏览器", "n": 42}
    write_json(p, data)

    text = p.read_text()
    assert "谷歌浏览器" in text  # not escaped
    assert json.loads(text) == data


def test_cmd_analyze_writes_phase_a(tmp_path, monkeypatch):
    """Run cmd_analyze end-to-end with mocked network. File appears with correct shape."""
    import aso_optimize_v2 as v2
    import keyword_local
    import appmate_config

    # Point outputs at tmp_path
    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    monkeypatch.setattr(v2, "SALES_CACHE", tmp_path / "sales_cache.json")

    # Minimal fixtures
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))
    (tmp_path / "sales_cache.json").write_text(json.dumps({
        # One day of sales in CN for this app
        "2026-05-10": [{
            "Title": "GBrowser:Choose Link Openly",
            "Country Code": "CN",
            "Product Type Identifier": "F1",
            "Units": "1875",
        }] * 1
    }))

    # Mock the two IO functions
    monkeypatch.setattr(v2, "itunes_rank",
                        lambda kw, country, entity, bid, cache=None: 1 if kw == "chrome" else None)
    monkeypatch.setattr(keyword_local, "lookup_popularity_batch",
                        lambda kws, store: {kw: {"popularity": 70, "difficulty": 50, "appsCount": 100} for kw in kws})

    # Also mock find_top_market to skip the 30-day rolling math
    monkeypatch.setattr(v2, "find_top_market",
                        lambda name, reports, today: ("CN", 25147))
    monkeypatch.setattr(v2, "pick_locales_for_country",
                        lambda country, infos, vers: ("zh-Hans", "zh-Hans", True))

    # Run the command
    exit_code = v2.cmd_analyze("6737885863")
    assert exit_code == 0

    out_path = tmp_path / "phase_a_gbrowser_cn.json"
    assert out_path.exists()

    payload = json.loads(out_path.read_text())
    assert payload["app_id"] == "6737885863"
    assert payload["market"] == "CN"
    assert payload["downloads_30d_in_market"] == 25147
    assert any(t["keyword"] == "chrome" and t["rank"] == 1 for t in payload["current_tokens"])


def test_parse_candidates_arg_basic():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg("kw1,kw2,kw3") == ["kw1", "kw2", "kw3"]


def test_parse_candidates_arg_strips_whitespace():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg(" foo , bar , baz ") == ["foo", "bar", "baz"]


def test_parse_candidates_arg_dedup_preserves_first_seen():
    from aso_optimize_v2 import parse_candidates_arg
    assert parse_candidates_arg("a,b,A,c,b") == ["a", "b", "c"]


def test_parse_candidates_arg_caps_at_30():
    from aso_optimize_v2 import parse_candidates_arg
    big = ",".join(f"kw{i}" for i in range(50))
    assert len(parse_candidates_arg(big)) == 30


def test_build_phase_b_shape():
    from aso_optimize_v2 import build_phase_b

    app = _sample_app()
    result = build_phase_b(
        app=app,
        market="CN",
        candidates=["谷歌地图", "翻译"],
        rank_fn=lambda kw, c, e, b: 2 if kw == "谷歌地图" else None,
        pop_fn=lambda kws, store: {
            "谷歌地图": {"popularity": 74, "difficulty": 25},
            "翻译": {"popularity": 75, "difficulty": 76},
        },
    )

    assert result["app_id"] == "6737885863"
    assert result["market"] == "CN"
    assert len(result["candidates"]) == 2

    map_row = next(c for c in result["candidates"] if c["keyword"] == "谷歌地图")
    assert map_row["rank"] == 2
    assert map_row["popularity"] == 74
    assert map_row["difficulty"] == 25

    trans_row = next(c for c in result["candidates"] if c["keyword"] == "翻译")
    assert trans_row["rank"] is None
    assert trans_row["popularity"] == 75


def test_cmd_validate_writes_phase_b(tmp_path, monkeypatch):
    import aso_optimize_v2 as v2
    import keyword_local
    import appmate_config

    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    monkeypatch.setattr(v2, "SALES_CACHE", tmp_path / "sales_cache.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))
    (tmp_path / "sales_cache.json").write_text(json.dumps({}))

    monkeypatch.setattr(v2, "itunes_rank",
                        lambda kw, country, entity, bid, cache=None: 2 if kw == "谷歌地图" else None)
    monkeypatch.setattr(keyword_local, "lookup_popularity_batch",
                        lambda kws, store: {kw: {"popularity": 74, "difficulty": 25} for kw in kws})

    # find_top_market needs to return a market without real sales
    monkeypatch.setattr(v2, "find_top_market",
                        lambda name, reports, today: ("CN", 0))

    exit_code = v2.cmd_validate("6737885863", "谷歌地图,翻译")
    assert exit_code == 0

    out_path = tmp_path / "phase_b_gbrowser_cn.json"
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["keyword"] == "谷歌地图"
    assert payload["candidates"][0]["rank"] == 2


def test_cmd_show_a_prints_summary(tmp_path, monkeypatch, capsys):
    import aso_optimize_v2 as v2
    import appmate_config
    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))

    # Fake a phase_a file
    phase_a = {
        "app": "GBrowser:Choose Link Openly",
        "app_id": "6737885863",
        "market": "CN",
        "locale": "zh-Hans",
        "downloads_30d_in_market": 25147,
        "current_metadata": {"title": "G浏览器", "subtitle": "...", "keywords": "..."},
        "current_tokens": [
            {"keyword": "chrome", "source": ["K"], "rank": 1, "popularity": 72, "difficulty": 79},
            {"keyword": "junk", "source": ["K"], "rank": None, "popularity": 5, "difficulty": 80},
        ],
        "generated_at": "2026-05-13T00:00:00+08:00",
    }
    (tmp_path / "phase_a_gbrowser_cn.json").write_text(json.dumps(phase_a, ensure_ascii=False))

    exit_code = v2.cmd_show_a("6737885863")
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "GBrowser" in out
    assert "CN" in out
    assert "chrome" in out
    assert "25,147" in out or "25147" in out


def test_cmd_show_a_handles_missing_file(tmp_path, monkeypatch, capsys):
    import aso_optimize_v2 as v2
    import appmate_config
    monkeypatch.setattr(appmate_config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(v2, "APPS_FULL", tmp_path / "apps_full.json")
    (tmp_path / "apps_full.json").write_text(json.dumps({"apps": [_sample_app()]}, ensure_ascii=False))

    exit_code = v2.cmd_show_a("6737885863")
    assert exit_code != 0  # exit non-zero because no phase_a file
    out = capsys.readouterr()
    assert "no phase_a" in (out.err + out.out).lower() or "not found" in (out.err + out.out).lower()


def test_main_dispatches_analyze(tmp_path, monkeypatch):
    """main(['analyze', '<app>']) routes to cmd_analyze."""
    import aso_optimize_v2 as v2

    called = {}
    def fake_analyze(query):
        called["analyze"] = query
        return 0
    monkeypatch.setattr(v2, "cmd_analyze", fake_analyze)

    exit_code = v2.main(["analyze", "GBrowser"])
    assert exit_code == 0
    assert called.get("analyze") == "GBrowser"


def test_main_dispatches_validate(monkeypatch):
    import aso_optimize_v2 as v2
    called = {}
    def fake_validate(query, candidates):
        called["validate"] = (query, candidates)
        return 0
    monkeypatch.setattr(v2, "cmd_validate", fake_validate)

    exit_code = v2.main(["validate", "GBrowser", "--candidates", "a,b,c"])
    assert exit_code == 0
    assert called["validate"] == ("GBrowser", "a,b,c")


def test_main_help_returns_zero(capsys):
    import aso_optimize_v2 as v2
    exit_code = v2.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "analyze" in out
    assert "validate" in out


def test_main_unknown_command_returns_nonzero(capsys):
    import aso_optimize_v2 as v2
    exit_code = v2.main(["bogus"])
    assert exit_code != 0
