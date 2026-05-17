"""Tests for the SessionStart update-check hook."""
from __future__ import annotations

import importlib
import io
import json
import pathlib
import time

import pytest

import check_for_update


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Pin CLAUDE_PLUGIN_ROOT / CLAUDE_PLUGIN_DATA to fresh dirs per test."""
    plugin_root = tmp_path / "plugin"
    data_dir = tmp_path / "data"
    plugin_root.mkdir()
    data_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data_dir))
    return plugin_root, data_dir


def _patch_shas(monkeypatch, *, local: str | None, remote: str | None) -> None:
    monkeypatch.setattr(check_for_update, "_local_sha", lambda root: local)
    monkeypatch.setattr(check_for_update, "_remote_sha", lambda: remote)


# --- check() verdict shape -----------------------------------------------
def test_up_to_date_has_no_message(isolated_env, monkeypatch):
    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    result = check_for_update.check(force=True)
    assert result["status"] == "up_to_date"
    assert result["message"] is None
    assert result["source"] == "fresh"


def test_outdated_banner_includes_short_shas_and_repo(isolated_env, monkeypatch):
    _patch_shas(monkeypatch, local="a" * 40, remote="b" * 40)
    result = check_for_update.check(force=True)
    assert result["status"] == "outdated"
    msg = result["message"]
    assert "out of date" in msg
    assert "aaaaaaa" in msg
    assert "bbbbbbb" in msg
    assert "/plugin" in msg
    assert check_for_update.REPO in msg


def test_missing_local_sha_returns_unknown(isolated_env, monkeypatch):
    _patch_shas(monkeypatch, local=None, remote="b" * 40)
    result = check_for_update.check(force=True)
    assert result["status"] == "unknown"
    assert result["source"] == "skipped"
    assert result["message"] is None


def test_missing_remote_sha_returns_unknown(isolated_env, monkeypatch):
    _patch_shas(monkeypatch, local="a" * 40, remote=None)
    result = check_for_update.check(force=True)
    assert result["status"] == "unknown"
    assert result["source"] == "skipped"
    assert result["message"] is None


# --- Cache behaviour ------------------------------------------------------
def test_cache_hit_skips_network_call(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_sha": "a" * 40,
                "remote_sha": "b" * 40,
                "checked_at": time.time(),
            }
        )
    )

    calls = {"remote": 0}

    def fake_remote():
        calls["remote"] += 1
        return None

    monkeypatch.setattr(check_for_update, "_local_sha", lambda root: "a" * 40)
    monkeypatch.setattr(check_for_update, "_remote_sha", fake_remote)

    result = check_for_update.check(force=False)
    assert result["source"] == "cache"
    assert result["status"] == "outdated"
    assert calls["remote"] == 0


def test_cache_expired_triggers_refetch(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_sha": "a" * 40,
                "remote_sha": "b" * 40,
                "checked_at": time.time() - (check_for_update.CACHE_TTL_SECONDS + 60),
            }
        )
    )

    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_cache_invalid_when_local_sha_changes(isolated_env, monkeypatch):
    """A fresh /plugin update bumps local SHA; the stale cache entry must be dropped."""
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_sha": "old0000000000000000000000000000000000000",
                "remote_sha": "b" * 40,
                "checked_at": time.time(),
            }
        )
    )

    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_corrupt_cache_file_is_ignored(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    (data_dir / "update_check.json").write_text("not json {{{")

    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"


def test_force_bypasses_fresh_cache(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_sha": "a" * 40,
                "remote_sha": "b" * 40,
                "checked_at": time.time(),
            }
        )
    )

    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    result = check_for_update.check(force=True)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_successful_check_writes_cache(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    assert not cache_file.exists()

    _patch_shas(monkeypatch, local="a" * 40, remote="b" * 40)
    check_for_update.check(force=True)

    cache = json.loads(cache_file.read_text())
    assert cache["local_sha"] == "a" * 40
    assert cache["remote_sha"] == "b" * 40
    assert isinstance(cache["checked_at"], (int, float))


# --- run_hook entrypoint --------------------------------------------------
def test_hook_emits_systemmessage_when_outdated(isolated_env, monkeypatch, capsys):
    _patch_shas(monkeypatch, local="a" * 40, remote="b" * 40)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event": "SessionStart"}'))

    with pytest.raises(SystemExit) as exc:
        check_for_update.run_hook()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "systemMessage" in payload
    assert "out of date" in payload["systemMessage"]


def test_hook_silent_when_up_to_date(isolated_env, monkeypatch, capsys):
    _patch_shas(monkeypatch, local="a" * 40, remote="a" * 40)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event": "SessionStart"}'))

    with pytest.raises(SystemExit) as exc:
        check_for_update.run_hook()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert out == ""


def test_hook_silent_on_unknown_status(isolated_env, monkeypatch, capsys):
    """Network failures (remote=None) must not surface any banner."""
    _patch_shas(monkeypatch, local="a" * 40, remote=None)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event": "SessionStart"}'))

    with pytest.raises(SystemExit) as exc:
        check_for_update.run_hook()
    assert exc.value.code == 0
    assert capsys.readouterr().out == ""


# --- Plugin-root / cache-path resolution ---------------------------------
def test_plugin_root_prefers_env(isolated_env):
    plugin_root, _ = isolated_env
    assert check_for_update._plugin_root() == plugin_root


def test_cache_path_prefers_plugin_data_env(isolated_env):
    _, data_dir = isolated_env
    assert check_for_update._cache_path() == data_dir / "update_check.json"


def test_cache_path_falls_back_when_env_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    expected = check_for_update._DEFAULT_PLUGIN_ROOT / "data" / "update_check.json"
    assert check_for_update._cache_path() == expected
