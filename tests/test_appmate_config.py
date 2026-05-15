import importlib
import io
import pathlib

import pytest

import appmate_config


def _fresh(monkeypatch, home: pathlib.Path):
    monkeypatch.setenv("APPMATE_HOME", str(home))
    mod = importlib.reload(appmate_config)
    return mod


def _write_full_creds(home: pathlib.Path, *, key_present: bool = True) -> None:
    """Populate a complete credentials.txt + optional .p8 under *home*."""
    cfg_dir = home / "config"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "credentials.txt").write_text(
        "issuer_id=i\nkey_id=k\nvendor_number=v\nprivate_key_path=config/key.p8\n"
    )
    if key_present:
        (cfg_dir / "key.p8").write_text("-----BEGIN PRIVATE KEY-----\nstub\n")


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


# --- credential_status / credentials_ok ----------------------------------
def test_credential_status_all_missing_when_no_file(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    status = cfg.credential_status()
    assert set(status.keys()) == set(cfg.REQUIRED_CRED_KEYS)
    assert all(v == "missing" for v in status.values())
    assert cfg.credentials_ok() is False


def test_credential_status_all_ok_when_complete(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    assert cfg.credential_status() == {k: "ok" for k in cfg.REQUIRED_CRED_KEYS}
    assert cfg.credentials_ok() is True


def test_credential_status_flags_missing_p8_file(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path, key_present=False)
    status = cfg.credential_status()
    assert status["private_key_path"] == "key_file_missing"
    # other three are still ok
    assert status["issuer_id"] == "ok"
    assert status["key_id"] == "ok"
    assert status["vendor_number"] == "ok"
    assert cfg.credentials_ok() is False


def test_credential_status_partial(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text(
        "issuer_id=i\nkey_id=\nvendor_number=v\n"  # key_id empty, private_key_path absent
    )
    status = cfg.credential_status()
    assert status["issuer_id"] == "ok"
    assert status["key_id"] == "missing"
    assert status["vendor_number"] == "ok"
    assert status["private_key_path"] == "missing"


# --- require_credentials_or_exit -----------------------------------------
def test_require_credentials_or_exit_passes_when_complete(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    # Must return None and not raise.
    assert cfg.require_credentials_or_exit() is None


def test_require_credentials_or_exit_exits_with_code_2(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        cfg.require_credentials_or_exit(stream=buf)
    assert exc.value.code == 2
    out = buf.getvalue()
    assert "not fully configured" in out
    assert "/appmate-setup" in out
    # All four missing keys should be enumerated.
    for key in cfg.REQUIRED_CRED_KEYS:
        assert key in out


def test_require_credentials_or_exit_lists_missing_p8(monkeypatch, tmp_path):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path, key_present=False)
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        cfg.require_credentials_or_exit(stream=buf)
    assert exc.value.code == 2
    out = buf.getvalue()
    assert "private_key_path" in out
    assert ".p8 file does not exist" in out


# --- CLI -----------------------------------------------------------------
def test_cli_check_returns_0_when_configured(monkeypatch, tmp_path, capsys):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    # The CLI also runs the online safety probe — stub it to "safe".
    import key_safety
    monkeypatch.setattr(
        key_safety,
        "assess_key_safety",
        lambda force=False: {
            "safe": True,
            "checked_at": "2026-05-16T00:00:00",
            "unsafe_roles": [],
            "probe": {},
            "source": "cache",
        },
    )
    assert cfg._cli(["check"]) == 0
    out = capsys.readouterr().out
    assert "credentials: ok" in out
    assert "SAFE" in out


def test_cli_check_returns_2_when_missing(monkeypatch, tmp_path, capsys):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg._cli(["check"]) == 2
    err = capsys.readouterr().err
    assert "NOT configured" in err
    assert "/appmate-setup" in err


def test_cli_check_returns_2_when_key_unsafe(monkeypatch, tmp_path, capsys):
    cfg = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    import key_safety
    monkeypatch.setattr(
        key_safety,
        "assess_key_safety",
        lambda force=False: {
            "safe": False,
            "checked_at": "2026-05-16T00:00:00",
            "unsafe_roles": ["Admin — full write access"],
            "probe": {"/v1/users": 200},
            "source": "fresh",
        },
    )
    # require_safe_key_or_exit normally re-reads assess_key_safety; the offline
    # check + assessment in _cli's branch is what we're exercising, so let
    # require_safe_key_or_exit raise to mimic the real flow.
    def fake_require(stream=None, force_probe=False):
        raise SystemExit(2)
    monkeypatch.setattr(key_safety, "require_safe_key_or_exit", fake_require)
    assert cfg._cli(["check"]) == 2


def test_cli_unknown_subcommand_returns_1(monkeypatch, tmp_path, capsys):
    cfg = _fresh(monkeypatch, tmp_path)
    assert cfg._cli([]) == 1
    assert cfg._cli(["bogus"]) == 1
    assert "usage:" in capsys.readouterr().err
