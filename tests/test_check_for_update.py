"""Tests for the SessionStart update-check hook."""
from __future__ import annotations

import io
import json
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


def _patch_versions(monkeypatch, *, local: str | None, remote: str | None) -> None:
    monkeypatch.setattr(check_for_update, "_local_version", lambda root: local)
    monkeypatch.setattr(check_for_update, "_remote_version", lambda: remote)


# --- _parse_version -------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.2.0", (0, 2, 0)),
        ("0.2.1", (0, 2, 1)),
        ("0.2.10", (0, 2, 10)),  # double-digit segment, not lexical
        ("1.0", (1, 0)),
        ("12.3.4.5", (12, 3, 4, 5)),
        ("0.3.0-rc1", (0, 3, 0)),  # pre-release suffix stripped at segment level
        ("", None),
        ("not-a-version", None),
        ("0..1", None),  # empty segment is invalid
        (None, None),
    ],
)
def test_parse_version(raw, expected):
    assert check_for_update._parse_version(raw) == expected


# --- _is_outdated ---------------------------------------------------------
@pytest.mark.parametrize(
    "local, remote, expected",
    [
        ("0.2.0", "0.2.1", True),          # patch behind
        ("0.2.0", "0.3.0", True),          # minor behind
        ("0.2.0", "1.0.0", True),          # major behind
        ("0.2.9", "0.2.10", True),         # numeric, not lexical compare
        ("0.2.1", "0.2.1", False),         # equal -> up to date
        ("0.2.1", "0.2.0", False),         # local ahead (dev worktree) -> up to date
        ("0.3.0", "0.2.99", False),
        ("garbage", "0.2.1", None),        # parse failure -> unknown
        ("0.2.1", "garbage", None),
    ],
)
def test_is_outdated(local, remote, expected):
    assert check_for_update._is_outdated(local, remote) is expected


# --- _local_version (manifest reader) -------------------------------------
def test_local_version_reads_manifest(tmp_path):
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"name": "appmate", "version": "0.4.2"}))
    assert check_for_update._local_version(tmp_path) == "0.4.2"


def test_local_version_returns_none_when_manifest_missing(tmp_path):
    assert check_for_update._local_version(tmp_path) is None


def test_local_version_returns_none_when_manifest_malformed(tmp_path):
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text("not json {{{")
    assert check_for_update._local_version(tmp_path) is None


def test_local_version_returns_none_when_version_field_missing(tmp_path):
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"name": "appmate"}))
    assert check_for_update._local_version(tmp_path) is None


def test_marketplace_install_path_works_even_without_git(tmp_path):
    """Regression: marketplace installs land under a non-git directory.
    The check must still succeed by reading the JSON manifest directly."""
    install_dir = tmp_path / "cache" / "appmate-marketplace" / "appmate" / "0.2.0"
    (install_dir / ".claude-plugin").mkdir(parents=True)
    (install_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "appmate", "version": "0.2.0"})
    )
    # No `.git` directory anywhere.
    assert not (install_dir / ".git").exists()
    assert check_for_update._local_version(install_dir) == "0.2.0"


# --- check() verdict shape ------------------------------------------------
def test_up_to_date_has_no_message(isolated_env, monkeypatch):
    _patch_versions(monkeypatch, local="0.2.1", remote="0.2.1")
    result = check_for_update.check(force=True)
    assert result["status"] == "up_to_date"
    assert result["message"] is None
    assert result["source"] == "fresh"


def test_local_ahead_of_remote_is_up_to_date(isolated_env, monkeypatch):
    """Dev worktree case: local has bumped to 0.3.0, master still on 0.2.1."""
    _patch_versions(monkeypatch, local="0.3.0", remote="0.2.1")
    result = check_for_update.check(force=True)
    assert result["status"] == "up_to_date"
    assert result["message"] is None


def test_outdated_banner_includes_versions_and_repo(isolated_env, monkeypatch):
    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.1")
    result = check_for_update.check(force=True)
    assert result["status"] == "outdated"
    msg = result["message"]
    assert "out of date" in msg
    assert "0.2.0" in msg
    assert "0.2.1" in msg
    assert "/plugin" in msg
    assert check_for_update.REPO in msg


def test_missing_local_version_returns_unknown(isolated_env, monkeypatch):
    _patch_versions(monkeypatch, local=None, remote="0.2.1")
    result = check_for_update.check(force=True)
    assert result["status"] == "unknown"
    assert result["source"] == "skipped"
    assert result["message"] is None


def test_missing_remote_version_returns_unknown(isolated_env, monkeypatch):
    _patch_versions(monkeypatch, local="0.2.0", remote=None)
    result = check_for_update.check(force=True)
    assert result["status"] == "unknown"
    assert result["source"] == "skipped"
    assert result["message"] is None


def test_unparseable_version_returns_unknown(isolated_env, monkeypatch):
    """Defensive: if upstream ships a weird version string, stay silent."""
    _patch_versions(monkeypatch, local="0.2.0", remote="garbage")
    result = check_for_update.check(force=True)
    assert result["status"] == "unknown"
    assert result["message"] is None


# --- Cache behaviour ------------------------------------------------------
def test_cache_hit_skips_network_call(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_version": "0.2.0",
                "remote_version": "0.2.1",
                "checked_at": time.time(),
            }
        )
    )

    calls = {"remote": 0}

    def fake_remote():
        calls["remote"] += 1
        return None

    monkeypatch.setattr(check_for_update, "_local_version", lambda root: "0.2.0")
    monkeypatch.setattr(check_for_update, "_remote_version", fake_remote)

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
                "local_version": "0.2.0",
                "remote_version": "0.2.1",
                "checked_at": time.time() - (check_for_update.CACHE_TTL_SECONDS + 60),
            }
        )
    )

    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.0")
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_cache_invalid_when_local_version_changes(isolated_env, monkeypatch):
    """A fresh /plugin update bumps local version; the stale cache entry must be dropped."""
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_version": "0.2.0",
                "remote_version": "0.2.1",
                "checked_at": time.time(),
            }
        )
    )

    _patch_versions(monkeypatch, local="0.2.1", remote="0.2.1")
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_corrupt_cache_file_is_ignored(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    (data_dir / "update_check.json").write_text("not json {{{")

    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.0")
    result = check_for_update.check(force=False)
    assert result["source"] == "fresh"


def test_force_bypasses_fresh_cache(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    cache_file.write_text(
        json.dumps(
            {
                "local_version": "0.2.0",
                "remote_version": "0.2.1",
                "checked_at": time.time(),
            }
        )
    )

    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.0")
    result = check_for_update.check(force=True)
    assert result["source"] == "fresh"
    assert result["status"] == "up_to_date"


def test_successful_check_writes_cache(isolated_env, monkeypatch):
    _, data_dir = isolated_env
    cache_file = data_dir / "update_check.json"
    assert not cache_file.exists()

    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.1")
    check_for_update.check(force=True)

    cache = json.loads(cache_file.read_text())
    assert cache["local_version"] == "0.2.0"
    assert cache["remote_version"] == "0.2.1"
    assert isinstance(cache["checked_at"], (int, float))


# --- run_hook entrypoint --------------------------------------------------
def test_hook_emits_systemmessage_when_outdated(isolated_env, monkeypatch, capsys):
    _patch_versions(monkeypatch, local="0.2.0", remote="0.2.1")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event": "SessionStart"}'))

    with pytest.raises(SystemExit) as exc:
        check_for_update.run_hook()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "systemMessage" in payload
    assert "out of date" in payload["systemMessage"]


def test_hook_silent_when_up_to_date(isolated_env, monkeypatch, capsys):
    _patch_versions(monkeypatch, local="0.2.1", remote="0.2.1")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"event": "SessionStart"}'))

    with pytest.raises(SystemExit) as exc:
        check_for_update.run_hook()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert out == ""


def test_hook_silent_on_unknown_status(isolated_env, monkeypatch, capsys):
    """Network failures (remote=None) must not surface any banner."""
    _patch_versions(monkeypatch, local="0.2.0", remote=None)
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
