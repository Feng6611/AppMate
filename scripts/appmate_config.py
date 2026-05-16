"""Shared configuration and path resolution for AppMate scripts.

Single source of truth for:
  - where data/caches and config/secrets live (DATA_DIR / CONFIG_DIR)
  - App Store Connect credentials + account constants
  - cheap pre-flight credential check used by every CLI entrypoint

Path resolution is eager and never fails. Credential loading is lazy and
graceful: a missing config/credentials.txt does not break imports — an error
is raised only when a required secret is actually used, pointing at /appmate-setup.

CLI:
    python3 scripts/appmate_config.py check
        Exits 0 if all required credentials are present and the .p8 key file
        exists; exits 2 with a clear message otherwise. Used as the universal
        gate before any downstream workflow script.
"""
from __future__ import annotations

import os
import pathlib
import sys

# --- Path resolution (eager, pure pathlib, never fails) --------------------
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
APPMATE_HOME = pathlib.Path(os.environ.get("APPMATE_HOME", PLUGIN_ROOT)).resolve()
DATA_DIR = APPMATE_HOME / "data"
CONFIG_DIR = APPMATE_HOME / "config"

REQUIRED_CRED_KEYS: tuple[str, ...] = (
    "issuer_id",
    "key_id",
    "private_key_path",
    "vendor_number",
)


def data_path(name: str) -> pathlib.Path:
    """Path to a file under data/. Ensures data/ exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def config_path(name: str) -> pathlib.Path:
    """Path to a file under config/."""
    return CONFIG_DIR / name


# --- Credential loading (lazy, graceful — re-read each call, file is tiny) --
def _load_config() -> dict[str, str]:
    """Parse config/credentials.txt into a dict. Missing file -> empty dict."""
    path = CONFIG_DIR / "credentials.txt"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _require(key: str) -> str:
    val = (_load_config().get(key) or "").strip()
    if not val:
        raise RuntimeError(
            f"AppMate config missing '{key}'. "
            f"Run /appmate-setup or edit {CONFIG_DIR / 'credentials.txt'}."
        )
    return val


def asc_issuer_id() -> str:
    return _require("issuer_id")


def asc_key_id() -> str:
    return _require("key_id")


def asc_vendor_number() -> str:
    return _require("vendor_number")


def asc_private_key_path() -> pathlib.Path:
    p = pathlib.Path(_require("private_key_path"))
    return p if p.is_absolute() else APPMATE_HOME / p


# --- Pre-flight credential check ------------------------------------------
def credential_status() -> dict[str, str]:
    """Return per-key status. Values are one of:
        "ok"               — value present (and, for private_key_path, file exists)
        "missing"          — key absent / empty in credentials.txt
        "key_file_missing" — private_key_path is set but the .p8 file is not on disk
    """
    cfg = _load_config()
    out: dict[str, str] = {}
    for key in REQUIRED_CRED_KEYS:
        val = (cfg.get(key) or "").strip()
        out[key] = "ok" if val else "missing"
    if out.get("private_key_path") == "ok":
        raw = cfg["private_key_path"].strip()
        p = pathlib.Path(raw)
        if not p.is_absolute():
            p = APPMATE_HOME / p
        if not p.exists():
            out["private_key_path"] = "key_file_missing"
    return out


def credentials_ok() -> bool:
    """True iff every required credential is present and the .p8 file exists."""
    return all(v == "ok" for v in credential_status().values())


_STATUS_HINTS = {
    "missing": "missing or empty in credentials.txt",
    "key_file_missing": ".p8 file does not exist on disk",
}


def _format_missing(status: dict[str, str]) -> list[str]:
    return [
        f"  - {k}: {_STATUS_HINTS.get(v, v)}"
        for k, v in status.items()
        if v != "ok"
    ]


def require_credentials_or_exit(stream=None) -> None:
    """Call at the top of any CLI entrypoint that touches App Store Connect.

    Prints a clear, actionable message to *stream* (default stderr) and exits
    with code 2 if any required credential is missing or the .p8 file is gone.
    Exits silently (returns) when everything is in place.
    """
    if stream is None:
        stream = sys.stderr
    status = credential_status()
    bad_lines = _format_missing(status)
    if not bad_lines:
        return
    print("AppMate is not fully configured — refusing to run.", file=stream)
    print(f"  config file: {CONFIG_DIR / 'credentials.txt'}", file=stream)
    for line in bad_lines:
        print(line, file=stream)
    print("Fix: run /appmate-setup (or edit config/credentials.txt and drop the .p8 into config/).", file=stream)
    raise SystemExit(2)


def _cli(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "check":
        # 1) Offline credential presence
        status = credential_status()
        bad_lines = _format_missing(status)
        if bad_lines:
            print("AppMate credentials: NOT configured", file=sys.stderr)
            print(f"  config file: {CONFIG_DIR / 'credentials.txt'}", file=sys.stderr)
            for line in bad_lines:
                print(line, file=sys.stderr)
            print("Run /appmate-setup to fix.", file=sys.stderr)
            return 2
        print("AppMate credentials: ok")
        print(f"  config file: {CONFIG_DIR / 'credentials.txt'}")

        # 2) Online role-safety probe (cached). Deferred import keeps this
        # module dependency-light when callers only need the offline check.
        try:
            import key_safety  # type: ignore[import-not-found]
        except ImportError:
            # Safety module missing — surface a warning but don't gate. Should
            # never happen in a normal install.
            print(
                "WARNING: scripts/key_safety.py not found; skipping key role probe.",
                file=sys.stderr,
            )
            return 0
        assessment = key_safety.assess_key_safety()
        if assessment["safe"]:
            print(
                f"AppMate key safety: SAFE  (source={assessment['source']}, checked_at={assessment['checked_at']})"
            )
            return 0
        # Unsafe — print the same message require_safe_key_or_exit would print
        # and exit 2.
        try:
            key_safety.require_safe_key_or_exit()
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 2
        return 2  # unreachable; defensive

    print("usage: python3 scripts/appmate_config.py check", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
