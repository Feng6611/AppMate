"""SessionStart hook: notify the user when AppMate is behind upstream master.

Wired in ``hooks/hooks.json`` against the ``startup`` and ``resume`` matchers,
so Claude Code runs it once at the top of every fresh session (and on resume
of a saved one). Compares the local plugin's ``version`` field in
``.claude-plugin/plugin.json`` against the same file on
``github.com/fengyiqicoder/AppMate@master`` and, when the local version is
lower, emits a one-line ``{"systemMessage": ...}`` banner pointing the user
at ``/plugin`` to upgrade.

Why version, not git SHA: the plugin gets installed two different ways and
only one of them is a git checkout.

  * **Marketplace install** (the common case) lands under
    ``~/.claude/plugins/cache/<marketplace>/appmate/<version>/`` — that
    directory is **not a git repo**, so ``git rev-parse HEAD`` has no SHA to
    return and the old SHA-based check sat at ``status=unknown`` forever,
    silently never banner-ing anyone. Comparing the ``version`` string in
    ``plugin.json`` works for both install modes.
  * **Git checkout** (the dev/contributor case) still works fine — same file,
    same field, same comparison. If the local version is *ahead* of master
    (typical mid-development state) we treat it as up-to-date, never as
    outdated.

Failure policy: always exit 0. A missing manifest, a malformed version
string, a network outage, or a 404 on the raw URL must never block the
session — the worst we do is stay silent.

Cache: the verdict is stored in ``${CLAUDE_PLUGIN_DATA}/update_check.json``
(falling back to ``data/update_check.json`` under the plugin root) for 24 h,
keyed by the local version string. A fresh ``/plugin update`` lands a new
version and invalidates the cache immediately, so the next session re-checks
instead of showing a stale "you're behind" banner.

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
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

REPO = "fengyiqicoder/AppMate"
BRANCH = "master"
PLUGIN_MANIFEST_PATH = ".claude-plugin/plugin.json"
CACHE_TTL_SECONDS = 24 * 3600
HTTP_TIMEOUT_SECONDS = 5

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


# --- Version lookup -------------------------------------------------------
def _version_from_manifest_text(raw: str) -> str | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("version")
    return v if isinstance(v, str) and v else None


def _local_version(root: pathlib.Path) -> str | None:
    try:
        raw = (root / PLUGIN_MANIFEST_PATH).read_text()
    except OSError:
        return None
    return _version_from_manifest_text(raw)


def _remote_version() -> str | None:
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{PLUGIN_MANIFEST_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError):
        return None
    return _version_from_manifest_text(raw)


# --- Version comparison ---------------------------------------------------
_VERSION_SEGMENT = re.compile(r"^\d+")


def _parse_version(s: str) -> tuple[int, ...] | None:
    """``"0.2.10"`` -> ``(0, 2, 10)``. Pre-release suffix on a segment is
    stripped (``"0.3.0-rc1"`` -> ``(0, 3, 0)``). Returns ``None`` if any
    dotted segment has no leading integer."""
    if not isinstance(s, str) or not s:
        return None
    parts: list[int] = []
    for chunk in s.split("."):
        m = _VERSION_SEGMENT.match(chunk)
        if not m:
            return None
        parts.append(int(m.group()))
    return tuple(parts) if parts else None


def _is_outdated(local: str, remote: str) -> bool | None:
    """``True`` when local < remote, ``False`` when local >= remote (covers
    both equal and dev-worktree-ahead), ``None`` when either side fails to
    parse and we should fall back to unknown."""
    lt = _parse_version(local)
    rt = _parse_version(remote)
    if lt is None or rt is None:
        return None
    n = max(len(lt), len(rt))
    lp = lt + (0,) * (n - len(lt))
    rp = rt + (0,) * (n - len(rt))
    return lp < rp


# --- Cache ----------------------------------------------------------------
def _read_cache(path: pathlib.Path, local_version: str) -> str | None:
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
    if cache.get("local_version") != local_version:
        return None
    try:
        age = time.time() - float(cache.get("checked_at", 0))
    except (TypeError, ValueError):
        return None
    if age > CACHE_TTL_SECONDS:
        return None
    remote = cache.get("remote_version")
    return remote if isinstance(remote, str) and remote else None


def _write_cache(path: pathlib.Path, local_version: str, remote_version: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "local_version": local_version,
                    "remote_version": remote_version,
                    "checked_at": time.time(),
                }
            )
        )
    except OSError:
        pass


# --- Verdict --------------------------------------------------------------
def _format_banner(local_version: str, remote_version: str) -> str:
    return (
        f"AppMate is out of date "
        f"(installed {local_version} -> latest {remote_version} on github.com/{REPO}). "
        "Run `/plugin` and update appmate to pull the newest skills, commands, and fixes."
    )


def _verdict(local: str, remote: str, *, source: str) -> dict[str, Any]:
    outdated = _is_outdated(local, remote)
    if outdated is None:
        return {
            "status": "unknown",
            "local_version": local,
            "remote_version": remote,
            "source": source,
            "message": None,
        }
    if outdated:
        return {
            "status": "outdated",
            "local_version": local,
            "remote_version": remote,
            "source": source,
            "message": _format_banner(local, remote),
        }
    return {
        "status": "up_to_date",
        "local_version": local,
        "remote_version": remote,
        "source": source,
        "message": None,
    }


def check(*, force: bool = False) -> dict[str, Any]:
    """Compute the update verdict. Pure function shape for testing.

    Returns a dict with keys:
        status         "up_to_date" | "outdated" | "unknown"
        local_version  str | None
        remote_version str | None
        source         "cache" | "fresh" | "skipped"
        message        str | None   (banner text when status == "outdated")
    """
    local = _local_version(_plugin_root())
    if local is None:
        return {
            "status": "unknown",
            "local_version": None,
            "remote_version": None,
            "source": "skipped",
            "message": None,
        }

    cache_path = _cache_path()
    if not force:
        cached_remote = _read_cache(cache_path, local)
        if cached_remote is not None:
            return _verdict(local, cached_remote, source="cache")

    remote = _remote_version()
    if remote is None:
        return {
            "status": "unknown",
            "local_version": local,
            "remote_version": None,
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
