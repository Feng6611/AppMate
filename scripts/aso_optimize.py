"""ASO Optimizer.

Approach: each app has a single dominant market (e.g. GBrowser → CN, Mirror → TR).
For that market we:

  1. Pull the matching locale's title/subtitle/keywords from apps_full.json.
  2. Tokenize them into seed words.
  3. For every seed, hit Apple's public Suggestions endpoint (the one App Store's
     search box uses) → returns up to 10 popular completions ordered by Apple's
     internal popularity signal.
  4. The union of (metadata tokens ∪ all hints) becomes the keyword universe.
  5. For every keyword in the universe, query iTunes Search top-200 in that
     storefront to get the app's actual rank.
  6. Produce an actionable table: which words to keep / replace / drop / add.

Suggestions endpoint:
  GET https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints
  ?clientApplication=Software&term=<seed>
  Headers: X-Apple-Store-Front: <country storefront id>
  Returns: plist XML with {hints: [{term, url}, …]}
  Ordering: most-searched completion first.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import plistlib
import re
import sys
import time
from collections import defaultdict
from typing import Any

import requests

# Reuse parts of aso_report
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import appmate_config
from aso_report import (
    LOCALE_TO_COUNTRY, COUNTRY_FLAG, PLATFORM_TO_ENTITY, PLATFORM_LABEL,
    is_download_ptid, per_country_downloads_range,
    rank_keyword as itunes_rank, load_rank_cache, save_rank_cache,
    tokenize_text, latest_version_localizations, app_platform,
)

APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
HINTS_CACHE = appmate_config.data_path("aso_hints_cache.json")
OUT = appmate_config.data_path("aso_optimize.md")

HINTS_URL = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
USER_AGENT = "iTunes/12.13.6 (Macintosh; OS X 14.0; en_US)"

# Country code → Apple storefront ID. iOS App Store suffix `-1,29`.
STOREFRONT_ID: dict[str, str] = {
    "US": "143441", "GB": "143444", "CA": "143455", "AU": "143460",
    "DE": "143443", "FR": "143442", "IT": "143450", "ES": "143454",
    "PT": "143453", "NL": "143452", "BE": "143446",
    "SE": "143456", "NO": "143457", "FI": "143447", "DK": "143458",
    "PL": "143478", "CZ": "143489", "RO": "143487",
    "RU": "143469", "UA": "143492", "HU": "143482", "GR": "143448",
    "CN": "143465", "TW": "143470", "HK": "143463",
    "JP": "143462", "KR": "143466",
    "TH": "143475", "ID": "143476", "MY": "143473", "PH": "143474",
    "VN": "143471", "SG": "143464",
    "TR": "143480", "IL": "143491", "AE": "143481", "SA": "143479",
    "EG": "143516", "ZA": "143472",
    "BR": "143503", "MX": "143468", "AR": "143505", "CL": "143483",
    "CO": "143501", "PE": "143507", "EC": "143509",
    "IN": "143467",
}

# Country → preferred locale match for keyword extraction.
COUNTRY_TO_LOCALE_FALLBACK = {
    "US": ["en-US", "en-GB", "en-CA", "en-AU"],
    "GB": ["en-GB", "en-US"],
    "CA": ["en-CA", "fr-CA", "en-US"],
    "AU": ["en-AU", "en-US"],
    "CN": ["zh-Hans"],
    "TW": ["zh-Hant", "zh-Hans"],
    "HK": ["zh-Hant", "zh-Hans", "en-GB"],
    "JP": ["ja"],
    "KR": ["ko"],
    "DE": ["de-DE"], "AT": ["de-DE"], "CH": ["de-DE", "fr-FR", "it"],
    "FR": ["fr-FR"], "BE": ["fr-FR", "nl-NL"], "LU": ["fr-FR", "de-DE"],
    "ES": ["es-ES", "ca"], "MX": ["es-MX", "es-ES"], "AR": ["es-ES"],
    "BR": ["pt-BR", "pt-PT"], "PT": ["pt-PT", "pt-BR"],
    "IT": ["it"],
    "RU": ["ru"], "UA": ["uk", "ru"],
    "TR": ["tr"], "GR": ["el"],
    "TH": ["th"], "ID": ["id"], "MY": ["ms", "en-US"], "VN": ["vi"],
    "SG": ["en-US", "zh-Hans"], "PH": ["en-US"],
    "SA": ["ar-SA"], "AE": ["ar-SA"], "EG": ["ar-SA"], "IL": ["he"],
    "SE": ["sv"], "NO": ["no"], "FI": ["fi"], "DK": ["da"],
    "PL": ["pl"], "HU": ["hu"], "NL": ["nl-NL"], "CZ": ["cs"], "RO": ["ro"],
    "IN": ["en-US"],
}


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------
def load_hints_cache() -> dict[str, Any]:
    return json.loads(HINTS_CACHE.read_text()) if HINTS_CACHE.exists() else {}


def save_hints_cache(c: dict[str, Any]) -> None:
    HINTS_CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=2))


def fetch_hints(term: str, country: str, cache: dict[str, Any], retries: int = 4) -> list[str]:
    """Returns ordered list of completion suggestions for `term` in `country` storefront."""
    cache_key = f"{country}|{term.lower()}"
    if cache_key in cache:
        return cache[cache_key].get("hints", [])
    sf = STOREFRONT_ID.get(country)
    if not sf:
        return []
    headers = {"User-Agent": USER_AGENT, "X-Apple-Store-Front": sf}
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.get(
                HINTS_URL,
                params={"clientApplication": "Software", "term": term},
                headers=headers,
                timeout=15,
            )
            if r.status_code != 200:
                cache[cache_key] = {"_status": r.status_code, "hints": []}
                return []
            j = plistlib.loads(r.content)
            hints = [h.get("term") for h in (j.get("hints") or []) if h.get("term")]
            cache[cache_key] = {"hints": hints}
            return hints
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    cache[cache_key] = {"_error": f"{type(last_exc).__name__}", "hints": []}
    return []


# ---------------------------------------------------------------------------
# Sales / top market
# ---------------------------------------------------------------------------
def per_country_downloads_for_app(
    reports: dict[str, Any], app_name: str, start: dt.date, end: dt.date
) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    d = start
    while d <= end:
        rows = reports.get(d.isoformat(), [])
        for r in rows:
            if "_error" in r:
                continue
            if r.get("Title") != app_name:
                continue
            ptid = r.get("Product Type Identifier") or ""
            if not is_download_ptid(ptid):
                continue
            try:
                units = int(r.get("Units") or 0)
            except ValueError:
                units = 0
            country = r.get("Country Code") or "?"
            out[country] += units
        d += dt.timedelta(days=1)
    return dict(out)


def find_top_market(
    app_name: str, reports: dict[str, Any], data_today: dt.date
) -> tuple[str, int] | None:
    """Returns (country, total_30d_downloads) or None."""
    by_country = per_country_downloads_for_app(
        reports, app_name, data_today - dt.timedelta(days=29), data_today
    )
    if not by_country:
        return None
    return max(by_country.items(), key=lambda kv: kv[1])


def pick_locale_for_country(
    country: str, available_locales: set[str]
) -> tuple[str | None, bool]:
    """Returns (locale, is_exact_match). is_exact_match=False means we fell back."""
    for loc in COUNTRY_TO_LOCALE_FALLBACK.get(country, []):
        if loc in available_locales:
            return loc, True
    if "en-US" in available_locales:
        return "en-US", False
    return (sorted(available_locales)[0] if available_locales else None, False)


def pick_locales_for_country(
    country: str,
    info_locales: set[str],
    ver_locales: set[str],
) -> tuple[str | None, str | None, bool]:
    """Pick best (info_locale, ver_locale, is_localized) for the country.
    info_locale and ver_locale may differ — Apple lets you set them independently.
    is_localized=False if neither matches the country language family."""
    chain = COUNTRY_TO_LOCALE_FALLBACK.get(country, []) + ["en-US"]
    info_loc = next((l for l in chain if l in info_locales), None)
    ver_loc = next((l for l in chain if l in ver_locales), None)
    is_localized = info_loc is not None or ver_loc is not None
    # If nothing in the language family, fall back to alphabetically first
    if info_loc is None and info_locales:
        info_loc = sorted(info_locales)[0]
    if ver_loc is None and ver_locales:
        ver_loc = sorted(ver_locales)[0]
    return info_loc, ver_loc, is_localized


# ---------------------------------------------------------------------------
# Top-3 selection
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze_app(
    app: dict[str, Any],
    reports: dict[str, Any],
    data_today: dt.date,
    rank_cache: dict[str, Any],
    hints_cache: dict[str, Any],
) -> dict[str, Any] | None:
    name = app["core"].get("name")
    bundle_id = app["core"].get("bundleId")
    platform = app_platform(app)
    entity = PLATFORM_TO_ENTITY.get(platform, "software")

    top_market = find_top_market(name, reports, data_today)
    if not top_market:
        return None
    country, dl30 = top_market

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
    locale = info_loc if info_loc == ver_loc else f"{info_loc or '—'} / {ver_loc or '—'}"

    # Tokenize metadata
    token_sources = tokenize_text(title, subtitle, keywords_raw)  # {token: {T/S/K}}

    # Filter seeds to avoid noise: drop very short / English low-signal tokens
    # that produce mostly irrelevant suggestions (e.g. "Pro" → procreate/protake).
    def _good_seed(t: str) -> bool:
        if len(t) < 3:
            return False
        # Skip Latin-only tokens of 3-4 chars (too noisy as a search prefix)
        if re.fullmatch(r"[A-Za-z]+", t) and len(t) <= 4:
            if t.lower() in {"app", "pro", "ios", "mac", "art", "key"}:
                return False
        # Skip pure digits
        if t.isdigit():
            return False
        return True

    seeds = [t for t in token_sources if _good_seed(t)][:20]

    # Hit suggestions for each filtered seed. Aggregate hints with positions.
    hint_to_positions: dict[str, list[tuple[str, int]]] = defaultdict(list)
    seeds_processed: list[tuple[str, list[str]]] = []
    for token in seeds:
        print(f"  hints · {country} · {token[:40]}", flush=True)
        hints = fetch_hints(token, country, hints_cache)
        seeds_processed.append((token, hints))
        for pos, h in enumerate(hints, 1):
            # Only keep the BEST (lowest) position across all seeds that surfaced this hint
            hint_to_positions[h].append((token, pos))
        time.sleep(0.15)

    # Build keyword universe: metadata tokens + all distinct hints
    universe: dict[str, dict[str, Any]] = {}
    for tok, srcs in token_sources.items():
        universe[tok] = {
            "sources": set(srcs),
            "hint_best_pos": None,
            "hint_seed_count": 0,
            "rank": None,
        }
    for hint_term, refs in hint_to_positions.items():
        # Dedupe vs existing metadata tokens (case-insensitive)
        existing = next((k for k in universe if k.lower() == hint_term.lower()), None)
        if existing:
            slot = universe[existing]
        else:
            universe[hint_term] = slot = {
                "sources": set(),
                "hint_best_pos": None,
                "hint_seed_count": 0,
                "rank": None,
            }
        slot["hint_best_pos"] = min(p for _, p in refs)
        slot["hint_seed_count"] = len(refs)
        if not slot["sources"]:
            slot["sources"].add("X")  # X = external (Apple-suggested, not in metadata)

    # Rank-check every keyword in the universe via iTunes Search (App Store webpage)
    print(f"  ranking {len(universe)} keywords for {country}/{entity}…", flush=True)
    for kw in list(universe):
        pos = itunes_rank(kw, country, entity, bundle_id, rank_cache)
        universe[kw]["rank"] = pos
        time.sleep(0.12)

    # Fetch popularity + difficulty for the same keyword universe
    import keyword_local
    store_code = country.lower()
    print(f"  fetching popularity for {len(universe)} keywords in {store_code}…", flush=True)
    pop_map = keyword_local.lookup_popularity_batch(list(universe), store_code)
    for kw, slot in universe.items():
        rec = pop_map.get(kw) or {}
        slot["popularity"] = rec.get("popularity")
        slot["difficulty"] = rec.get("difficulty")
        slot["apps_count"] = rec.get("appsCount")

    return {
        "name": name,
        "bundle_id": bundle_id,
        "platform": platform,
        "country": country,
        "locale": locale,
        "is_localized": is_localized,
        "downloads_30d": dl30,
        "title": title,
        "subtitle": subtitle,
        "keywords_raw": keywords_raw,
        "universe": universe,
        "seeds": seeds_processed,
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def _classify(slot: dict[str, Any]) -> tuple[str, str]:
    """(emoji, label) — actionable category. Uses the popularity (1-99) signal
    from the keyword reference; iTunes Suggestions only as a fallback hint."""
    rank = slot["rank"]
    pop = slot.get("popularity") or 0
    diff = slot.get("difficulty") or 0
    srcs = slot["sources"]
    has_meta = bool(srcs & {"T", "S", "K"})

    # 🔥 High-value core: in metadata + rank ≤ 10 + popularity ≥ 30
    if has_meta and rank and rank <= 10 and pop >= 30:
        return "🔥", "高价值核心词"

    # ✅ Solid asset: in metadata + good rank
    if has_meta and rank and rank <= 10:
        return "✅", "保留 / 核心"
    if has_meta and rank and rank <= 50 and pop >= 10:
        return "✅", "保留"

    # ➕ Easy win: NOT in metadata + Apple ranks you ≤ 50 + popularity ≥ 30
    if not has_meta and rank and rank <= 50 and pop >= 30:
        return "➕", "新增（高热度且已有排名）"

    # 🎯 Aspirational: high popularity but rank weak — needs work
    if pop >= 50 and (not rank or rank > 50):
        return "🎯", "高热度但暂无排名 — 需要冲刺"

    # 🔁 In metadata + has popularity, but rank weak — copy needs fixing
    if has_meta and pop >= 10 and (not rank or rank > 50):
        return "🔁", "已在元数据中但排名弱 — 文案需要调整"

    # ❌ Drop: in metadata + pop < 5 + (no rank OR rank > 100)
    if has_meta and pop < 5 and (not rank or rank > 100):
        return "❌", "删除（无热度、无排名）"

    return "", ""


def render(results: list[dict[str, Any]], data_today: dt.date) -> str:
    lines: list[str] = []
    lines.append("# 🎯 ASO 优化日报（单市场聚焦）")
    lines.append("")
    lines.append(f"- 🕐 生成时间: **{dt.datetime.now():%Y-%m-%d %H:%M}**")
    lines.append(f"- 📅 销售数据日期: **{data_today:%Y-%m-%d}**")
    lines.append(f"- 📊 排名: iTunes Search Top-200（与 App Store 网页搜索同源）")
    lines.append(f"- 🔥 热度 / 难度: 内部指标（1-99）")
    lines.append("")
    lines.append("> 来源 — **T**: 标题 · **S**: 副标题 · **K**: 关键词字段 · **X**: Apple Suggestions 新发现")
    lines.append("> 难度: ≥70 🔴 高，50-69 🟡 中，<50 🟢 低")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, R in enumerate(results, 1):
        flag = COUNTRY_FLAG.get(R["country"], "🏳")
        plat_label = PLATFORM_LABEL.get(R["platform"], R["platform"])
        lines.append(f"## {idx}. {R['name']}  ·  {plat_label}")
        lines.append("")
        lines.append(f"**主市场**: {flag} {R['country']} (`{R['locale']}`)  ·  近 30 天下载 **{R['downloads_30d']:,}**")
        if not R["is_localized"]:
            lines.append("")
            lines.append(f"> ⚠️ 该 App 缺少 **{R['country']}** 对应语言族本地化，这是一个 ASO 空白机会")
        lines.append("")
        lines.append(f"- 标题: `{R['title'] or '—'}`")
        lines.append(f"- 副标题: `{R['subtitle'] or '—'}`")
        lines.append(f"- 关键词: `{R['keywords_raw'] or '—'}`")
        lines.append("")

        # Build sortable rows. Primary key: popularity desc; tiebreak: rank asc.
        rows: list[tuple[tuple[int, int], dict[str, Any]]] = []
        for kw, slot in R["universe"].items():
            pop = slot.get("popularity") or 0
            rank = slot["rank"] if slot["rank"] is not None else 999
            rows.append(((-pop, rank), {"kw": kw, **slot}))
        rows.sort(key=lambda x: x[0])

        # Render rows with signal: popularity ≥ 5 OR ranked ≤ 100 OR in metadata
        def _has_signal(r: dict[str, Any]) -> bool:
            return (
                (r.get("popularity") or 0) >= 5
                or (r["rank"] is not None and r["rank"] <= 100)
                or bool(r["sources"] & {"T", "S", "K"})
            )

        filtered_rows = [r for _, r in rows if _has_signal(r)]

        lines.append("### 关键词集合分析（按热度降序）")
        lines.append("")
        lines.append("| 关键词 | 来源 | 热度 | 难度 | 竞品数 | 我的排名 | 判断 |")
        lines.append("|---|:-:|:-:|:-:|:-:|:-:|---|")
        for row in filtered_rows[:40]:
            kw = row["kw"]
            srcs = "".join(sorted(row["sources"]))
            pop = row.get("popularity")
            diff = row.get("difficulty")
            apps_count = row.get("apps_count")
            pop_str = (f"**{pop}** 🔥" if pop and pop >= 50 else (f"**{pop}**" if pop and pop >= 20 else (str(pop) if pop is not None else "—")))
            if diff is None:
                diff_str = "—"
            elif diff >= 70:
                diff_str = f"{diff} 🔴"
            elif diff >= 50:
                diff_str = f"{diff} 🟡"
            else:
                diff_str = f"{diff} 🟢"
            comp_str = str(apps_count) if apps_count is not None else "—"
            rank = row["rank"]
            if rank is None:
                rank_str = ">200"
            elif rank <= 20:
                rank_str = f"**#{rank}**"
            else:
                rank_str = f"#{rank}"
            emoji, label = _classify(row)
            kw_disp = kw.replace("|", "\\|")
            lines.append(f"| `{kw_disp}` | {srcs} | {pop_str} | {diff_str} | {comp_str} | {rank_str} | {emoji} {label} |")
        lines.append("")

        # Concrete optimization recipe
        keep, add, drop, fix, aspire = [], [], [], [], []
        for _, row in rows:
            emoji, _ = _classify(row)
            if emoji in ("✅", "🔥"):
                keep.append(row["kw"])
            elif emoji == "➕":
                add.append(row["kw"])
            elif emoji == "❌":
                drop.append(row["kw"])
            elif emoji == "🔁":
                fix.append(row["kw"])
            elif emoji == "🎯":
                aspire.append(row["kw"])
        lines.append("### 优化清单")
        lines.append("")
        lines.append(f"- 🔥/✅ **保留（核心）** ({len(keep)}): " + (", ".join(f"`{k}`" for k in keep) or "—"))
        lines.append(f"- ➕ **新增** ({len(add)}): " + (", ".join(f"`{k}`" for k in add) or "—"))
        lines.append(f"- 🎯 **冲刺（高热度、暂无排名）** ({len(aspire)}): " + (", ".join(f"`{k}`" for k in aspire) or "—"))
        lines.append(f"- 🔁 **文案需要调整** ({len(fix)}): " + (", ".join(f"`{k}`" for k in fix) or "—"))
        lines.append(f"- ❌ **删除** ({len(drop)}): " + (", ".join(f"`{k}`" for k in drop) or "—"))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
def main() -> int:
    apps, data_today = top_3_by_30d_downloads()
    if not apps:
        print("No apps found.", file=sys.stderr)
        return 1
    reports = json.loads(SALES_CACHE.read_text())
    rank_cache = load_rank_cache()
    hints_cache = load_hints_cache()

    print(f"Top-3 apps · data anchored to {data_today}")
    for i, a in enumerate(apps, 1):
        print(f"  {i}. {a['core'].get('name')}")
    print()

    results = []
    for app in apps:
        print(f"\n=== Analyzing: {app['core'].get('name')} ===")
        r = analyze_app(app, reports, data_today, rank_cache, hints_cache)
        if r:
            results.append(r)
        save_rank_cache(rank_cache)
        save_hints_cache(hints_cache)

    md = render(results, data_today)
    OUT.write_text(md)
    print(f"\n[saved] {OUT}")
    print()
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
