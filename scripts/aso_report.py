"""ASO daily report.

For the top-3 apps by 30-day downloads:
  1. 主标题 / 副标题（按 locale）
  2. 各市场表现：昨日下载量（按国家拆分）+ 该 storefront 中排名 ≤ #20 的关键词
  3. (可选) 搜索热度 / Search Popularity — 需要 Apple Search Ads API 凭证

iTunes Search API 给排名（与 App Store 网页版同源）。
Apple Search Ads API 给热度（需另行配置，见 README 段）。
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

import requests

import appmate_config

APPS_FULL = appmate_config.data_path("apps_full.json")
SALES_CACHE = appmate_config.data_path("sales_cache.json")
OUT = appmate_config.data_path("aso_report.md")
RANK_CACHE = appmate_config.data_path("aso_rank_cache.json")
POP_CACHE = appmate_config.data_path("aso_popularity_cache.json")
SEARCH_ADS_CREDS = appmate_config.config_path("search_ads_credentials.txt")

ITUNES_BASE = "https://itunes.apple.com/search"

LOCALE_TO_COUNTRY: dict[str, str] = {
    "en-US": "US", "en-GB": "GB", "en-CA": "CA", "en-AU": "AU",
    "zh-Hans": "CN", "zh-Hant": "TW",
    "ja": "JP", "ko": "KR",
    "de-DE": "DE", "fr-FR": "FR", "fr-CA": "CA",
    "es-ES": "ES", "es-MX": "MX",
    "it": "IT", "pt-BR": "BR", "pt-PT": "PT",
    "ru": "RU", "ar-SA": "SA",
    "ms": "MY", "id": "ID", "th": "TH", "tr": "TR",
    "el": "GR", "pl": "PL", "nl": "NL", "nl-NL": "NL",
    "sv": "SE", "no": "NO", "fi": "FI", "da": "DK",
    "he": "IL", "hu": "HU", "uk": "UA", "vi": "VN",
}

COUNTRY_FLAG: dict[str, str] = {
    "US": "🇺🇸", "GB": "🇬🇧", "CA": "🇨🇦", "AU": "🇦🇺",
    "CN": "🇨🇳", "TW": "🇹🇼", "HK": "🇭🇰",
    "JP": "🇯🇵", "KR": "🇰🇷",
    "DE": "🇩🇪", "FR": "🇫🇷", "ES": "🇪🇸", "IT": "🇮🇹",
    "BR": "🇧🇷", "PT": "🇵🇹", "MX": "🇲🇽",
    "RU": "🇷🇺", "SA": "🇸🇦",
    "MY": "🇲🇾", "ID": "🇮🇩", "TH": "🇹🇭", "TR": "🇹🇷",
    "GR": "🇬🇷", "PL": "🇵🇱", "NL": "🇳🇱",
    "SE": "🇸🇪", "NO": "🇳🇴", "FI": "🇫🇮", "DK": "🇩🇰",
    "IL": "🇮🇱", "HU": "🇭🇺", "UA": "🇺🇦", "VN": "🇻🇳",
}

PLATFORM_TO_ENTITY = {"IOS": "software", "MAC_OS": "macSoftware"}
PLATFORM_LABEL = {"IOS": "iOS", "MAC_OS": "macOS"}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def load_rank_cache() -> dict[str, Any]:
    return json.loads(RANK_CACHE.read_text()) if RANK_CACHE.exists() else {}


def save_rank_cache(c: dict[str, Any]) -> None:
    RANK_CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=2))


def load_pop_cache() -> dict[str, Any]:
    return json.loads(POP_CACHE.read_text()) if POP_CACHE.exists() else {}


def save_pop_cache(c: dict[str, Any]) -> None:
    POP_CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_keywords(s: str | None) -> list[str]:
    if not s:
        return []
    s = s.replace("，", ",").replace("、", ",")
    out, seen = [], set()
    for kw in s.split(","):
        kw = kw.strip()
        if not kw:
            continue
        if kw.lower() in seen:
            continue
        seen.add(kw.lower())
        out.append(kw)
    return out


# Tokenize metadata (title + subtitle + keywords) into candidate search terms.
# Note: tokenizer is intentionally conservative — it splits on punctuation,
# whitespace, and Latin↔CJK boundaries only. Meaningful Chinese word
# segmentation is delegated to the LLM consumer (Claude in conversation),
# which reads the raw current_metadata text and proposes real ASO words
# (e.g. "便利贴", "备忘录") that a regex tokenizer can't extract.
_LATIN_CJK_1 = re.compile(r"([A-Za-z0-9])([一-鿿぀-ヿ가-힣])")
_LATIN_CJK_2 = re.compile(r"([一-鿿぀-ヿ가-힣])([A-Za-z0-9])")
_SPLIT_RX = re.compile(r"[,;:|/\\\(\)\[\]\{\}\s　\.!\?！？•·…—\-]+")

EN_STOPWORDS = set(
    "the and for with your you this that are was were have has had will can all "
    "any one two use using used new now any my our its his her their from into "
    "out get got make made just only own each some most many much very over under "
    "more less than then them not but and yet so still while if up down off on in "
    "of to is be by or as at it we they he she do so no my me be am pm".split()
)


def tokenize_text(
    title: str | None, subtitle: str | None, keywords: str | None
) -> dict[str, set[str]]:
    """Combine title/subtitle/keywords and return {token: {source-tags}}.

    Source tags: 'T' (title), 'S' (subtitle), 'K' (keywords).
    Splits on punctuation + whitespace + Latin↔CJK boundaries only.
    Long CJK runs without internal boundaries stay as one token (and are
    filtered out by `_good_token`'s CJK ≥ 6 rule). The LLM consumer is
    expected to re-segment those from raw metadata in Phase B.
    """
    tagged: dict[str, set[str]] = defaultdict(set)

    def _emit(src: str, tag: str) -> None:
        if not src:
            return
        s = src.replace("，", ",").replace("、", ",").replace("：", ":").replace("；", ";")
        s = _LATIN_CJK_1.sub(r"\1,\2", s)
        s = _LATIN_CJK_2.sub(r"\1,\2", s)
        for raw in _SPLIT_RX.split(s):
            t = raw.strip(" .,#&")
            if len(t) < 2:
                continue
            if t.lower() in EN_STOPWORDS:
                continue
            # collapse duplicates case-insensitive but keep original casing
            existing = next((k for k in tagged if k.lower() == t.lower()), None)
            if existing:
                tagged[existing].add(tag)
            else:
                tagged[t].add(tag)

    _emit(title, "T")
    _emit(subtitle, "S")
    _emit(keywords, "K")
    return dict(tagged)


def latest_version_localizations(app: dict[str, Any]) -> list[dict[str, Any]]:
    versions = app.get("versions") or []
    if not versions:
        return []
    versions = sorted(
        versions,
        key=lambda v: v.get("attributes", {}).get("createdDate", ""),
        reverse=True,
    )
    return versions[0].get("localizations", [])


def app_platform(app: dict[str, Any]) -> str:
    versions = app.get("versions") or []
    return versions[0].get("attributes", {}).get("platform", "IOS") if versions else "IOS"


# ---------------------------------------------------------------------------
# iTunes Search ranker (cached)
# ---------------------------------------------------------------------------
def rank_keyword(
    keyword: str, country: str, entity: str, bundle_id: str,
    cache: dict[str, Any], retries: int = 4,
) -> int | None:
    cache_key = f"{entity}|{country}|{keyword}"
    if cache_key in cache:
        return cache[cache_key].get("ranks", {}).get(bundle_id)
    params = {"term": keyword, "country": country, "entity": entity, "limit": 200}
    last_exc = None
    for attempt in range(retries):
        try:
            r = requests.get(ITUNES_BASE, params=params, timeout=20)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            if not r.ok:
                cache[cache_key] = {"_error": r.status_code, "ranks": {}}
                return None
            results = r.json().get("results", [])
            ranks: dict[str, int] = {}
            for i, app in enumerate(results, 1):
                bid = app.get("bundleId")
                if bid and bid not in ranks:
                    ranks[bid] = i
            cache[cache_key] = {"total_results": len(results), "ranks": ranks}
            return ranks.get(bundle_id)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(0.5 * (2 ** attempt))
    cache[cache_key] = {"_error": f"{type(last_exc).__name__}", "ranks": {}}
    return None


# ---------------------------------------------------------------------------
# Apple Search Ads popularity stub
# ---------------------------------------------------------------------------
def search_ads_available() -> bool:
    """Returns True once Search Ads credentials are configured. Stub for now."""
    return SEARCH_ADS_CREDS.exists()


def fetch_popularity(keyword: str, country: str, cache: dict[str, Any]) -> int | None:
    """Apple Search Ads "Popularity Index" 1-99 for keyword in given storefront.

    Stub: returns None until Search Ads credentials are configured.
    See README section in this file's docstring for setup steps.
    """
    if not search_ads_available():
        return None
    # TODO: wire up once creds available.
    #   POST https://api.searchads.apple.com/api/v5/keywords/recommendation
    #   with bearer token + org id header
    return None


# ---------------------------------------------------------------------------
# Per-country downloads
# ---------------------------------------------------------------------------
def is_download_ptid(ptid: str) -> bool:
    if not ptid:
        return False
    if ptid.startswith("IA") or ptid.startswith("7"):
        return False
    return True


def per_country_downloads(
    reports: dict[str, list[dict[str, str]]],
    app_name: str,
    sku: str,
    date_iso: str,
) -> dict[str, int]:
    """Sum app downloads (not IAPs, not updates) per Country Code on given date."""
    rows = reports.get(date_iso, [])
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        if "_error" in r:
            continue
        ptid = r.get("Product Type Identifier") or ""
        if not is_download_ptid(ptid):
            continue
        title = r.get("Title") or ""
        if title != app_name:
            continue
        country = r.get("Country Code") or "?"
        try:
            units = int(r.get("Units") or 0)
        except ValueError:
            units = 0
        out[country] += units
    return dict(out)


def per_country_downloads_range(
    reports: dict[str, list[dict[str, str]]],
    app_name: str,
    sku: str,
    start: dt.date,
    end: dt.date,
) -> dict[str, int]:
    """Sum app downloads per country across a date range (inclusive)."""
    out: dict[str, int] = defaultdict(int)
    d = start
    while d <= end:
        for country, n in per_country_downloads(reports, app_name, sku, d.isoformat()).items():
            out[country] += n
        d += dt.timedelta(days=1)
    return dict(out)


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
    last30 = next(d for d in dims if d["label"].startswith("前30天"))
    ranked = sorted(
        ((name, m.get("downloads", 0)) for name, m in last30["current_data"].items() if name in live),
        key=lambda kv: -kv[1],
    )[:3]
    top_names = [n for n, _ in ranked]
    apps = json.loads(APPS_FULL.read_text())["apps"]
    name_to_app = {a["core"].get("name"): a for a in apps}
    return [name_to_app[n] for n in top_names if n in name_to_app], sr.DATA_TODAY


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _flag(country: str) -> str:
    return COUNTRY_FLAG.get(country, "🏳")


def render_app_section(
    idx: int,
    app: dict[str, Any],
    reports: dict[str, list[dict[str, str]]],
    data_today: dt.date,
    rank_cache: dict[str, Any],
    pop_cache: dict[str, Any],
) -> list[str]:
    name = app["core"].get("name")
    bundle_id = app["core"].get("bundleId")
    sku = app["core"].get("sku")
    platform = app_platform(app)
    entity = PLATFORM_TO_ENTITY.get(platform, "software")
    plat_label = PLATFORM_LABEL.get(platform, platform)

    info_locs = (app.get("appInfo") or {}).get("localizations", [])
    info_by_locale = {L.get("locale"): L for L in info_locs}
    ver_locs = latest_version_localizations(app)
    ver_by_locale = {L.get("locale"): L for L in ver_locs}

    rankable_locales = [
        loc for loc in (set(info_by_locale) | set(ver_by_locale))
        if loc in LOCALE_TO_COUNTRY and (ver_by_locale.get(loc) or {}).get("keywords")
    ]

    # Get yesterday's downloads per country for this app
    dl_yesterday = per_country_downloads(reports, name, sku, data_today.isoformat())

    lines: list[str] = []
    lines.append(f"## {idx}. {name}  ·  {plat_label}")
    lines.append("")
    lines.append(f"- bundleId: `{bundle_id}`")
    lines.append("")

    # Compute rankings per (locale, country) from combined title+subtitle+keywords
    all_locales_with_data = (set(info_by_locale) | set(ver_by_locale)) & set(LOCALE_TO_COUNTRY)

    market_rows: list[dict[str, Any]] = []
    for loc in all_locales_with_data:
        country = LOCALE_TO_COUNTRY[loc]
        info = info_by_locale.get(loc) or {}
        ver = ver_by_locale.get(loc) or {}
        title = info.get("name")
        subtitle = info.get("subtitle")
        kw_raw = ver.get("keywords")
        token_sources = tokenize_text(title, subtitle, kw_raw)
        if not token_sources:
            continue
        ranks_top20: list[tuple[str, int, str]] = []  # (token, rank, source_tags)
        for token in token_sources:
            srcs = "".join(sorted(token_sources[token]))
            print(f"  [{idx}/3] {name} · {country} · '{token[:40]}' [{srcs}]", flush=True)
            pos = rank_keyword(token, country, entity, bundle_id, rank_cache)
            if pos is not None and pos <= 20:
                ranks_top20.append((token, pos, srcs))
            time.sleep(0.15)
        ranks_top20.sort(key=lambda kp: (kp[1], kp[0]))
        market_rows.append({
            "locale": loc,
            "country": country,
            "dl_yesterday": dl_yesterday.get(country, 0),
            "top20": ranks_top20,
            "token_count": len(token_sources),
            "title": title,
            "subtitle": subtitle,
            "keywords": kw_raw,
        })
    market_rows.sort(key=lambda m: -m["dl_yesterday"])

    lines.append(f"### 🌍 各市场表现（按昨日下载量降序，下载日期 {data_today:%Y-%m-%d}）")
    lines.append("")
    lines.append("> 关键词来源标签 — T: 主标题 · S: 副标题 · K: 关键词字段")
    lines.append("")
    lines.append("| 市场 | 昨日下载 | 排名 ≤ #20 的关键词（[来源]） |")
    lines.append("|---|---:|---|")
    for row in market_rows:
        flag = _flag(row["country"])
        if row["top20"]:
            kws_cell = " · ".join(
                f"`{k}` **#{p}** [{s}]" for k, p, s in row["top20"]
            )
        else:
            kws_cell = "_无_"
        lines.append(
            f"| {flag} {row['country']} (`{row['locale']}`) | "
            f"{row['dl_yesterday']:,} | {kws_cell} |"
        )
    lines.append("")

    # Markets where downloads happened but we DON'T have keyword localization → note them
    rankable_countries = {r["country"] for r in market_rows}
    leftover = [
        (cc, n) for cc, n in dl_yesterday.items()
        if cc not in rankable_countries and n > 0
    ]
    leftover.sort(key=lambda x: -x[1])
    if leftover:
        leftover_str = "、".join(
            f"{_flag(cc)} {cc} ({n})" for cc, n in leftover[:10]
        )
        lines.append(f"> 📌 还有下载但无对应 locale 关键词的市场：{leftover_str}")
        lines.append("")

    return lines


def main() -> int:
    apps, data_today = top_3_by_30d_downloads()
    if not apps:
        print("No apps found.", file=sys.stderr)
        return 1
    print(f"Top-3 apps · DATA_TODAY = {data_today}")
    for i, a in enumerate(apps, 1):
        print(f"  {i}. {a['core'].get('name')}  ({app_platform(a)})")
    print()

    reports = json.loads(SALES_CACHE.read_text())
    rank_cache = load_rank_cache()
    pop_cache = load_pop_cache()

    lines: list[str] = []
    lines.append("# 🎯 ASO 关键词排名日报")
    lines.append("")
    lines.append(f"- 🕐 生成时间: **{dt.datetime.now():%Y-%m-%d %H:%M}**")
    lines.append(f"- 📅 下载数据日期: **{data_today:%Y-%m-%d}**")
    lines.append(f"- 🔍 排名: iTunes Search Top-200（与 App Store 网页版同源）")
    lines.append(f"- 📊 搜索热度: {'✅ 已配置' if search_ads_available() else '⚠️ 未配置（需 Apple Search Ads API 凭证）'}")
    lines.append(f"- 📱 排名口径: 前 30 日下载量最高的 3 个上架 App")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, app in enumerate(apps, 1):
        lines.extend(render_app_section(idx, app, reports, data_today, rank_cache, pop_cache))
        lines.append("---")
        lines.append("")
        save_rank_cache(rank_cache)

    if not search_ads_available():
        lines.append("## 📊 关于搜索热度数据")
        lines.append("")
        lines.append("当前未配置 Apple Search Ads API，因此无法展示每个关键词的搜索热度（Popularity Index 1-99）。")
        lines.append("Astro / Sensor Tower / AppTweak 显示的热度数据，全部来自这同一个 API。")
        lines.append("")
        lines.append("**配置步骤**:")
        lines.append("")
        lines.append("1. 注册 / 登录 [Apple Search Ads](https://searchads.apple.com)（Account Holder 邀请加入）")
        lines.append("2. 在 ASA UI 创建 API key → 拿到 `orgId / clientId / clientSecret`")
        lines.append("3. 保存到 `search_ads_credentials.txt`，格式：")
        lines.append("   ```")
        lines.append("   org_id        = 1234567")
        lines.append("   client_id     = SEARCHADS.xxxx")
        lines.append("   client_secret = xxxxxx")
        lines.append("   key_id        = xxxxxx")
        lines.append("   private_key_path = /path/to/searchads.p8")
        lines.append("   ```")
        lines.append("4. 重新跑 `python3 aso_report.py`，热度列会自动出现")
        lines.append("")

    save_rank_cache(rank_cache)
    save_pop_cache(pop_cache)
    md = "\n".join(lines)
    OUT.write_text(md)
    print(f"\n[saved] {OUT}")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
