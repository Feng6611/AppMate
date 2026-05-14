"""Fetch app icon URLs from Apple's public iTunes Lookup API and cache them.

Output: app_icons.json — keyed by App Store ID, with artworkUrl60/100/512.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

import requests

import appmate_config

APPS_FULL = appmate_config.data_path("apps_full.json")
OUT = appmate_config.data_path("app_icons.json")


def main() -> int:
    apps = json.loads(APPS_FULL.read_text())["apps"]
    icons: dict[str, Any] = {}
    if OUT.exists():
        icons = json.loads(OUT.read_text())

    for a in apps:
        app_id = a["id"]
        name = (a.get("core") or {}).get("name", "?")
        if app_id in icons and icons[app_id].get("artworkUrl60"):
            print(f"  [cached] {name}")
            continue
        def fetch(url: str) -> Any:
            for attempt in range(5):
                try:
                    r = requests.get(url, timeout=15)
                    return r
                except (requests.ConnectionError, requests.Timeout):
                    time.sleep(0.5 * (2 ** attempt))
            return None

        r = fetch(f"https://itunes.apple.com/lookup?id={app_id}")
        if r is None:
            print(f"  [conn-err] {name}")
            continue
        if not r.ok:
            print(f"  [{r.status_code}] {name}")
            continue
        results = r.json().get("results", [])
        if not results:
            r = fetch(f"https://itunes.apple.com/lookup?id={app_id}&entity=macSoftware")
            results = (r.json().get("results", []) if r and r.ok else [])
        if not results:
            print(f"  [no-result] {name}  id={app_id}")
            icons[app_id] = {"name": name, "_no_result": True}
            continue
        rec = results[0]
        icons[app_id] = {
            "name": name,
            "trackName": rec.get("trackName"),
            "artworkUrl60": rec.get("artworkUrl60"),
            "artworkUrl100": rec.get("artworkUrl100"),
            "artworkUrl512": rec.get("artworkUrl512"),
            "primaryGenreName": rec.get("primaryGenreName"),
            "averageUserRating": rec.get("averageUserRating"),
            "userRatingCount": rec.get("userRatingCount"),
            "version": rec.get("version"),
            "trackViewUrl": rec.get("trackViewUrl"),
        }
        print(f"  [ok] {name}  → {rec.get('artworkUrl60')}")
        time.sleep(0.2)  # be polite to iTunes API

    OUT.write_text(json.dumps(icons, indent=2, ensure_ascii=False))
    n_ok = sum(1 for v in icons.values() if v.get("artworkUrl60"))
    print(f"\n[saved] {OUT}  ({n_ok}/{len(icons)} have icons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
