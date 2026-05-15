"""Smoke test for the indie keyword-reference builder.

Top-5 CN-native apps (by indieScore_S, then est_monthly_downloads), LLM-extracted
ASO target keywords baked in, then runs Astro lookup_popularity_batch over the
deduped pool and writes a reference CSV + Markdown table.

This is the small-scale validation of the full pipeline. The 200-app version
will live in scripts/build_keyword_reference.py.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import astro_client  # noqa: E402
import appmate_config  # noqa: E402


APPS = [
    {
        "product_id": "41066047431",
        "name": "生辰 — 桌面时间小组件",
        "category": "lifestyle",
        "indie_score": 65.0,
        "dl_mo": 16767,
        "keywords": [
            "桌面小组件", "倒数日", "纪念日", "生命倒计时", "人生倒计时",
            "生日提醒", "桌面时钟", "时间小组件",
        ],
    },
    {
        "product_id": "42141224015",
        "name": "吾记 - 日记本,记事本",
        "category": "lifestyle",
        "indie_score": 65.0,
        "dl_mo": 16158,
        "keywords": [
            "日记本", "日记", "记事本", "笔记", "便签", "备忘录",
            "私密日记", "心情日记", "时间轴",
        ],
    },
    {
        "product_id": "334395804311",
        "name": "极简课程表 - watch课程表",
        "category": "education",
        "indie_score": 65.0,
        "dl_mo": 15857,
        "keywords": [
            "课程表", "大学课程表", "课表", "排课", "时间表", "学生课程表",
        ],
    },
    {
        "product_id": "213765551",
        "name": "小熊油耗-电车汽车摩托车能耗记录助手",
        "category": "finance",
        "indie_score": 65.0,
        "dl_mo": 12686,
        "keywords": [
            "油耗", "油耗记录", "汽车油耗", "加油记录", "用车账本", "节油", "油费",
        ],
    },
    {
        "product_id": "337361972365",
        "name": "海拔测量仪-实时高度表测海拔",
        "category": "lifestyle",
        "indie_score": 65.0,
        "dl_mo": 12405,
        "keywords": [
            "海拔", "海拔测量", "高度测量", "海拔仪", "指南针",
            "徒步", "登山", "户外", "气压", "路线记录",
        ],
    },
]

STORE = "cn"


def build_reverse_index(apps: list[dict]) -> dict[str, list[dict]]:
    """keyword -> [{product_id, name, category}, ...]"""
    rev: dict[str, list[dict]] = {}
    for a in apps:
        for kw in a["keywords"]:
            rev.setdefault(kw, []).append(
                {"product_id": a["product_id"], "name": a["name"], "category": a["category"]}
            )
    return rev


def main() -> None:
    rev = build_reverse_index(APPS)
    pool = sorted(rev.keys())
    print(f"=== Keyword pool: {len(pool)} unique (from {len(APPS)} apps) ===")
    for kw in pool:
        srcs = rev[kw]
        if len(srcs) > 1:
            print(f"  [shared x{len(srcs)}] {kw}  ←  {', '.join(s['name'][:12] for s in srcs)}")

    print(f"\n=== Astro batch lookup on store={STORE} ===")
    # Defaults: batch_size=10, add_timeout=300, recovers from HTTP read timeouts.
    results = astro_client.lookup_popularity_batch(pool, store=STORE)
    print(f"got {len(results)}/{len(pool)} entries back")

    # Build rows
    rows = []
    for kw in pool:
        r = results.get(kw) or {}
        sources = rev[kw]
        rows.append({
            "keyword": kw,
            "popularity": r.get("popularity"),
            "popularity_is_floor": bool(r.get("popularity_is_floor")),
            "difficulty": r.get("difficulty"),
            "apps_count": r.get("appsCount"),
            "source_apps_count": len(sources),
            "source_apps": "|".join(s["product_id"] for s in sources[:5]),
            "top_category": max({s["category"] for s in sources}, key=lambda c: sum(1 for s in sources if s["category"] == c)),
            "fetched_at": r.get("fetched_at"),
        })

    # Sort by popularity desc, fall back to source_apps_count
    rows.sort(key=lambda x: (-(x["popularity"] or 0), -(x["source_apps_count"])))

    csv_path = appmate_config.data_path(f"keyword_reference_smoke_{STORE}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {csv_path}")

    md_path = appmate_config.data_path(f"keyword_reference_smoke_{STORE}.md")
    lines = ["# Smoke-test keyword reference (CN top-5 indie apps)\n"]
    lines.append(f"Source: top-5 CN-native apps by indieScore_S | store={STORE} | {len(pool)} keywords")
    lines.append("`*` after pop = at Astro measurement floor (≤5), treat as no real signal\n")
    lines.append("| keyword | pop | diff | apps | from N app | top cat |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for r in rows:
        pop_cell = (
            f"{r['popularity']}*" if r["popularity_is_floor"]
            else (str(r["popularity"]) if r["popularity"] is not None else "-")
        )
        lines.append(
            f"| {r['keyword']} | {pop_cell} | {r['difficulty'] or '-'} | "
            f"{r['apps_count'] or '-'} | {r['source_apps_count']} | {r['top_category']} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md_path}")

    json_path = appmate_config.data_path(f"keyword_reference_smoke_{STORE}.json")
    json_path.write_text(json.dumps({"apps": APPS, "rows": rows}, ensure_ascii=False, indent=2))
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
