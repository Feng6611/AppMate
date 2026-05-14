"""App Analytics + Performance pulls.

Two layers:

1. **Performance metrics** (`/v1/apps/{id}/perfPowerMetrics`) — works for iOS apps
   that meet Apple's daily-active-devices threshold. No special consent needed.
   Returns metrics like hangRate, launchTime, memory, disk, battery, scrollHitch,
   per-version, per-device (iPhones/iPads/etc), at p50/p90 percentile.

2. **App Analytics reports** (`/v1/analyticsReportRequests` + reports + instances
   + segments) — requires per-API-key opt-in from the Account Holder.
   Currently returns 403 for this key (see `permission_check()`).

Run modes:
  python3 app_analytics.py probe      — check which APIs are accessible
  python3 app_analytics.py perf       — pull perfPowerMetrics for all iOS apps
  python3 app_analytics.py request    — try creating analytics report requests
  python3 app_analytics.py download   — list & download already-prepared reports
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import pathlib
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable

import requests

import appmate_config
from asc_client import get, post, paged_get

OUT_PERF = appmate_config.data_path("perf_metrics.json")
OUT_ANALYTICS = appmate_config.data_path("app_analytics.json")
APPS_FULL = appmate_config.data_path("apps_full.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def live_apps() -> list[tuple[str, str, set[str]]]:
    """[(app_id, name, {platform,…})] for every live app."""
    apps = json.loads(APPS_FULL.read_text())["apps"]
    out: list[tuple[str, str, set[str]]] = []
    for a in apps:
        info_state = (a.get("appInfo") or {}).get("attributes", {}).get("appStoreState")
        any_live = any(
            v.get("attributes", {}).get("appStoreState") == "READY_FOR_SALE"
            for v in (a.get("versions") or []) if isinstance(v, dict)
        )
        if info_state != "READY_FOR_SALE" and not any_live:
            continue
        plats = {
            v.get("attributes", {}).get("platform")
            for v in (a.get("versions") or [])
            if isinstance(v, dict)
        }
        out.append((a["id"], a["core"].get("name", "?"), plats))
    return out


# ---------------------------------------------------------------------------
# 1. Performance metrics
# ---------------------------------------------------------------------------
def fetch_perf_one(app_id: str, platform: str) -> dict[str, Any]:
    r = get(f"/v1/apps/{app_id}/perfPowerMetrics", params={"filter[platform]": platform})
    if not r.ok:
        return {"_error": r.status_code, "_body": r.text[:300]}
    return r.json()


def cmd_perf() -> None:
    apps = live_apps()
    results: dict[str, dict[str, Any]] = {}
    print(f"Pulling perfPowerMetrics for {len(apps)} live apps…\n")
    for app_id, name, plats in apps:
        results[name] = {}
        for plat in plats:
            api_plat = "IOS" if plat == "IOS" else None  # API currently rejects MAC_OS/etc.
            if not api_plat:
                continue
            data = fetch_perf_one(app_id, api_plat)
            results[name][api_plat] = data
            n = len(data.get("productData", [])) if "productData" in data else 0
            tag = f"err={data.get('_error')}" if "_error" in data else f"productData={n}"
            print(f"  {name:<40} {api_plat:<6} {tag}")
    OUT_PERF.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n[saved] {OUT_PERF}")

    # Tabular summary of apps that returned actual metrics
    print("\nApps with performance data:")
    for name, plats in results.items():
        for plat, d in plats.items():
            pd = d.get("productData") or []
            if pd:
                cats = pd[0].get("metricCategories", [])
                cat_names = ",".join(c.get("identifier") for c in cats)
                print(f"  {name:<40} {plat}  categories=[{cat_names}]")


# ---------------------------------------------------------------------------
# 2. App Analytics reports
# ---------------------------------------------------------------------------
def list_existing_requests(app_id: str) -> list[dict[str, Any]]:
    r = get(f"/v1/apps/{app_id}/analyticsReportRequests", params={"limit": 50})
    if not r.ok:
        return []
    return r.json().get("data", [])


def create_request(app_id: str, access_type: str = "ONGOING") -> dict[str, Any]:
    body = {
        "data": {
            "type": "analyticsReportRequests",
            "attributes": {"accessType": access_type},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }
    }
    r = post("/v1/analyticsReportRequests", body)
    if r.status_code == 201:
        return {"ok": True, "data": r.json()["data"]}
    return {"ok": False, "status": r.status_code, "body": r.text[:400]}


def list_reports(request_id: str) -> list[dict[str, Any]]:
    page = paged_get(
        f"/v1/analyticsReportRequests/{request_id}/reports",
        params={"limit": 200},
    )
    return page["data"]


def list_instances(report_id: str) -> list[dict[str, Any]]:
    page = paged_get(
        f"/v1/analyticsReports/{report_id}/instances",
        params={"limit": 200, "sort": "-processingDate"},
    )
    return page["data"]


def list_segments(instance_id: str) -> list[dict[str, Any]]:
    r = get(f"/v1/analyticsReportInstances/{instance_id}/segments")
    if not r.ok:
        return []
    return r.json().get("data", [])


def download_segment_csv(segment_url: str) -> list[dict[str, str]]:
    """Segment data is a gzipped CSV at a presigned URL."""
    r = requests.get(segment_url, timeout=120)
    r.raise_for_status()
    raw = gzip.decompress(r.content) if r.content[:2] == b"\x1f\x8b" else r.content
    text = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_probe() -> None:
    apps = live_apps()
    print(f"=== App Analytics API probe ({len(apps)} live apps) ===\n")
    total_requests = 0
    for app_id, name, _ in apps:
        existing = list_existing_requests(app_id)
        if existing:
            total_requests += len(existing)
            print(f"  {name:<40} existing requests: {len(existing)}")
            for req in existing:
                a = req.get("attributes", {})
                print(f"    - {req['id'][:8]}… type={a.get('accessType')} "
                      f"stopped={a.get('stoppedDueToInactivity')}")
    print(f"\nTotal existing analyticsReportRequests on this account: {total_requests}")

    print("\nTrying to create a request on first app…")
    first = apps[0]
    res = create_request(first[0], "ONGOING")
    if res["ok"]:
        print(f"  ✅ Created request {res['data']['id']} for {first[1]}")
    else:
        print(f"  ❌ {res['status']}  {res['body'][:300]}")
        print()
        print("  ⓘ App Analytics report creation requires per-API-key consent.")
        print("    Have an Account Holder open App Store Connect →")
        print("    Users and Access → Integrations → App Store Connect API →")
        print("    edit key '{}', and enable 'App Analytics Reports'.".format(
            "M5JXS72F29"
        ))


def cmd_request() -> None:
    apps = live_apps()
    print(f"Creating ONGOING analytics requests for {len(apps)} live apps…\n")
    for app_id, name, _ in apps:
        existing = list_existing_requests(app_id)
        if existing:
            print(f"  ⏭  {name}  already has {len(existing)} request(s)")
            continue
        res = create_request(app_id, "ONGOING")
        if res["ok"]:
            print(f"  ✅ {name}  req_id={res['data']['id'][:8]}…")
        else:
            print(f"  ❌ {name}  status={res['status']}  {res['body'][:120]}")


def cmd_download() -> None:
    apps = live_apps()
    print(f"Listing prepared reports for {len(apps)} live apps…\n")
    bundle: dict[str, dict[str, Any]] = {}
    for app_id, name, _ in apps:
        per_app: dict[str, Any] = {}
        reqs = list_existing_requests(app_id)
        if not reqs:
            continue
        for req in reqs:
            req_id = req["id"]
            try:
                reports = list_reports(req_id)
            except Exception as e:
                per_app[req_id] = {"_error": f"list_reports: {e}"}
                continue
            for rpt in reports:
                rid = rpt["id"]
                rattrs = rpt.get("attributes", {})
                rname = rattrs.get("name") or rid
                try:
                    instances = list_instances(rid)
                except Exception:
                    instances = []
                if not instances:
                    continue
                # Take most recent instance only
                inst = instances[0]
                segments = list_segments(inst["id"])
                rows_all: list[dict[str, str]] = []
                for seg in segments:
                    url = seg.get("attributes", {}).get("url")
                    if not url:
                        continue
                    try:
                        rows_all.extend(download_segment_csv(url))
                    except Exception as e:
                        rows_all.append({"_error": str(e)})
                per_app.setdefault(rname, []).extend(rows_all[:1000])  # cap per report
                print(f"  {name:<28} {rname:<40} rows={len(rows_all)}")
        if per_app:
            bundle[name] = per_app
    OUT_ANALYTICS.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    print(f"\n[saved] {OUT_ANALYTICS}")


COMMANDS = {
    "probe": cmd_probe,
    "perf": cmd_perf,
    "request": cmd_request,
    "download": cmd_download,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: app_analytics.py <probe|perf|request|download>")
        return 0
    cmd = argv[0]
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2
    fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
