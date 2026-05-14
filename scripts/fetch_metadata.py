"""Fetch static metadata for every app on this App Store Connect account.

Output: apps_metadata.json (full payload) + console summary table.

For each app we pull:
  - core: name, bundleId, sku, primaryLocale, contentRightsDeclaration, isOrEverWasMadeForKids
  - appInfos -> primary/secondary categories, age rating
  - appStoreVersions -> versionString, state, platform, releaseType, createdDate
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

import appmate_config
from asc_client import paged_get, get

OUT_PATH = appmate_config.data_path("apps_metadata.json")


def _build_included_index(included: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["type"], item["id"]): item for item in included}


def _rel_id(app: dict[str, Any], rel: str) -> str | None:
    d = ((app.get("relationships") or {}).get(rel) or {}).get("data")
    if isinstance(d, dict):
        return d.get("id")
    if isinstance(d, list) and d:
        return d[0].get("id")
    return None


def _rel_ids(app: dict[str, Any], rel: str) -> list[str]:
    d = ((app.get("relationships") or {}).get(rel) or {}).get("data") or []
    return [x.get("id") for x in d if isinstance(x, dict)]


def fetch_all_metadata() -> dict[str, Any]:
    # /v1/apps with includes. App Store Connect supports nested includes via dot path,
    # but to keep responses small we ask for the relationships we need and resolve
    # category references in a 2nd pass.
    # Pass 1: list apps with appInfos + appStoreVersions. Category needs a 2nd pass
    # because /v1/apps does not support nested includes for those rels.
    payload = paged_get(
        "/v1/apps",
        params={
            "limit": 200,
            "include": "appInfos,appStoreVersions",
            "fields[apps]": (
                "name,bundleId,sku,primaryLocale,contentRightsDeclaration,"
                "isOrEverWasMadeForKids,appInfos,appStoreVersions"
            ),
            "fields[appInfos]": (
                "appStoreState,appStoreAgeRating,brazilAgeRating,kidsAgeBand,"
                "primaryCategory,secondaryCategory"
            ),
            "fields[appStoreVersions]": (
                "versionString,appStoreState,platform,releaseType,createdDate"
            ),
            "limit[appStoreVersions]": 1,
        },
    )

    apps = payload["data"]
    index = _build_included_index(payload["included"])

    # Pass 2: each appInfo -> follow-up GET with category includes.
    appinfo_categories: dict[str, tuple[str | None, str | None]] = {}
    for (typ, info_id), info in list(index.items()):
        if typ != "appInfos":
            continue
        r = get(
            f"/v1/appInfos/{info_id}",
            params={
                "include": "primaryCategory,secondaryCategory",
                "fields[appInfos]": "primaryCategory,secondaryCategory",
                "fields[appCategories]": "platforms",
            },
        )
        if not r.ok:
            continue
        j = r.json()
        info_full = j["data"]
        # update our index with the richer info record (preserves earlier attrs we set)
        # then read category ids
        rels = info_full.get("relationships", {})
        prim = ((rels.get("primaryCategory") or {}).get("data") or {}).get("id")
        sec = ((rels.get("secondaryCategory") or {}).get("data") or {}).get("id")
        appinfo_categories[info_id] = (prim, sec)

    # category id IS the human-readable code (e.g. "PRODUCTIVITY", "UTILITIES")
    category_names: dict[str, str] = {
        cat_id: cat_id
        for prim, sec in appinfo_categories.values()
        for cat_id in (prim, sec) if cat_id
    }

    # Compose per-app records
    records: list[dict[str, Any]] = []
    for app in apps:
        attrs = app.get("attributes", {})
        app_info_id = _rel_id(app, "appInfos")
        app_info = index.get(("appInfos", app_info_id)) if app_info_id else None
        version_ids = _rel_ids(app, "appStoreVersions")
        version = None
        for vid in version_ids:
            v = index.get(("appStoreVersions", vid))
            if v:
                version = v
                break

        primary_cat = secondary_cat = None
        appstore_state = age_rating = None
        if app_info:
            iattrs = app_info.get("attributes", {})
            appstore_state = iattrs.get("appStoreState")
            age_rating = iattrs.get("appStoreAgeRating")
        if app_info_id and app_info_id in appinfo_categories:
            primary_cat, secondary_cat = appinfo_categories[app_info_id]

        records.append({
            "id": app["id"],
            "name": attrs.get("name"),
            "bundleId": attrs.get("bundleId"),
            "sku": attrs.get("sku"),
            "primaryLocale": attrs.get("primaryLocale"),
            "contentRights": attrs.get("contentRightsDeclaration"),
            "madeForKids": attrs.get("isOrEverWasMadeForKids"),
            "appStoreState": appstore_state,
            "ageRating": age_rating,
            "primaryCategory": category_names.get(primary_cat, primary_cat),
            "secondaryCategory": category_names.get(secondary_cat, secondary_cat),
            "latestVersion": (version or {}).get("attributes", {}).get("versionString"),
            "latestVersionPlatform": (version or {}).get("attributes", {}).get("platform"),
            "latestVersionState": (version or {}).get("attributes", {}).get("appStoreState"),
            "latestVersionCreatedDate": (version or {}).get("attributes", {}).get("createdDate"),
        })

    records.sort(key=lambda r: (r.get("primaryCategory") or "ZZ", r["name"] or ""))
    return {"count": len(records), "apps": records}


def print_summary(meta: dict[str, Any]) -> None:
    apps = meta["apps"]
    print(f"\n=== {meta['count']} apps on this account ===\n")

    # Group by primary category
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in apps:
        by_cat[a.get("primaryCategory") or "(uncategorized)"].append(a)

    for cat, items in sorted(by_cat.items()):
        print(f"── {cat} ({len(items)}) " + "─" * max(0, 60 - len(cat) - len(str(len(items)))))
        for a in items:
            ver = a.get("latestVersion") or "?"
            state = a.get("latestVersionState") or a.get("appStoreState") or "?"
            plat = a.get("latestVersionPlatform") or ""
            print(f"  {a['name']!s:<45} v{ver:<8} {state:<22} {plat:<10} ({a['bundleId']})")
        print()

    # Status breakdown
    states: dict[str, int] = defaultdict(int)
    for a in apps:
        states[a.get("latestVersionState") or a.get("appStoreState") or "?"] += 1
    print("── Status breakdown " + "─" * 45)
    for s, n in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"  {s:<30} {n}")


def main() -> int:
    meta = fetch_all_metadata()
    OUT_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"[saved] {OUT_PATH} ({len(meta['apps'])} apps)")
    print_summary(meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
