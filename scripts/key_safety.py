"""App Store Connect API key role-safety probe.

AppMate is a read-only analytics tool. Its API key must never have write access
to App Store Connect data, banking, builds, or app metadata. This module probes
the configured key against role-restricted endpoints, detects elevated roles,
and refuses to operate when any write-capable role is granted.

Role policy
-----------
Safe (read-only):
  * Sales and Reports / Access to Reports — read sales / downloads
  * Customer Support                      — read customer reviews
  * Marketing                             — read analytics / marketing data

Refused (write access to live ASC data — STOP SERVICE):
  * Admin                 — full write: users, billing, anything
  * App Manager           — modify app metadata, screenshots, pricing
  * Developer             — upload builds, modify certificates / identifiers
  * Finance               — modify banking, tax, financial routing

Probe matrix
------------
  /v1/bundleIds              200 -> Developer (or Admin)
  /v1/financeReports         200/404 -> Finance (or Admin); 403 -> not Finance

Caveats
-------
The probes above reliably detect Admin, Developer, and Finance — all three are
gated by Apple at the *read* layer for endpoints owned by Developer / Finance
domains. App Manager, however, cannot be distinguished from read-only roles
through GET endpoints because Apple gates App Manager writes (POST/PATCH on
appStoreVersions, inAppPurchases, etc.) without restricting metadata reads.
Earlier probes against /v1/users and /v1/builds were *false positives* — Sales
and Marketing roles can read those endpoints.

The App-Manager gap is covered by two other defenses:
  1. The setup skill / commands / README instruct users to check ONLY Sales /
     Customer Support / Marketing when generating the key.
  2. ``scripts/asc_client.py`` refuses to issue any non-GET HTTP method unless
     ``APPMATE_ALLOW_WRITES=1`` is set — so even if App Manager slips through
     the probe, AppMate's own code cannot make a write call.

Results are cached in data/key_safety.json for 7 days so the probe runs at most
once per week. Network failures are *not* cached — the probe is retried next
invocation.

Public surface
--------------
    assess_key_safety(force=False) -> dict
        {
            "safe":          bool,
            "checked_at":    "YYYY-MM-DDTHH:MM:SS",
            "unsafe_roles":  [str, ...],   # human-readable
            "probe":         {endpoint: status_code, ...},
            "source":        "cache" | "fresh" | "probe_failed",
        }

    require_safe_key_or_exit(stream=None) -> None
        Fast-fails (SystemExit 2) when offline credentials are missing OR the
        key probe reports an unsafe role. Used by every workflow entrypoint.

CLI
---
    python3 scripts/key_safety.py probe   # force a fresh probe + print verdict
    python3 scripts/key_safety.py status  # print the cached verdict only
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time
from typing import Any

import requests

import appmate_config

# --- Config -------------------------------------------------------------
CACHE_TTL_SECONDS = 7 * 24 * 3600
CACHE_PATH: pathlib.Path = appmate_config.DATA_DIR / "key_safety.json"

# Far-back date used for the Finance probe (must be a valid past month).
_FINANCE_PROBE_DATE = "2024-01"

UNSAFE_ROLES: dict[str, str] = {
    "DEVELOPER_OR_ADMIN": "Developer or Admin — can upload builds, modify certificates and identifiers",
    "FINANCE_OR_ADMIN": "Finance or Admin — can modify banking, tax, financial routing",
}

ROLE_SELECTION_GUIDANCE = (
    "Recreate the key with ONLY these App Store Connect roles checked:\n"
    "    [x] Sales and Reports\n"
    "    [x] Customer Support\n"
    "    [x] Marketing\n"
    "Do NOT check Admin / Developer / App Manager / Finance — those grant\n"
    "write access to live App Store data and will be refused by AppMate."
)


# --- Probe primitives ---------------------------------------------------
def _auth_headers() -> dict[str, str]:
    """Re-use asc_client's JWT generation. Deferred import avoids touching the
    network during module import."""
    from asc_client import _auth_headers as ah  # type: ignore[attr-defined]
    return ah()


def _probe(path: str, params: dict[str, Any] | None = None, retries: int = 2) -> int:
    """Single GET with brief retry on transport failure.

    Returns HTTP status, or -1 if every attempt failed at the transport layer.
    Retries cover the occasional ``ConnectionResetError`` from Apple's edge —
    real authorization decisions (401 / 403 / 200) come back fast and don't
    spin the retry loop.
    """
    url = f"https://api.appstoreconnect.apple.com{path}"
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=_auth_headers(), params=params, timeout=15)
            return r.status_code
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
    _ = last_exc  # retained for debuggers; not surfaced to keep the API small
    return -1


def detect_elevated_roles() -> dict[str, Any]:
    """Run the probe set. Returns a structured result; does not cache.

    Probes:
      * /v1/bundleIds      200 -> Developer or Admin
      * /v1/financeReports 200/404 -> Finance or Admin; 403 -> not Finance/Admin

    See module docstring for the role policy and the App Manager caveat.
    """
    bundle_ids_status = _probe("/v1/bundleIds", {"limit": "1"})
    finance_status = _probe(
        "/v1/financeReports",
        {
            "filter[reportDate]": _FINANCE_PROBE_DATE,
            "filter[regionCode]": "ZZ",
            "filter[reportType]": "FINANCIAL",
            "filter[vendorNumber]": appmate_config.asc_vendor_number(),
        },
    )

    probe_failed = any(s == -1 for s in (bundle_ids_status, finance_status))

    developer_or_admin = bundle_ids_status == 200
    # /v1/financeReports: 200 = report exists; 404 = no data for that date
    # but the call was authorized; 403 = denied (role lacks Finance/Admin).
    finance_or_admin = finance_status in (200, 404)

    roles = {
        "DEVELOPER_OR_ADMIN": developer_or_admin,
        "FINANCE_OR_ADMIN": finance_or_admin,
    }
    return {
        "roles": roles,
        "probe": {
            "/v1/bundleIds": bundle_ids_status,
            "/v1/financeReports": finance_status,
        },
        "probe_failed": probe_failed,
    }


# --- Cache --------------------------------------------------------------
def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


# --- Public API ---------------------------------------------------------
def assess_key_safety(force: bool = False) -> dict[str, Any]:
    """Cached safety assessment. Hits the API at most once per CACHE_TTL_SECONDS.

    Returns a dict with keys: safe, checked_at, unsafe_roles, probe, source.
    Network failures yield source="probe_failed" and are not cached, so the
    next call retries.
    """
    now = time.time()
    cache = _load_cache()
    if cache and not force and now - cache.get("ts", 0) < CACHE_TTL_SECONDS:
        return {**cache["result"], "source": "cache"}

    detection = detect_elevated_roles()
    unsafe = [
        UNSAFE_ROLES[role]
        for role, hit in detection["roles"].items()
        if hit
    ]
    result: dict[str, Any] = {
        "safe": not unsafe and not detection["probe_failed"],
        "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
        "unsafe_roles": unsafe,
        "probe": detection["probe"],
    }

    if detection["probe_failed"]:
        # Don't cache a probe we couldn't trust. Surface the issue.
        result["source"] = "probe_failed"
        result["safe"] = False
        return result

    _save_cache({"ts": now, "result": result})
    result["source"] = "fresh"
    return result


def require_safe_key_or_exit(stream=None, *, force_probe: bool = False) -> None:
    """Combined gate used by every workflow entrypoint and the check CLI.

    Order of checks:
        1. Offline credential validation (appmate_config.require_credentials_or_exit)
        2. Online role-safety probe (cached for 7 days)

    Exits with status 2 and a clear, actionable message on either credential
    or role-probe failure.
    """
    if stream is None:
        stream = sys.stderr

    appmate_config.require_credentials_or_exit(stream=stream)

    assessment = assess_key_safety(force=force_probe)
    if assessment["safe"]:
        return

    print(
        "AppMate refuses to run — the configured API key has write access to App Store data.",
        file=stream,
    )
    if assessment["unsafe_roles"]:
        print("Detected role(s):", file=stream)
        for desc in assessment["unsafe_roles"]:
            print(f"  - {desc}", file=stream)
    elif assessment.get("source") == "probe_failed":
        print(
            "Could not reach App Store Connect to verify key roles "
            "(network error). Re-run when online — AppMate will not start "
            "without a successful safety check.",
            file=stream,
        )
    print("Probe results:", file=stream)
    for endpoint, status in assessment["probe"].items():
        marker = "200/404" if status in (200, 404) else str(status)
        print(f"  GET {endpoint} -> {marker}", file=stream)
    print("", file=stream)
    print(ROLE_SELECTION_GUIDANCE, file=stream)
    print("", file=stream)
    print(
        "How to recover:\n"
        "  1. Revoke the current key in App Store Connect → Users and Access\n"
        "     → Integrations → App Store Connect API.\n"
        "  2. Generate a NEW key with ONLY the three safe roles above.\n"
        "  3. Drop the new .p8 into config/, update private_key_path / key_id\n"
        "     in config/credentials.txt.\n"
        f"  4. Delete the stale cache: rm {CACHE_PATH}\n"
        "  5. Re-run: python3 scripts/appmate_config.py check",
        file=stream,
    )
    raise SystemExit(2)


# --- CLI ----------------------------------------------------------------
def _print_assessment(assessment: dict[str, Any]) -> None:
    verdict = "SAFE" if assessment["safe"] else "UNSAFE"
    print(f"AppMate key safety: {verdict}  (checked_at={assessment['checked_at']}, source={assessment['source']})")
    for endpoint, status in assessment["probe"].items():
        print(f"  GET {endpoint} -> {status}")
    if assessment["unsafe_roles"]:
        print("Detected unsafe role(s):")
        for desc in assessment["unsafe_roles"]:
            print(f"  - {desc}")


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: python3 scripts/key_safety.py <probe|status>", file=sys.stderr)
        return 1

    cmd = argv[0]
    if cmd == "probe":
        appmate_config.require_credentials_or_exit()
        assessment = assess_key_safety(force=True)
        _print_assessment(assessment)
        return 0 if assessment["safe"] else 2

    if cmd == "status":
        cache = _load_cache()
        if not cache:
            print("No cached safety assessment. Run: python3 scripts/key_safety.py probe", file=sys.stderr)
            return 1
        _print_assessment({**cache["result"], "source": "cache"})
        return 0 if cache["result"]["safe"] else 2

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
