"""Shared configuration and path resolution for AppMate scripts.

Single source of truth for:
  - where data/caches and config/secrets live (DATA_DIR / CONFIG_DIR)
  - App Store Connect credentials + account constants

Path resolution is eager and never fails. Credential loading is lazy and
graceful: a missing config/credentials.txt does not break imports — an error
is raised only when a required secret is actually used, pointing at /appmate-setup.
"""
from __future__ import annotations

import os
import pathlib

# --- Path resolution (eager, pure pathlib, never fails) --------------------
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
APPMATE_HOME = pathlib.Path(os.environ.get("APPMATE_HOME", PLUGIN_ROOT)).resolve()
DATA_DIR = APPMATE_HOME / "data"
CONFIG_DIR = APPMATE_HOME / "config"


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


def rag_base_url() -> str:
    return _load_config().get("rag_base_url") or "https://appmate.000ooo.ooo"


def astro_endpoint() -> str:
    return _load_config().get("astro_endpoint") or "http://127.0.0.1:8089/mcp"
