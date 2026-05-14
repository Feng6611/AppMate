"""App Store Connect API client.

Reads credentials via appmate_config (config/credentials.txt) and exposes:
  - apps()              list all apps on the account
  - sales_report(...)   download a Sales/Subscription report (gzipped TSV -> DataFrame-like list)
  - finance_report(...) download a Finance report
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import pathlib
import sys
import time
from typing import Any, Iterable

import jwt
import requests

import appmate_config

BASE_URL = "https://api.appstoreconnect.apple.com"


def make_token(audience: str = "appstoreconnect-v1", lifetime_seconds: int = 1200) -> str:
    """Generate a short-lived ES256 JWT for App Store Connect."""
    now = int(time.time())
    headers = {"alg": "ES256", "kid": appmate_config.asc_key_id(), "typ": "JWT"}
    payload = {
        "iss": appmate_config.asc_issuer_id(),
        "iat": now,
        "exp": now + lifetime_seconds,
        "aud": audience,
    }
    private_key = appmate_config.asc_private_key_path().read_text()
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def get(path: str, params: dict[str, Any] | None = None, retries: int = 5) -> requests.Response:
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_auth_headers(), params=params, timeout=60)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("get() exhausted retries without exception")


def post(path: str, body: dict[str, Any], retries: int = 3) -> requests.Response:
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    headers = {**_auth_headers(), "Content-Type": "application/json"}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("post() exhausted retries without exception")


def paged_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Follow `links.next` until exhausted. Returns merged {'data': [...], 'included': [...]}."""
    merged: dict[str, Any] = {"data": [], "included": []}
    url: str | None = path
    while url:
        r = get(url, params=params if url == path else None)
        r.raise_for_status()
        j = r.json()
        merged["data"].extend(j.get("data", []))
        merged["included"].extend(j.get("included", []))
        url = (j.get("links") or {}).get("next")
        params = None  # already encoded in `next`
    return merged


def apps(limit: int = 200) -> list[dict[str, Any]]:
    """List all apps visible to this key."""
    r = get("/v1/apps", params={"limit": limit})
    r.raise_for_status()
    return r.json().get("data", [])


def sales_report(
    report_date: str,
    frequency: str = "DAILY",
    report_type: str = "SALES",
    report_sub_type: str = "SUMMARY",
    version: str = "1_0",
) -> list[dict[str, str]]:
    """Download a sales report.

    report_date format depends on frequency:
      DAILY   -> YYYY-MM-DD
      WEEKLY  -> YYYY-MM-DD (must be a Sunday)
      MONTHLY -> YYYY-MM
      YEARLY  -> YYYY
    """
    params = {
        "filter[frequency]": frequency,
        "filter[reportType]": report_type,
        "filter[reportSubType]": report_sub_type,
        "filter[vendorNumber]": appmate_config.asc_vendor_number(),
        "filter[reportDate]": report_date,
        "filter[version]": version,
    }
    r = get("/v1/salesReports", params=params)
    if r.status_code == 404:
        return []  # no data for that date
    r.raise_for_status()
    text = gzip.decompress(r.content).decode("utf-8")
    return _parse_tsv(text)


def finance_report(
    report_date: str,
    region_code: str = "ZZ",
    report_type: str = "FINANCIAL",
) -> list[dict[str, str]]:
    """Download a finance report. region_code='ZZ' returns all regions."""
    params = {
        "filter[reportDate]": report_date,
        "filter[regionCode]": region_code,
        "filter[reportType]": report_type,
        "filter[vendorNumber]": appmate_config.asc_vendor_number(),
    }
    r = get("/v1/financeReports", params=params)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    text = gzip.decompress(r.content).decode("utf-8")
    return _parse_tsv(text)


def _parse_tsv(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return rows
    header = lines[0].split("\t")
    for ln in lines[1:]:
        cells = ln.split("\t")
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def summarize_sales(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    """Aggregate sales rows by app + country."""
    by_app: dict[str, dict[str, float]] = {}
    by_country: dict[str, float] = {}
    total_units = 0
    total_proceeds = 0.0
    for r in rows:
        title = r.get("Title") or r.get("SKU") or "?"
        country = r.get("Country Code") or r.get("Country") or "?"
        units = int(r.get("Units") or 0)
        proceeds = float(r.get("Developer Proceeds") or 0)
        currency = r.get("Currency of Proceeds") or ""
        slot = by_app.setdefault(title, {"units": 0, "proceeds_usd_ish": 0.0})
        slot["units"] += units
        slot["proceeds_usd_ish"] += proceeds
        by_country[country] = by_country.get(country, 0) + units
        total_units += units
        total_proceeds += proceeds
    return {
        "total_units": total_units,
        "total_proceeds_raw_sum": round(total_proceeds, 2),
        "by_app": dict(sorted(by_app.items(), key=lambda kv: -kv[1]["units"])),
        "by_country": dict(sorted(by_country.items(), key=lambda kv: -kv[1])),
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _cmd_apps() -> None:
    data = apps()
    out = [
        {
            "id": a["id"],
            "name": a["attributes"].get("name"),
            "bundleId": a["attributes"].get("bundleId"),
            "sku": a["attributes"].get("sku"),
            "primaryLocale": a["attributes"].get("primaryLocale"),
        }
        for a in data
    ]
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _cmd_sales(args: list[str]) -> None:
    # Default: yesterday daily
    date = args[0] if args else (dt.date.today() - dt.timedelta(days=1)).isoformat()
    freq = args[1] if len(args) > 1 else "DAILY"
    rows = sales_report(date, frequency=freq)
    summary = summarize_sales(rows)
    print(json.dumps({"date": date, "frequency": freq, "rows": len(rows), "summary": summary}, indent=2, ensure_ascii=False))


def _cmd_token() -> None:
    print(make_token())


COMMANDS = {
    "apps": lambda a: _cmd_apps(),
    "sales": _cmd_sales,
    "token": lambda a: _cmd_token(),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: asc_client.py <apps|sales [YYYY-MM-DD] [DAILY|WEEKLY|MONTHLY|YEARLY]|token>")
        return 0
    cmd, *rest = argv
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2
    fn(rest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
