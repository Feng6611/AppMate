"""Tests for the App Store Connect API key role-safety probe."""
from __future__ import annotations

import importlib
import io
import json
import pathlib
import time

import pytest

import key_safety
import appmate_config


# ----------------------------------------------------------------------------
# Test helpers
# ----------------------------------------------------------------------------
def _fresh(monkeypatch, home: pathlib.Path):
    """Reload appmate_config + key_safety against a clean APPMATE_HOME.

    Reloading restores the real ``require_safe_key_or_exit`` function for the
    duration of the test, overriding the conftest autouse no-op.
    """
    monkeypatch.setenv("APPMATE_HOME", str(home))
    cfg = importlib.reload(appmate_config)
    ks = importlib.reload(key_safety)
    return cfg, ks


def _write_full_creds(home: pathlib.Path) -> None:
    cfg_dir = home / "config"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "credentials.txt").write_text(
        "issuer_id=i\nkey_id=k\nvendor_number=v\nprivate_key_path=config/key.p8\n"
    )
    (cfg_dir / "key.p8").write_text("-----BEGIN PRIVATE KEY-----\nstub\n")


# Endpoint set used by detect_elevated_roles after the v2 probe redesign.
_PROBE_ENDPOINTS = ("/v1/bundleIds", "/v1/financeReports")


def _patch_probe(ks, monkeypatch, statuses: dict[str, int]) -> list[str]:
    """Replace ks._probe with a stub that returns the mapped status by path."""
    calls: list[str] = []

    def fake(path, params=None):
        calls.append(path)
        return statuses.get(path, 200)

    monkeypatch.setattr(ks, "_probe", fake)
    return calls


def _all_safe() -> dict[str, int]:
    """Probe map for a read-only key: every endpoint denies."""
    return {p: 403 for p in _PROBE_ENDPOINTS}


# ----------------------------------------------------------------------------
# detect_elevated_roles
# ----------------------------------------------------------------------------
def test_detect_all_safe_when_403_everywhere(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    result = ks.detect_elevated_roles()
    assert result["roles"] == {
        "DEVELOPER_OR_ADMIN": False,
        "FINANCE_OR_ADMIN": False,
    }
    assert result["probe_failed"] is False


def test_detect_developer_or_admin_when_bundleids_200(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 200,
        "/v1/financeReports": 403,
    })
    result = ks.detect_elevated_roles()
    assert result["roles"]["DEVELOPER_OR_ADMIN"] is True
    assert result["roles"]["FINANCE_OR_ADMIN"] is False


def test_detect_finance_when_finance_200_or_404(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    for status in (200, 404):  # 404 = no data for the period, but call was authorized
        _patch_probe(ks, monkeypatch, {
            "/v1/bundleIds": 403,
            "/v1/financeReports": status,
        })
        result = ks.detect_elevated_roles()
        assert result["roles"]["FINANCE_OR_ADMIN"] is True, (
            f"finance status {status} should flag"
        )
        assert result["roles"]["DEVELOPER_OR_ADMIN"] is False


def test_detect_admin_flags_both_when_everything_open(monkeypatch, tmp_path):
    """An Admin key passes every probe — both flags fire (each independently
    sufficient to refuse service)."""
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 200,
        "/v1/financeReports": 200,
    })
    result = ks.detect_elevated_roles()
    assert result["roles"]["DEVELOPER_OR_ADMIN"] is True
    assert result["roles"]["FINANCE_OR_ADMIN"] is True


def test_detect_probe_failed_when_any_minus_one(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 403,
        "/v1/financeReports": -1,
    })
    result = ks.detect_elevated_roles()
    assert result["probe_failed"] is True


# ----------------------------------------------------------------------------
# assess_key_safety  (caching + safe / unsafe / probe_failed branches)
# ----------------------------------------------------------------------------
def test_assess_returns_safe_for_clean_key(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    result = ks.assess_key_safety()
    assert result["safe"] is True
    assert result["unsafe_roles"] == []
    assert result["source"] == "fresh"


def test_assess_returns_unsafe_with_role_descriptions(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 200,
        "/v1/financeReports": 200,
    })
    result = ks.assess_key_safety()
    assert result["safe"] is False
    # Both messages must be surfaced.
    joined = " · ".join(result["unsafe_roles"])
    assert "Developer or Admin" in joined
    assert "Finance or Admin" in joined
    assert result["source"] == "fresh"


def test_assess_caches_within_ttl(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    calls = _patch_probe(ks, monkeypatch, _all_safe())
    first = ks.assess_key_safety()
    assert first["source"] == "fresh"
    second = ks.assess_key_safety()
    assert second["source"] == "cache"
    # Probe should have been called once per endpoint for the first assessment only.
    assert calls == list(_PROBE_ENDPOINTS)


def test_assess_reprobes_when_cache_stale(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    ks.assess_key_safety()
    stale = json.loads(ks.CACHE_PATH.read_text())
    stale["ts"] = time.time() - (8 * 24 * 3600)
    ks.CACHE_PATH.write_text(json.dumps(stale))
    second = ks.assess_key_safety()
    assert second["source"] == "fresh"


def test_assess_does_not_cache_probe_failures(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {p: -1 for p in _PROBE_ENDPOINTS})
    result = ks.assess_key_safety()
    assert result["source"] == "probe_failed"
    assert result["safe"] is False
    assert not ks.CACHE_PATH.exists()


def test_assess_force_skips_cache(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    ks.assess_key_safety()
    second = ks.assess_key_safety(force=True)
    assert second["source"] == "fresh"


# ----------------------------------------------------------------------------
# require_safe_key_or_exit
# ----------------------------------------------------------------------------
def test_require_safe_passes_for_safe_key(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    assert ks.require_safe_key_or_exit() is None


def test_require_safe_exits_when_credentials_missing(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        ks.require_safe_key_or_exit(stream=buf)
    assert exc.value.code == 2
    assert "not fully configured" in buf.getvalue()


def test_require_safe_exits_on_unsafe_role_with_recovery_steps(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 200,
        "/v1/financeReports": 200,
    })
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        ks.require_safe_key_or_exit(stream=buf)
    assert exc.value.code == 2
    msg = buf.getvalue()
    assert "refuses to run" in msg
    assert "Developer or Admin" in msg
    assert "Finance or Admin" in msg
    assert "Sales and Reports" in msg  # recovery guidance mentions the safe roles
    assert "Revoke" in msg


def test_require_safe_exits_on_probe_failure(monkeypatch, tmp_path):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {p: -1 for p in _PROBE_ENDPOINTS})
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        ks.require_safe_key_or_exit(stream=buf)
    assert exc.value.code == 2
    assert "Could not reach App Store Connect" in buf.getvalue()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def test_cli_probe_returns_0_when_safe(monkeypatch, tmp_path, capsys):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    assert ks._cli(["probe"]) == 0
    out = capsys.readouterr().out
    assert "SAFE" in out


def test_cli_probe_returns_2_when_unsafe(monkeypatch, tmp_path, capsys):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, {
        "/v1/bundleIds": 200,
        "/v1/financeReports": 200,
    })
    assert ks._cli(["probe"]) == 2
    out = capsys.readouterr().out
    assert "UNSAFE" in out


def test_cli_status_returns_1_when_no_cache(monkeypatch, tmp_path, capsys):
    _, ks = _fresh(monkeypatch, tmp_path)
    assert ks._cli(["status"]) == 1
    err = capsys.readouterr().err
    assert "No cached safety assessment" in err


def test_cli_status_reads_cached_verdict(monkeypatch, tmp_path, capsys):
    _, ks = _fresh(monkeypatch, tmp_path)
    _write_full_creds(tmp_path)
    _patch_probe(ks, monkeypatch, _all_safe())
    ks.assess_key_safety()  # populate cache
    assert ks._cli(["status"]) == 0


def test_cli_help_returns_1(monkeypatch, tmp_path, capsys):
    _, ks = _fresh(monkeypatch, tmp_path)
    assert ks._cli([]) == 1
    assert ks._cli(["-h"]) == 1
    err = capsys.readouterr().err
    assert "usage:" in err
