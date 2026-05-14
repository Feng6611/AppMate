"""Pull EVERYTHING App Store Connect API will give us for each app.

Per app we fetch (each wrapped in try/except — endpoints differ in availability
depending on app state and platform):

  1. core           /v1/apps/{id}                              attributes only
  2. appInfo        /v1/apps/{id}/appInfos                     + age/categories
  3. appInfoLocs    /v1/appInfos/{id}/appInfoLocalizations     name/subtitle/privacyUrl per locale
  4. versions       /v1/apps/{id}/appStoreVersions             every historical version
  5. versionLocs    /v1/appStoreVersions/{vid}/appStoreVersionLocalizations
                                                               desc/kw/whatsNew/marketingUrl per locale
  6. iaps           /v1/apps/{id}/inAppPurchasesV2             non-subscription IAPs
  7. subscriptions  /v1/apps/{id}/subscriptionGroups           groups + subs + introductory offers
  8. pricing        /v1/apps/{id}/appPricePoints (current)
  9. availability   /v1/apps/{id}/availabilities (or appAvailabilityV2)
 10. builds         /v1/apps/{id}/builds                       latest 10
 11. reviews        /v1/apps/{id}/customerReviews              up to 200, only for live apps

Output:
  apps_full.json   one big object  { fetched_at, count, apps: [...] }
  prints a categorized summary (live vs not-yet-live) at the end.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import appmate_config
from asc_client import get, paged_get

OUT_PATH = appmate_config.data_path("apps_full.json")


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------
def _safe(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def _rel_id(obj: dict[str, Any], rel: str) -> str | None:
    d = ((obj.get("relationships") or {}).get(rel) or {}).get("data")
    if isinstance(d, dict):
        return d.get("id")
    if isinstance(d, list) and d:
        return d[0].get("id")
    return None


def _rel_ids(obj: dict[str, Any], rel: str) -> list[str]:
    d = ((obj.get("relationships") or {}).get(rel) or {}).get("data") or []
    return [x.get("id") for x in d if isinstance(x, dict)]


def _attrs(obj: dict[str, Any] | None) -> dict[str, Any]:
    return (obj or {}).get("attributes") or {}


# ---------------------------------------------------------------------------
# Top-level apps list
# ---------------------------------------------------------------------------
def list_apps() -> list[dict[str, Any]]:
    r = get("/v1/apps", params={"limit": 200})
    r.raise_for_status()
    return r.json()["data"]


# ---------------------------------------------------------------------------
# Per-app fetchers
# ---------------------------------------------------------------------------
def fetch_app_info(app_id: str) -> dict[str, Any]:
    """AppInfo + categories + age + localizations."""
    r = get(f"/v1/apps/{app_id}/appInfos", params={
        "include": "primaryCategory,secondaryCategory,appInfoLocalizations",
        "limit": 10,
    })
    r.raise_for_status()
    j = r.json()
    if not j.get("data"):
        return {}
    info = j["data"][0]  # the "current" one (apps usually have 1 EDITABLE + 1 PUBLIC)
    included = {(it["type"], it["id"]): it for it in j.get("included", [])}
    locs = []
    for loc_id in _rel_ids(info, "appInfoLocalizations"):
        loc = included.get(("appInfoLocalizations", loc_id))
        if loc:
            locs.append({"id": loc_id, **_attrs(loc)})
    return {
        "id": info["id"],
        "attributes": _attrs(info),
        "primaryCategory": _rel_id(info, "primaryCategory"),
        "secondaryCategory": _rel_id(info, "secondaryCategory"),
        "localizations": locs,
    }


def fetch_versions(app_id: str) -> list[dict[str, Any]]:
    """All historical app store versions + their localizations."""
    page = paged_get(f"/v1/apps/{app_id}/appStoreVersions", params={
        "limit": 200,
        "include": "appStoreVersionLocalizations",
    })
    included = {(it["type"], it["id"]): it for it in page["included"]}
    versions = []
    for v in page["data"]:
        locs = []
        for loc_id in _rel_ids(v, "appStoreVersionLocalizations"):
            loc = included.get(("appStoreVersionLocalizations", loc_id))
            if loc:
                locs.append({"id": loc_id, **_attrs(loc)})
        versions.append({
            "id": v["id"],
            "attributes": _attrs(v),
            "localizations": locs,
        })
    return versions


def fetch_iaps(app_id: str) -> list[dict[str, Any]]:
    """Non-subscription in-app purchases."""
    page = paged_get(f"/v1/apps/{app_id}/inAppPurchasesV2", params={
        "limit": 200,
        "include": "inAppPurchaseLocalizations,iapPriceSchedule",
    })
    included = {(it["type"], it["id"]): it for it in page["included"]}
    iaps = []
    for iap in page["data"]:
        loc_records = []
        for lid in _rel_ids(iap, "inAppPurchaseLocalizations"):
            loc = included.get(("inAppPurchaseLocalizations", lid))
            if loc:
                loc_records.append({"id": lid, **_attrs(loc)})
        iaps.append({
            "id": iap["id"],
            "attributes": _attrs(iap),
            "localizations": loc_records,
        })
    return iaps


def fetch_subscriptions(app_id: str) -> list[dict[str, Any]]:
    """Subscription groups, each with its subscriptions."""
    groups = paged_get(f"/v1/apps/{app_id}/subscriptionGroups", params={
        "limit": 50,
        "include": "subscriptions,subscriptionGroupLocalizations",
    })
    included = {(it["type"], it["id"]): it for it in groups["included"]}
    out = []
    for g in groups["data"]:
        sub_ids = _rel_ids(g, "subscriptions")
        subs = []
        for sid in sub_ids:
            sub_full = _safe(_fetch_one_subscription, sid)
            subs.append(sub_full)
        loc_ids = _rel_ids(g, "subscriptionGroupLocalizations")
        loc_records = []
        for lid in loc_ids:
            loc = included.get(("subscriptionGroupLocalizations", lid))
            if loc:
                loc_records.append({"id": lid, **_attrs(loc)})
        out.append({
            "id": g["id"],
            "attributes": _attrs(g),
            "subscriptions": subs,
            "localizations": loc_records,
        })
    return out


def _fetch_one_subscription(sub_id: str) -> dict[str, Any]:
    r = get(f"/v1/subscriptions/{sub_id}", params={
        "include": "subscriptionLocalizations,introductoryOffers,prices",
    })
    if not r.ok:
        return {"id": sub_id, "_error": r.status_code}
    j = r.json()
    sub = j["data"]
    included = {(it["type"], it["id"]): it for it in j.get("included", [])}
    locs = [
        {"id": lid, **_attrs(included.get(("subscriptionLocalizations", lid)))}
        for lid in _rel_ids(sub, "subscriptionLocalizations")
    ]
    offers = [
        {"id": oid, **_attrs(included.get(("subscriptionIntroductoryOffers", oid)))}
        for oid in _rel_ids(sub, "introductoryOffers")
    ]
    prices = [
        {"id": pid, **_attrs(included.get(("subscriptionPrices", pid)))}
        for pid in _rel_ids(sub, "prices")
    ]
    return {
        "id": sub_id,
        "attributes": _attrs(sub),
        "localizations": locs,
        "introductoryOffers": offers,
        "prices": prices,
    }


def fetch_pricing(app_id: str) -> dict[str, Any]:
    """Current price tier via appPriceSchedule."""
    r = get(f"/v1/apps/{app_id}/appPriceSchedule", params={
        "include": "manualPrices,baseTerritory",
    })
    if not r.ok:
        return {"_error": r.status_code}
    j = r.json()
    return {
        "data": j.get("data"),
        "included": j.get("included", []),
    }


def fetch_availability(app_id: str) -> dict[str, Any]:
    """Where the app is available."""
    r = get(f"/v1/apps/{app_id}/appAvailabilityV2", params={
        "include": "territoryAvailabilities",
        "limit[territoryAvailabilities]": 200,
    })
    if not r.ok:
        # fallback to v1
        r = get(f"/v1/apps/{app_id}/availabilities", params={"limit": 200})
    if not r.ok:
        return {"_error": r.status_code}
    j = r.json()
    return {"data": j.get("data"), "included": j.get("included", [])}


def fetch_builds(app_id: str) -> list[dict[str, Any]]:
    """Latest 10 builds."""
    r = get(f"/v1/apps/{app_id}/builds", params={
        "limit": 10,
        "sort": "-uploadedDate",
    })
    if not r.ok:
        return [{"_error": r.status_code}]
    return [{"id": b["id"], "attributes": _attrs(b)} for b in r.json().get("data", [])]


def fetch_reviews(app_id: str, max_pages: int = 5) -> dict[str, Any]:
    """Customer reviews — paginate up to max_pages × 200."""
    url = f"/v1/apps/{app_id}/customerReviews"
    params: dict[str, Any] | None = {"limit": 200, "sort": "-createdDate"}
    pages = 0
    rows: list[dict[str, Any]] = []
    while url and pages < max_pages:
        r = get(url, params=params)
        if not r.ok:
            return {"_error": r.status_code, "count": len(rows), "reviews": rows}
        j = r.json()
        for review in j.get("data", []):
            a = _attrs(review)
            rows.append({
                "id": review["id"],
                "rating": a.get("rating"),
                "title": a.get("title"),
                "body": a.get("body"),
                "reviewerNickname": a.get("reviewerNickname"),
                "createdDate": a.get("createdDate"),
                "territory": a.get("territory"),
            })
        nxt = (j.get("links") or {}).get("next")
        if not nxt:
            break
        url = nxt
        params = None
        pages += 1
    avg = sum(r["rating"] for r in rows if isinstance(r.get("rating"), int)) / len(rows) if rows else 0
    return {"count": len(rows), "averageRating": round(avg, 2), "reviews": rows}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def fetch_one(app: dict[str, Any], include_reviews: bool = True) -> dict[str, Any]:
    app_id = app["id"]
    name = _attrs(app).get("name")
    started = time.time()
    rec: dict[str, Any] = {
        "id": app_id,
        "core": _attrs(app),
        "appInfo": _safe(fetch_app_info, app_id),
        "versions": _safe(fetch_versions, app_id),
        "iaps": _safe(fetch_iaps, app_id),
        "subscriptionGroups": _safe(fetch_subscriptions, app_id),
        "pricing": _safe(fetch_pricing, app_id),
        "availability": _safe(fetch_availability, app_id),
        "builds": _safe(fetch_builds, app_id),
    }
    if include_reviews:
        rec["reviews"] = _safe(fetch_reviews, app_id)
    rec["_fetch_seconds"] = round(time.time() - started, 2)
    return rec


def is_live(rec: dict[str, Any]) -> bool:
    """An app is 'live' if any of its appStoreVersions is/was READY_FOR_SALE."""
    info_state = (rec.get("appInfo") or {}).get("attributes", {}).get("appStoreState")
    if info_state == "READY_FOR_SALE":
        return True
    versions = rec.get("versions") or []
    if isinstance(versions, list):
        for v in versions:
            if v.get("attributes", {}).get("appStoreState") == "READY_FOR_SALE":
                return True
    return False


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def categorize_and_print(records: list[dict[str, Any]]) -> None:
    live: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    for rec in records:
        (live if is_live(rec) else drafts).append(rec)

    def fmt(rec: dict[str, Any]) -> str:
        core = rec["core"]
        info = rec.get("appInfo") or {}
        cat = info.get("primaryCategory") or "-"
        info_state = info.get("attributes", {}).get("appStoreState") or "-"
        # latest version
        versions = rec.get("versions") or []
        latest = versions[0] if isinstance(versions, list) and versions else {}
        v_attrs = latest.get("attributes", {}) if isinstance(latest, dict) else {}
        plat = v_attrs.get("platform", "-")
        ver = v_attrs.get("versionString", "-")
        n_iap = len(rec.get("iaps") or []) if isinstance(rec.get("iaps"), list) else 0
        n_sub_groups = len(rec.get("subscriptionGroups") or []) if isinstance(rec.get("subscriptionGroups"), list) else 0
        n_reviews = (rec.get("reviews") or {}).get("count", 0) if isinstance(rec.get("reviews"), dict) else 0
        avg = (rec.get("reviews") or {}).get("averageRating", 0) if isinstance(rec.get("reviews"), dict) else 0
        n_locs = 0
        for v in versions if isinstance(versions, list) else []:
            n_locs = max(n_locs, len(v.get("localizations") or []))
        return (
            f"  {(core.get('name') or '?')[:32]:<32} v{ver:<7} {plat:<7} "
            f"{cat:<18} iap={n_iap:<2} sub_grp={n_sub_groups:<2} "
            f"locs={n_locs:<2} reviews={n_reviews}({avg}⭐)  "
            f"[{core.get('bundleId')}]"
        )

    print()
    print(f"━━━ Live on App Store ({len(live)}) ━━━")
    # group by platform inside
    for plat in ("IOS", "MAC_OS", "TV_OS", "VISION_OS"):
        group = []
        for r in live:
            versions = r.get("versions") or []
            top = versions[0].get("attributes", {}) if isinstance(versions, list) and versions else {}
            if top.get("platform") == plat:
                group.append(r)
        if not group:
            continue
        print(f"\n  ▸ {plat} ({len(group)})")
        for rec in sorted(group, key=lambda r: r["core"].get("name") or ""):
            print(fmt(rec))

    print(f"\n━━━ Not yet on App Store ({len(drafts)}) ━━━")
    states: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in drafts:
        versions = rec.get("versions") or []
        st = versions[0].get("attributes", {}).get("appStoreState") if versions else "NO_VERSIONS"
        states[st or "NO_VERSIONS"].append(rec)
    for st, group in sorted(states.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  ▸ {st} ({len(group)})")
        for rec in sorted(group, key=lambda r: r["core"].get("name") or ""):
            print(fmt(rec))

    # Aggregate stats
    total_locs = sum(
        sum(len(v.get("localizations") or []) for v in (r.get("versions") or []) if isinstance(v, dict))
        for r in records
    )
    total_iaps = sum(len(r.get("iaps") or []) for r in records if isinstance(r.get("iaps"), list))
    total_sub_groups = sum(
        len(r.get("subscriptionGroups") or []) for r in records if isinstance(r.get("subscriptionGroups"), list)
    )
    total_subs = sum(
        sum(len(g.get("subscriptions") or []) for g in (r.get("subscriptionGroups") or []) if isinstance(g, dict))
        for r in records
    )
    total_reviews = sum(
        (r.get("reviews") or {}).get("count", 0) if isinstance(r.get("reviews"), dict) else 0
        for r in records
    )
    total_versions = sum(len(r.get("versions") or []) for r in records if isinstance(r.get("versions"), list))
    print()
    print(f"━━━ Aggregate ━━━")
    print(f"  total apps:               {len(records)}")
    print(f"    live:                   {len(live)}")
    print(f"    not live:               {len(drafts)}")
    print(f"  total versions on file:   {total_versions}")
    print(f"  total localization rows:  {total_locs}")
    print(f"  total IAPs:               {total_iaps}")
    print(f"  total subscription grps:  {total_sub_groups}  ({total_subs} subs)")
    print(f"  total reviews fetched:    {total_reviews}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    workers = 4
    apps = list_apps()
    print(f"Found {len(apps)} apps. Fetching with {workers} workers…\n")

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_app = {pool.submit(fetch_one, a): a for a in apps}
        for i, fut in enumerate(as_completed(future_to_app), 1):
            app = future_to_app[fut]
            name = _attrs(app).get("name", "?")
            try:
                rec = fut.result()
                records.append(rec)
                # crude one-line progress
                n_v = len(rec.get("versions") or []) if isinstance(rec.get("versions"), list) else 0
                n_i = len(rec.get("iaps") or []) if isinstance(rec.get("iaps"), list) else 0
                n_s = len(rec.get("subscriptionGroups") or []) if isinstance(rec.get("subscriptionGroups"), list) else 0
                n_r = (rec.get("reviews") or {}).get("count", 0) if isinstance(rec.get("reviews"), dict) else 0
                dt_s = rec.get("_fetch_seconds")
                print(f"  [{i:>2}/{len(apps)}] {name[:38]:<38}  v={n_v}  iap={n_i}  sub={n_s}  rev={n_r}  {dt_s}s")
            except Exception as e:
                traceback.print_exc()
                records.append({
                    "id": app["id"],
                    "core": _attrs(app),
                    "_fatal": f"{type(e).__name__}: {e}",
                })

    # Stable ordering
    records.sort(key=lambda r: r["core"].get("name") or "")
    payload = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "count": len(records),
        "apps": records,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n[saved] {OUT_PATH}  ({OUT_PATH.stat().st_size / 1024:.1f} KB)")

    categorize_and_print(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
