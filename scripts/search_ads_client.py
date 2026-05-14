"""Apple Ads (Search Ads) API client.

OAuth flow:
  1. Sign an ES256 JWT with private key (kid = key_id)
  2. POST that JWT as `client_secret` to appleid.apple.com → access_token
  3. Call api.searchads.apple.com with Bearer <token> + X-AP-Context: orgId=<org>

Token is cached for ~1h. Tied to the public key uploaded in Apple Ads UI.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time
from typing import Any

import jwt
import requests

import appmate_config

TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
API_BASE = "https://api.searchads.apple.com/api/v5"


def _creds_path() -> pathlib.Path:
    return appmate_config.config_path("search_ads_credentials.txt")


def _token_cache() -> pathlib.Path:
    return appmate_config.data_path(".search_ads_token.json")


def _load_creds() -> dict[str, str]:
    creds: dict[str, str] = {}
    for line in _creds_path().read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        creds[k.strip()] = v.strip()
    return creds


def make_client_assertion(lifetime_seconds: int = 86400 * 180) -> str:
    """JWT used as client_secret in the OAuth token exchange."""
    creds = _load_creds()
    now = int(time.time())
    payload = {
        "sub": creds["client_id"],
        "aud": "https://appleid.apple.com",
        "iat": now,
        "exp": now + lifetime_seconds,
        "iss": creds["team_id"],
    }
    private_key = pathlib.Path(creds["private_key_path"]).read_text()
    return jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"alg": "ES256", "kid": creds["key_id"]},
    )


def _load_cached_token() -> str | None:
    cache = _token_cache()
    if not cache.exists():
        return None
    try:
        c = json.loads(cache.read_text())
        if c.get("expires_at", 0) - 60 > time.time():
            return c["access_token"]
    except Exception:
        pass
    return None


def _save_cached_token(token: str, ttl: int) -> None:
    _token_cache().write_text(json.dumps({
        "access_token": token,
        "expires_at": int(time.time()) + ttl,
    }))


def get_access_token(force_refresh: bool = False, retries: int = 6) -> str:
    if not force_refresh:
        cached = _load_cached_token()
        if cached:
            return cached
    assertion = make_client_assertion()
    client_id = _load_creds()["client_id"]
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": assertion,
                    "grant_type": "client_credentials",
                    "scope": "searchadsorg",
                },
                headers={
                    "Host": "appleid.apple.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            token = body["access_token"]
            ttl = int(body.get("expires_in", 3600))
            _save_cached_token(token, ttl)
            return token
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError(f"get_access_token: {last_exc}")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "X-AP-Context": f"orgId={_load_creds()['org_id']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get(path: str, params: dict[str, Any] | None = None, retries: int = 3) -> requests.Response:
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=30)
            if r.status_code == 401:
                # token expired? refresh and retry once
                get_access_token(force_refresh=True)
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("get() exhausted retries")


def post(path: str, body: dict[str, Any], retries: int = 3) -> requests.Response:
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=30)
            if r.status_code == 401:
                get_access_token(force_refresh=True)
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("post() exhausted retries")


# ---------------------------------------------------------------------------
# CLI probe
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    print("Fetching access token…")
    tok = get_access_token(force_refresh=True)
    print(f"  ok, length={len(tok)}, prefix={tok[:30]}…")
    print()
    print("GET /api/v5/acls (test auth + see what orgs we can access)")
    r = get("/acls")
    print(f"  HTTP {r.status_code}")
    print(r.text[:1200])
