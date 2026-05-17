"""SessionStart hook: notify the user when AppMate is behind upstream main.

Wired in ``hooks/hooks.json`` against the ``startup`` and ``resume`` matchers,
so Claude Code runs it once at the top of every fresh session (and on resume
of a saved one). Compares the local plugin's HEAD commit against the latest
commit on ``github.com/fengyiqicoder/AppMate@main`` and, when they differ,
emits a one-line ``{"systemMessage": ...}`` banner pointing the user at
``/plugin`` to upgrade.

Failure policy: always exit 0. A missing ``git`` binary, a non-git plugin
directory, a network outage, or a GitHub rate-limit must never block the
session — the worst we do is stay silent.

Cache: the verdict is stored in ``${CLAUDE_PLUGIN_DATA}/update_check.json``
(falling back to ``data/update_check.json`` under the plugin root) for 24 h,
keyed by the local SHA. A fresh ``/plugin update`` advances the local SHA and
invalidates the cache immediately, so the next session re-checks instead of
showing a stale "you're behind" banner.

CLI
---
    python3 scripts/check_for_update.py check
        Force a fresh check, ignore cache. Prints the verdict JSON to stderr
        for manual debugging. Always exits 0.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

REPO = "fengyiqicoder/AppMate"
BRANCH = "main"
CACHE_TTL_SECONDS = 24 * 3600
HTTP_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 5

# When invoked as a hook, Claude Code sets CLAUDE_PLUGIN_ROOT to the install
# directory. When invoked from a checkout (CLI, tests), fall back to the repo
# that contains this script.
_DEFAULT_PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _plugin_root() -> pathlib.Path:
    return pathlib.Path(
        os.environ.get("CLAUDE_PLUGIN_ROOT", str(_DEFAULT_PLUGIN_ROOT))
    )


def _cache_path() -> pathlib.Path:
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data_dir:
        return pathlib.Path(data_dir) / "update_check.json"
    return _DEFAULT_PLUGIN_ROOT / "data" / "update_check.json"


# --- SHA lookup -----------------------------------------------------------
def _local_sha(root: pathlib.Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    sha = out.decode("ascii", errors="replace").strip()
    return sha or None


def _remote_sha() -> str | None:
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    sha = payload.get("sha") if isinstance(payload, dict) else None
    return sha if isinstance(sha, str) and sha else None


# --- Cache ----------------------------------------------------------------
def _read_cache(path: pathlib.Path, local_sha: str) -> str | None:
    try:
        raw = path.read_text()
    except OSError:
        return None
    try:
        cache = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(cache, dict):
        return None
    if cache.get("local_sha") != local_sha:
        return None
    try:
        age = time.time() - float(cache.get("checked_at", 0))
    except (TypeError, ValueError):
        return None
    if age > CACHE_TTL_SECONDS:
        return None
    remote = cache.get("remote_sha")
    return remote if isinstance(remote, str) and remote else None


def _write_cache(path: pathlib.Path, local_sha: str, remote_sha: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "local_sha": local_sha,
                    "remote_sha": remote_sha,
                    "checked_at": time.time(),
                }
            )
        )
    except OSError:
        pass


# --- Verdict --------------------------------------------------------------
def _format_banner(local_sha: str, remote_sha: str) -> str:
    return (
        f"AppMate is out of date "
        f"(installed {local_sha[:7]} -> latest {remote_sha[:7]} on github.com/{REPO}). "
        "Run `/plugin` and update appmate to pull the newest skills, commands, and fixes."
    )


def _verdict(local: str, remote: str, *, source: str) -> dict[str, Any]:
    if local == remote:
        return {
            "status": "up_to_date",
            "local_sha": local,
            "remote_sha": remote,
            "source": source,
            "message": None,
        }
    return {
        "status": "outdated",
        "local_sha": local,
        "remote_sha": remote,
        "source": source,
        "message": _format_banner(local, remote),
    }


def check(*, force: bool = False) -> dict[str, Any]:
    """Compute the update verdict. Pure function shape for testing.

    Returns a dict with keys:
        status     "up_to_date" | "outdated" | "unknown"
        local_sha  str | None
        remote_sha str | None
        source     "cache" | "fresh" | "skipped"
        message    str | None   (banner text when status == "outdated")
    """
    local = _local_sha(_plugin_root())
    if local is None:
        return {
            "status": "unknown",
            "local_sha": None,
            "remote_sha": None,
            "source": "skipped",
            "message": None,
        }

    cache_path = _cache_path()
    if not force:
        cached_remote = _read_cache(cache_path, local)
        if cached_remote is not None:
            return _verdict(local, cached_remote, source="cache")

    remote = _remote_sha()
    if remote is None:
        return {
            "status": "unknown",
            "local_sha": local,
            "remote_sha": None,
            "source": "skipped",
            "message": None,
        }

    _write_cache(cache_path, local, remote)
    return _verdict(local, remote, source="fresh")


# --- Entry points ---------------------------------------------------------
def run_hook() -> None:
    """SessionStart hook entrypoint. Read stdin, emit JSON if outdated, exit 0."""
    try:
        sys.stdin.read()
    except OSError:
        pass

    result = check()
    message = result.get("message")
    if message:
        sys.stdout.write(json.dumps({"systemMessage": message}))
    sys.exit(0)


def _cli() -> None:
    """``check`` subcommand: force a fresh verdict, print it to stderr."""
    result = check(force=True)
    sys.stderr.write(json.dumps(result, indent=2) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        _cli()
    else:
        run_hook()
