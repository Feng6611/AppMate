import importlib
import pathlib

import appmate_config


def _fresh(monkeypatch, home: pathlib.Path):
    monkeypatch.setenv("APPMATE_HOME", str(home))
    mod = importlib.reload(appmate_config)
    return mod


def test_paths_resolve_under_appmate_home(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg.DATA_DIR == tmp_path / "data"
    assert cfg.CONFIG_DIR == tmp_path / "config"


def test_data_path_creates_data_dir(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    p = cfg.data_path("x.json")
    assert p == tmp_path / "data" / "x.json"
    assert (tmp_path / "data").is_dir()


def test_load_config_missing_file_returns_empty(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg._load_config() == {}


def test_load_config_parses_and_skips_comments(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text(
        "# comment\nissuer_id = abc\n\nvendor_number = 123\n"
    )
    parsed = cfg._load_config()
    assert parsed == {"issuer_id": "abc", "vendor_number": "123"}


def test_url_accessors_have_defaults(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg.rag_base_url() == "https://appmate.000ooo.ooo"


def test_require_raises_pointing_to_setup(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    try:
        cfg.asc_issuer_id()
    except RuntimeError as e:
        assert "appmate-setup" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_accessors_return_values_when_present(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text(
        "issuer_id=i\nkey_id=k\nvendor_number=v\nprivate_key_path=config/key.p8\n"
    )
    assert cfg.asc_issuer_id() == "i"
    assert cfg.asc_key_id() == "k"
    assert cfg.asc_vendor_number() == "v"
    assert cfg.asc_private_key_path() == tmp_path / "config" / "key.p8"
