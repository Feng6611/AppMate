"""Build the indie keyword reference table.

Pipeline (LLM extracts keywords, this script orchestrates the deterministic work):

  1. prepare    — read apps_scored_full.csv, pick top-N apps per region,
                  write data/indie_apps_<region>_top<N>.json. CN filters to
                  apps with native Chinese metadata so extracted keywords
                  match what an Astro <cn> lookup would actually find.

  2. (external) — dispatch subagents to read the apps JSON and write
                  data/keyword_extraction/<region>_batch_<NN>.json files
                  with {product_id, keywords} per app.

  3. aggregate  — read all batch files, dedupe, build reverse index
                  (keyword -> [{product_id, name, category}]).

  4. query      — call astro_client.lookup_popularity_batch on the pool;
                  results land in data/astro_popularity_cache.json.

  5. render     — write data/keyword_reference_<region>.{csv,md,json}.

Usage:
  python build_keyword_reference.py prepare --region cn --top 100
  python build_keyword_reference.py aggregate --region cn
  python build_keyword_reference.py query     --region cn
  python build_keyword_reference.py render    --region cn
  python build_keyword_reference.py all       --region cn   # 3 + 4 + 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import astro_client  # noqa: E402
import appmate_config  # noqa: E402


CSV_PATH = Path("/Users/fengyq/Desktop/AppMateMax/apps_scored_full.csv")


def _has_chinese(s: str, min_count: int = 20) -> bool:
    return len(re.findall(r"[一-鿿]", s)) >= min_count


# ---------------------------------------------------------------------------
# Phase 1: prepare app list
# ---------------------------------------------------------------------------
def prepare(region: str, top_n: int) -> Path:
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if region == "cn":
        pool = [
            r for r in rows
            if r["region"] == "CN" and _has_chinese(r["name"] + r["description"])
        ]
    elif region == "us":
        pool = [r for r in rows if r["region"] == "US"]
    else:
        raise ValueError(f"unsupported region: {region}")

    def _key(r: dict) -> tuple[float, int]:
        try:
            return (-float(r["indieScore_S"]), -int(r["est_monthly_downloads"] or 0))
        except ValueError:
            return (0.0, 0)

    pool.sort(key=_key)
    top = pool[:top_n]

    out = []
    for r in top:
        out.append({
            "product_id": r["product_id"],
            "name": r["name"],
            "category": r["category"],
            "category_slug": r["category_slug"],
            "indie_score": float(r["indieScore_S"]),
            "est_monthly_downloads": int(r["est_monthly_downloads"] or 0),
            "rating": float(r["rating"] or 0),
            "description": r["description"],
            "app_store_link": r["app_store_link"],
        })

    path = appmate_config.data_path(f"indie_apps_{region}_top{top_n}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[prepare] wrote {len(out)} apps to {path}")
    return path


# ---------------------------------------------------------------------------
# Phase 3: aggregate subagent outputs
# ---------------------------------------------------------------------------
def aggregate(region: str) -> tuple[Path, Path]:
    extract_dir = appmate_config.data_path("keyword_extraction")
    batch_files = sorted(extract_dir.glob(f"{region}_batch_*.json"))
    if not batch_files:
        raise FileNotFoundError(f"no batch files under {extract_dir} matching {region}_batch_*.json")

    apps_path = appmate_config.data_path(f"indie_apps_{region}_top100.json")
    # tolerate other sizes
    candidates = sorted(appmate_config.data_path(".").glob(f"indie_apps_{region}_top*.json"))
    if candidates and not apps_path.exists():
        apps_path = candidates[0]
    apps = {a["product_id"]: a for a in json.loads(apps_path.read_text())}

    rev: dict[str, list[dict]] = {}
    app_keywords: dict[str, list[str]] = {}
    seen_apps: set[str] = set()
    for bf in batch_files:
        try:
            batch = json.loads(bf.read_text())
        except json.JSONDecodeError as e:
            print(f"[aggregate] WARN: {bf.name} malformed: {e}")
            continue
        for entry in batch:
            pid = str(entry.get("product_id"))
            kws = [k.strip() for k in entry.get("keywords", []) if k and k.strip()]
            if not pid or not kws:
                continue
            seen_apps.add(pid)
            app_keywords[pid] = kws
            app_info = apps.get(pid, {})
            for kw in kws:
                rev.setdefault(kw, []).append({
                    "product_id": pid,
                    "name": app_info.get("name", "?"),
                    "category": app_info.get("category_slug", "?"),
                })

    pool_path = appmate_config.data_path(f"keyword_pool_{region}.json")
    pool_path.write_text(json.dumps({
        "region": region,
        "n_apps_covered": len(seen_apps),
        "n_apps_total": len(apps),
        "n_keywords": len(rev),
        "keywords": sorted(rev.keys()),
        "reverse_index": rev,
        "per_app": app_keywords,
    }, ensure_ascii=False, indent=2))
    print(f"[aggregate] {len(rev)} unique keywords from {len(seen_apps)}/{len(apps)} apps → {pool_path}")
    return pool_path, apps_path


# ---------------------------------------------------------------------------
# Phase 4: Astro lookup
# ---------------------------------------------------------------------------
def query(region: str) -> Path:
    pool_path = appmate_config.data_path(f"keyword_pool_{region}.json")
    pool = json.loads(pool_path.read_text())
    keywords = pool["keywords"]

    print(f"[query] looking up {len(keywords)} keywords on store={region} (cache-aware)…")
    t0 = time.time()
    results = astro_client.lookup_popularity_batch(keywords, store=region)
    elapsed = time.time() - t0
    print(f"[query] got {len(results)}/{len(keywords)} entries in {elapsed:.0f}s")

    out_path = appmate_config.data_path(f"keyword_astro_{region}.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return out_path


# ---------------------------------------------------------------------------
# Phase 5: render
# ---------------------------------------------------------------------------
def render(region: str) -> dict[str, Path]:
    pool = json.loads(appmate_config.data_path(f"keyword_pool_{region}.json").read_text())
    astro = json.loads(appmate_config.data_path(f"keyword_astro_{region}.json").read_text())
    rev = pool["reverse_index"]

    rows = []
    for kw, sources in rev.items():
        r = astro.get(kw) or {}
        cats = [s["category"] for s in sources]
        top_cat = max(set(cats), key=cats.count) if cats else "?"
        rows.append({
            "keyword": kw,
            "popularity": r.get("popularity"),
            "popularity_is_floor": bool(r.get("popularity_is_floor")),
            "difficulty": r.get("difficulty"),
            "apps_count": r.get("appsCount"),
            "source_apps_count": len(sources),
            "source_apps": "|".join(s["product_id"] for s in sources[:5]),
            "top_category": top_cat,
            "fetched_at": r.get("fetched_at"),
        })

    rows.sort(key=lambda x: (
        -(x["popularity"] or 0),
        -x["source_apps_count"],
        x["keyword"],
    ))

    csv_path = appmate_config.data_path(f"keyword_reference_{region}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    md_path = appmate_config.data_path(f"keyword_reference_{region}.md")
    floor_count = sum(1 for r in rows if r["popularity_is_floor"])
    real_count = len(rows) - floor_count
    head = [
        f"# Indie keyword reference — {region.upper()} store",
        "",
        f"Source: top {pool['n_apps_covered']} CN-native indie apps by indieScore_S"
        if region == "cn" else
        f"Source: top {pool['n_apps_covered']} US indie apps by indieScore_S",
        f"{len(rows)} unique keywords ({real_count} with real signal · {floor_count} at Astro floor)",
        "`*` after pop = at Astro measurement floor (≤5); treat as no real search-volume signal",
        "",
        "| keyword | pop | diff | apps | from N | top cat |",
        "|---|---:|---:|---:|---:|---|",
    ]
    body = []
    for r in rows:
        pop_cell = (
            f"{r['popularity']}*" if r["popularity_is_floor"]
            else (str(r["popularity"]) if r["popularity"] is not None else "-")
        )
        body.append(
            f"| {r['keyword']} | {pop_cell} | {r['difficulty'] or '-'} | "
            f"{r['apps_count'] or '-'} | {r['source_apps_count']} | {r['top_category']} |"
        )
    md_path.write_text("\n".join(head + body))

    json_path = appmate_config.data_path(f"keyword_reference_{region}.json")
    json_path.write_text(json.dumps({"region": region, "rows": rows}, ensure_ascii=False, indent=2))

    print(f"[render] wrote {csv_path}")
    print(f"[render] wrote {md_path}")
    print(f"[render] wrote {json_path}")
    return {"csv": csv_path, "md": md_path, "json": json_path}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["prepare", "aggregate", "query", "render", "all"])
    p.add_argument("--region", choices=["cn", "us"], required=True)
    p.add_argument("--top", type=int, default=100)
    args = p.parse_args()

    if args.phase == "prepare":
        prepare(args.region, args.top)
    elif args.phase == "aggregate":
        aggregate(args.region)
    elif args.phase == "query":
        query(args.region)
    elif args.phase == "render":
        render(args.region)
    elif args.phase == "all":
        aggregate(args.region)
        query(args.region)
        render(args.region)


if __name__ == "__main__":
    main()
