"""ASO daily report — target-keyword acquisition pipeline.

  1. For each top-3 app, find its single largest market (chosen by stable
     30-day download volume).
  2. Pull the title/subtitle/keywords for that market's locale and tokenize.
  3. Rank-check every candidate keyword via iTunes Search Top-200 (same
     source as the App Store web search).
  4. Only rank <= 20 counts as a "target keyword" and enters the target group.
  5. Look up popularity / difficulty / appsCount from the local keyword
     reference table (`data/keyword_reference_<region>.json`).
  6. Compare against yesterday's rank snapshot and report the delta.
  7. Render: app + yesterday's downloads (single number) + target-keyword
     table (sorted by popularity descending).

Rank snapshots are stored in aso_rank_snapshots.json, one entry per calendar day.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import time
from collections import defaultdict
from typing import Any

# Reuse infrastructure already built
import appmate_config
import keyword_local
from aso_optimize import (
    COUNTRY_FLAG, PLATFORM_TO_ENTITY, PLATFORM_LABEL,
    find_top_market, pick_locales_for_country,
    latest_version_localizations, app_platform,
    tokenize_text,
)
from aso_report import (
    is_download_ptid,
    rank_keyword as itunes_rank,
    load_rank_cache, save_rank_cache,
)

APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
RANK_SNAPSHOTS = appmate_config.data_path("aso_rank_snapshots.json")
OUT = appmate_config.data_path("aso_daily.md")

TARGET_RANK_CEILING = 20  # only rank <= this value counts as a "target keyword"


# ---------------------------------------------------------------------------
# Snapshot store
# ---------------------------------------------------------------------------
def load_snapshots() -> dict[str, Any]:
    return json.loads(RANK_SNAPSHOTS.read_text()) if RANK_SNAPSHOTS.exists() else {}


def save_snapshots(s: dict[str, Any]) -> None:
    RANK_SNAPSHOTS.write_text(json.dumps(s, ensure_ascii=False, indent=2))


def snapshot_set(snapshots: dict[str, Any], date_iso: str, bundle_id: str, country: str, keyword: str, rank: int | None) -> None:
    snapshots.setdefault(date_iso, {}).setdefault(bundle_id, {}).setdefault(country, {})[keyword] = rank


def snapshot_get(snapshots: dict[str, Any], date_iso: str, bundle_id: str, country: str, keyword: str) -> int | None:
    return ((snapshots.get(date_iso) or {}).get(bundle_id) or {}).get(country, {}).get(keyword)


# ---------------------------------------------------------------------------
# Pipeline pieces
# ---------------------------------------------------------------------------
def yesterday_downloads(reports: dict[str, Any], app_name: str, country: str, date_iso: str) -> int:
    """Sum downloads for the given app + country on a single day."""
    rows = reports.get(date_iso, [])
    n = 0
    for r in rows:
        if "_error" in r:
            continue
        if r.get("Title") != app_name:
            continue
        if r.get("Country Code") != country:
            continue
        if not is_download_ptid(r.get("Product Type Identifier") or ""):
            continue
        try:
            n += int(r.get("Units") or 0)
        except ValueError:
            pass
    return n


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
    last30 = next(d for d in dims if d["label"] == "Last 30 days")
    ranked = sorted(
        ((name, m.get("downloads", 0)) for name, m in last30["current_data"].items() if name in live),
        key=lambda kv: -kv[1],
    )[:3]
    apps = json.loads(APPS_FULL.read_text())["apps"]
    name_to_app = {a["core"].get("name"): a for a in apps}
    return [name_to_app[n] for n, _ in ranked if n in name_to_app], sr.DATA_TODAY


def _count_cjk(s: str) -> int:
    """Count CJK characters (Chinese / Japanese kana / Korean Hangul)."""
    return sum(
        1 for c in s
        if "一" <= c <= "鿿"  # CJK Unified Ideographs
        or "぀" <= c <= "ヿ"  # Japanese hiragana + katakana
        or "가" <= c <= "힣"  # Korean Hangul syllables
    )


def _good_token(t: str) -> bool:
    if len(t) < 2:
        return False
    if re.fullmatch(r"[A-Za-z]+", t) and len(t) <= 4 and t.lower() in {"app", "pro", "ios", "mac", "art", "key"}:
        return False
    if t.isdigit():
        return False
    # Reject tokenization failures: long stretches of consecutive CJK chars
    # (real ASO target words are typically 2-5 CJK chars; anything 6+ is
    # almost always multiple keywords mashed together by missing commas).
    if _count_cjk(t) >= 6:
        return False
    # Reject very long Latin phrases (users rarely type 25+ char queries).
    if _count_cjk(t) == 0 and len(t) > 25:
        return False
    return True


def analyze_app(
    app: dict[str, Any],
    reports: dict[str, Any],
    data_today: dt.date,
    today_iso: str,
    rank_cache: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any] | None:
    name = app["core"]["name"]
    bundle_id = app["core"]["bundleId"]
    platform = app_platform(app)
    entity = PLATFORM_TO_ENTITY.get(platform, "software")

    # Step 1 — find single biggest market (by 30-day downloads, more stable)
    top = find_top_market(name, reports, data_today)
    if not top:
        return None
    country, dl30 = top

    # Step 2 — locale metadata for that market
    info_locs = (app.get("appInfo") or {}).get("localizations", [])
    info_by_locale = {L.get("locale"): L for L in info_locs}
    ver_locs = latest_version_localizations(app)
    ver_by_locale = {L.get("locale"): L for L in ver_locs}
    info_loc, ver_loc, is_localized = pick_locales_for_country(
        country, set(info_by_locale), set(ver_by_locale)
    )
    info = info_by_locale.get(info_loc) or {}
    ver = ver_by_locale.get(ver_loc) or {}
    title = info.get("name")
    subtitle = info.get("subtitle")
    keywords_raw = ver.get("keywords")

    # Yesterday's (DATA_TODAY's) downloads in that country
    yday_dl = yesterday_downloads(reports, name, country, data_today.isoformat())

    # Step 3 — tokenize + rank
    token_sources = tokenize_text(title, subtitle, keywords_raw)
    candidates = [t for t in token_sources if _good_token(t)]
    print(f"  {name} · {country}: {len(candidates)} candidate tokens", flush=True)

    ranks_today: dict[str, int | None] = {}
    for kw in candidates:
        pos = itunes_rank(kw, country, entity, bundle_id, rank_cache)
        ranks_today[kw] = pos
        snapshot_set(snapshots, today_iso, bundle_id, country, kw, pos)
        time.sleep(0.10)

    # Step 4 — filter to "target words" (rank ≤ 20)
    target_words = {
        kw: pos for kw, pos in ranks_today.items()
        if pos is not None and pos <= TARGET_RANK_CEILING
    }
    print(f"    {len(target_words)} target words (rank ≤ {TARGET_RANK_CEILING})", flush=True)

    # Step 5 — popularity / difficulty from the local keyword reference
    if target_words:
        pop_map = keyword_local.lookup_popularity_batch(list(target_words), country.lower())
    else:
        pop_map = {}

    # Step 6 — Δ vs yesterday
    yday_iso = (dt.date.fromisoformat(today_iso) - dt.timedelta(days=1)).isoformat()
    rows: list[dict[str, Any]] = []
    for kw, today_rank in target_words.items():
        rec = pop_map.get(kw) or {}
        prev_rank = snapshot_get(snapshots, yday_iso, bundle_id, country, kw)
        rows.append({
            "keyword": kw,
            "rank": today_rank,
            "prev_rank": prev_rank,
            "popularity": rec.get("popularity"),
            "difficulty": rec.get("difficulty"),
            "apps_count": rec.get("appsCount"),
        })
    # Sort by popularity desc (None last), tiebreak rank asc
    rows.sort(key=lambda r: (-(r.get("popularity") or 0), r.get("rank") or 999))

    return {
        "name": name,
        "bundle_id": bundle_id,
        "platform": platform,
        "country": country,
        "is_localized": is_localized,
        "downloads_yesterday": yday_dl,
        "title": title,
        "subtitle": subtitle,
        "keywords_raw": keywords_raw,
        "target_words": rows,
        "total_candidates": len(candidates),
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _delta(today: int | None, yday: int | None) -> str:
    if today is None or yday is None:
        return "—"
    diff = yday - today  # positive = rank improved (smaller number is better)
    if diff > 0:
        return f"↑{diff}"
    if diff < 0:
        return f"↓{abs(diff)}"
    return "—"


def _fmt_pop(p: int | None) -> str:
    if p is None:
        return "—"
    if p >= 50:
        return f"**{p}** 🔥"
    if p >= 20:
        return f"**{p}**"
    return str(p)


def _fmt_diff(d: int | None) -> str:
    if d is None:
        return "—"
    if d >= 70:
        return f"{d} 🔴"
    if d >= 50:
        return f"{d} 🟡"
    return f"{d} 🟢"


def render(results: list[dict[str, Any]], data_today: dt.date) -> str:
    lines: list[str] = []
    lines.append("# 🎯 ASO Daily Report")
    lines.append("")
    lines.append(f"**Yesterday ({data_today:%m-%d}) data · Rank = App Store web search · Popularity/difficulty = internal metric**")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, R in enumerate(results, 1):
        flag = COUNTRY_FLAG.get(R["country"], "🏳")
        plat_label = PLATFORM_LABEL.get(R["platform"], R["platform"])

        lines.append(f"## {idx}. {R['name']}  ·  {plat_label}  ·  {flag} {R['country']}")
        lines.append("")
        lines.append(f"Downloads yesterday **{R['downloads_yesterday']:,}**  ·  target keywords **{len(R['target_words'])}** (rank ≤ {TARGET_RANK_CEILING}, filtered from {R['total_candidates']} candidates)")
        if not R["is_localized"]:
            lines.append("")
            lines.append(f"> ⚠️ This app has no localization for the {R['country']} language family")
        lines.append("")

        if not R["target_words"]:
            lines.append("> No target keywords with rank ≤ 20.")
            lines.append("")
        else:
            lines.append("| Keyword | Rank | Δ | Popularity | Difficulty |")
            lines.append("|---|:-:|:-:|:-:|:-:|")
            for row in R["target_words"]:
                kw_disp = row["keyword"].replace("|", "\\|")
                rank = row["rank"]
                rank_str = f"**#{rank}**" if rank and rank <= 10 else f"#{rank}"
                delta_str = _delta(rank, row.get("prev_rank"))
                pop_str = _fmt_pop(row.get("popularity"))
                diff_str = _fmt_diff(row.get("difficulty"))
                lines.append(f"| `{kw_disp}` | {rank_str} | {delta_str} | {pop_str} | {diff_str} |")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    import key_safety
    key_safety.require_safe_key_or_exit()
    apps, data_today = top_3_by_30d_downloads()
    if not apps:
        print("No apps found.", file=sys.stderr)
        return 1
    reports = json.loads(SALES_CACHE.read_text())
    rank_cache = load_rank_cache()
    snapshots = load_snapshots()
    today_iso = dt.date.today().isoformat()

    print(f"Top-3 apps · data anchored to {data_today}")
    for i, a in enumerate(apps, 1):
        print(f"  {i}. {a['core'].get('name')}")
    print()

    results: list[dict[str, Any]] = []
    for app in apps:
        r = analyze_app(app, reports, data_today, today_iso, rank_cache, snapshots)
        if r:
            results.append(r)
        save_rank_cache(rank_cache)
        save_snapshots(snapshots)

    md = render(results, data_today)
    OUT.write_text(md)
    print(f"\n[saved] {OUT}")
    print()
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
