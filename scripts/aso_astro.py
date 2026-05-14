"""ASO report powered by Astro MCP data.

Astro tracks keyword rankings with:
  - popularity (1-99) — same as Apple Search Ads Popularity Index
  - difficulty (1-99) — how hard to rank
  - currentRanking + previousRanking + rankingChange (daily delta)
  - appsCount — competitive density

We combine this with our local metadata (apps_full.json) so we know which
tracked keywords came from main title (T), subtitle (S), or keywords field (K).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

import appmate_config
import astro_client
from aso_optimize import (
    COUNTRY_FLAG, PLATFORM_LABEL,
    find_top_market, pick_locales_for_country, latest_version_localizations,
    app_platform, tokenize_text,
)

APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
OUT = appmate_config.data_path("aso_astro.md")


def top_3_by_30d_downloads() -> tuple[list[dict[str, Any]], dt.date]:
    import sales_report as sr
    dates = sr.needed_dates()
    reports = json.loads(SALES_CACHE.read_text())
    reports = {d.isoformat(): reports.get(d.isoformat(), []) for d in dates}
    for d in sorted(dates, reverse=True):
        rows = reports.get(d.isoformat(), [])
        if rows and not any("_error" in r for r in rows):
            sr.DATA_TODAY = d
            break
    by_day = sr.aggregate_by_day(reports)
    dims = sr.build_dimensions(by_day)
    live = sr.load_live_apps()
    last30 = next(d for d in dims if d["label"].startswith("前30天"))
    ranked = sorted(
        ((name, m.get("downloads", 0)) for name, m in last30["current_data"].items() if name in live),
        key=lambda kv: -kv[1],
    )[:3]
    apps = json.loads(APPS_FULL.read_text())["apps"]
    name_to_app = {a["core"].get("name"): a for a in apps}
    return [name_to_app[n] for n, _ in ranked if n in name_to_app], sr.DATA_TODAY


def index_metadata_tokens(app: dict[str, Any], country: str) -> dict[str, set[str]]:
    """For the matching locale, return {token.lower() → source-tags}."""
    info_locs = (app.get("appInfo") or {}).get("localizations", [])
    info_by_locale = {L.get("locale"): L for L in info_locs}
    ver_locs = latest_version_localizations(app)
    ver_by_locale = {L.get("locale"): L for L in ver_locs}
    info_loc, ver_loc, _ = pick_locales_for_country(
        country, set(info_by_locale), set(ver_by_locale)
    )
    info = info_by_locale.get(info_loc) or {}
    ver = ver_by_locale.get(ver_loc) or {}
    tagged = tokenize_text(info.get("name"), info.get("subtitle"), ver.get("keywords"))
    return {k.lower(): v for k, v in tagged.items()}


def find_sources_for(keyword: str, token_index: dict[str, set[str]]) -> set[str]:
    """Best-effort match: exact (case-insensitive) OR substring containment."""
    kl = keyword.lower()
    if kl in token_index:
        return token_index[kl]
    # Substring fallback: if keyword overlaps with any indexed token
    out: set[str] = set()
    for tok, srcs in token_index.items():
        if tok in kl or kl in tok:
            out |= srcs
    return out


def _classify(row: dict[str, Any], in_meta: bool) -> tuple[str, str]:
    rank = row.get("currentRanking")
    pop = row.get("popularity") or 0
    diff = row.get("difficulty") or 0

    if rank and rank <= 5 and pop >= 30:
        return "🔥", "高价值核心词"
    if rank and rank <= 10 and pop >= 10:
        return "✅", "核心资产"
    if rank and rank <= 30 and pop >= 30:
        return "📈", "有潜力，可推进"
    if pop >= 30 and (not rank or rank > 50):
        return "🎯", "高热度但未排名，攻坚"
    if pop < 5 and rank and rank > 30:
        return "❌", "低热度+低排名，移除"
    if pop < 5 and in_meta:
        return "⚠️", "低热度，元数据浪费"
    return "—", ""


def fmt_pop(pop: int) -> str:
    if pop >= 50:
        return f"**{pop}** 🔥"
    if pop >= 20:
        return f"**{pop}**"
    return str(pop)


def fmt_diff(d: int) -> str:
    if d >= 70:
        return f"{d} 🔴"
    if d >= 50:
        return f"{d} 🟡"
    return f"{d} 🟢"


def fmt_rank_change(c: int) -> str:
    if c is None or c == 0:
        return "—"
    if c > 0:
        return f"↑{c}"
    return f"↓{abs(c)}"


def render_app(app: dict[str, Any], data_today: dt.date, reports: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    name = app["core"]["name"]
    bundle_id = app["core"]["bundleId"]
    platform = app_platform(app)
    plat_label = PLATFORM_LABEL.get(platform, platform)

    # Get App Store ID (Astro uses Apple's numeric ID, which matches our app["id"])
    app_store_id = app["id"]

    # Identify top market from our sales data
    top = find_top_market(name, reports, data_today)
    if not top:
        return [f"## {name} — no sales data\n"]
    top_country, dl30 = top
    top_country_lower = top_country.lower()

    # Pull all tracked keywords for this app
    tracked = astro_client.get_app_keywords(app_id=app_store_id)
    if not tracked:
        lines.append(f"## {name}  ·  {plat_label}")
        lines.append("")
        lines.append(f"**主市场**: {COUNTRY_FLAG.get(top_country, '🏳')} {top_country}  ·  近 30 日下载 **{dl30:,}**")
        lines.append("")
        lines.append("> ⚠️ 此 app 在 Astro 中尚未追踪。可调用 `astro_client.add_keywords()` 添加。")
        lines.append("")
        return lines

    # Group by store
    by_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kw in tracked:
        by_store[kw.get("store", "?")].append(kw)

    lines.append(f"## {name}  ·  {plat_label}")
    lines.append("")
    lines.append(f"**主市场**: {COUNTRY_FLAG.get(top_country, '🏳')} {top_country}  ·  近 30 日下载 **{dl30:,}**")
    lines.append("")
    lines.append(f"Astro 已追踪：{len(tracked)} 个词，分布在 {len(by_store)} 个 store")
    lines.append("")

    # Determine display order: top market first, then by keyword count
    store_order = sorted(by_store.keys(), key=lambda s: (
        0 if s == top_country_lower else 1,
        -len(by_store[s]),
    ))

    for store in store_order:
        kws = by_store[store]
        flag = COUNTRY_FLAG.get(store.upper(), "🏳")
        is_top = store == top_country_lower

        # Build metadata token index for this country
        token_index = index_metadata_tokens(app, store.upper())

        # Sort keywords by popularity desc within store, ties by rank asc
        kws_sorted = sorted(
            kws,
            key=lambda k: (-(k.get("popularity") or 0), k.get("currentRanking") or 999),
        )

        marker = " 🎯 主市场" if is_top else ""
        lines.append(f"### {flag} {store.upper()}{marker}  ·  {len(kws)} 个追踪词")
        lines.append("")
        lines.append("| 关键词 | 排名 | Δ | 热度 | 难度 | 竞品数 | 来源 | 建议 |")
        lines.append("|---|:-:|:-:|:-:|:-:|:-:|:-:|---|")
        for kw in kws_sorted:
            term = kw.get("keyword", "")
            rank = kw.get("currentRanking")
            change = kw.get("rankingChange")
            pop = kw.get("popularity") or 0
            diff = kw.get("difficulty") or 0
            comp = kw.get("appsCount") or 0
            note = kw.get("note", "")

            sources = find_sources_for(term, token_index)
            in_meta = bool(sources & {"T", "S", "K"})
            srcs_str = "".join(sorted(sources)) if sources else "·"

            rank_str = f"**#{rank}**" if rank and rank <= 10 else (f"#{rank}" if rank else ">200")
            emoji, label = _classify(kw, in_meta)
            note_suffix = f" {note}" if note else ""
            term_disp = (term + note_suffix).replace("|", "\\|")

            lines.append(
                f"| `{term_disp}` | {rank_str} | {fmt_rank_change(change)} | "
                f"{fmt_pop(pop)} | {fmt_diff(diff)} | {comp} | {srcs_str} | "
                f"{emoji} {label} |"
            )
        lines.append("")

    return lines


def main() -> int:
    apps, data_today = top_3_by_30d_downloads()
    reports = json.loads(SALES_CACHE.read_text())

    lines: list[str] = []
    lines.append("# 🎯 ASO 排名日报（Astro 数据）")
    lines.append("")
    lines.append(f"- 🕐 生成时间: **{dt.datetime.now():%Y-%m-%d %H:%M}**")
    lines.append(f"- 📅 销售数据: **{data_today:%Y-%m-%d}**")
    lines.append(f"- 📊 排名来源: Astro MCP（Apple Search Ads Popularity Index 1-99）")
    lines.append("")
    lines.append("> 来源标签 — **T**: 主标题 · **S**: 副标题 · **K**: 关键词字段 · **·**: 未在元数据中")
    lines.append("> 热度: 1-99（Apple 官方搜索量）  |  难度: 1-99（≥70 🔴 难, 50-69 🟡 中, <50 🟢 易）")
    lines.append("")
    lines.append("---")
    lines.append("")

    print(f"Generating for {len(apps)} apps…")
    for app in apps:
        print(f"  · {app['core'].get('name')}")
        lines.extend(render_app(app, data_today, reports))
        lines.append("---")
        lines.append("")

    md = "\n".join(lines)
    OUT.write_text(md)
    print(f"\n[saved] {OUT}")
    print()
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
