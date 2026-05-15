"""Sales & downloads dashboard for all live apps.

Time dimensions (in display order):
  1. 综合 / Consolidated   — aggregate totals across all apps for every dimension below
  2. 昨天     yesterday     vs day-before
  3. 前7天    last 7 days   vs prior 7 days
  4. 前30天   last 30 days  vs prior 30 days
  5. 本周     this week (Mon→today)         vs same days of last week
  6. 本月     this month (1st → today)      vs same range of last month

Then per-app rows, sorted by 30-day download count desc.

Downloads = sum of Units where ProductTypeIdentifier indicates an app install
            (not an update '7*' and not an IAP/sub 'IA*').
Revenue  = sum of Units × Developer Proceeds, converted to USD via static FX.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import appmate_config
from asc_client import sales_report

CACHE_PATH = appmate_config.data_path("sales_cache.json")

# Today is treated as "now". Apple's daily reports usually lag by 1–2 days.
TODAY = dt.date.today()  # 2026-05-12 per session context
# "yesterday" is auto-shifted to the most recent date that actually has data
# (Apple's daily report lag is 1–2 days). Set by main() once cache is loaded.
DATA_TODAY: dt.date = TODAY - dt.timedelta(days=1)

# Coarse FX → USD. Good enough for cross-app ranking; not accounting-grade.
FX_TO_USD: dict[str, float] = {
    "USD": 1.00, "EUR": 1.08, "GBP": 1.26, "JPY": 0.0065, "CNY": 0.138,
    "AUD": 0.66, "CAD": 0.74, "CHF": 1.13, "HKD": 0.128, "TWD": 0.031,
    "KRW": 0.00073, "INR": 0.012, "BRL": 0.20, "MXN": 0.058, "RUB": 0.011,
    "SGD": 0.74, "THB": 0.028, "MYR": 0.21, "IDR": 0.000062, "PHP": 0.018,
    "VND": 0.000041, "TRY": 0.030, "ILS": 0.27, "AED": 0.27, "SAR": 0.27,
    "ZAR": 0.054, "PLN": 0.25, "SEK": 0.094, "NOK": 0.092, "DKK": 0.145,
    "NZD": 0.61, "CZK": 0.043, "HUF": 0.0028, "RON": 0.22, "BGN": 0.55,
    "CLP": 0.00104, "COP": 0.00025, "ARS": 0.0011, "PEN": 0.27, "EGP": 0.020,
    "PKR": 0.0036, "NGN": 0.00062, "KZT": 0.0019, "UAH": 0.024,
}


def to_usd(amount: float, currency: str) -> float:
    rate = FX_TO_USD.get(currency)
    if rate is None:
        return 0.0
    return amount * rate


def is_download_ptid(ptid: str) -> bool:
    """Product type identifiers that count as an app install/download.
    Excludes updates ('7*') and IAPs/subs ('IA*')."""
    if not ptid:
        return False
    if ptid.startswith("IA") or ptid.startswith("ITA"):
        return False
    if ptid.startswith("7"):
        return False
    return True


def is_iap_ptid(ptid: str) -> bool:
    return ptid.startswith("IA")


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------
def needed_dates() -> list[dt.date]:
    """Union of all dates we'll need to satisfy every dimension's current+previous range."""
    yesterday = TODAY - dt.timedelta(days=1)
    # ~65 day window covers last_30d + its prior 30d, with margin for data-lag shift.
    start = yesterday - dt.timedelta(days=64)
    out: list[dt.date] = []
    d = start
    while d <= yesterday:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def load_cache() -> dict[str, list[dict[str, str]]]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict[str, list[dict[str, str]]]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False))


def fetch_daily(date: dt.date) -> tuple[str, list[dict[str, str]]]:
    iso = date.isoformat()
    try:
        rows = sales_report(iso, frequency="DAILY")
        return iso, rows
    except Exception as e:
        return iso, [{"_error": f"{type(e).__name__}: {e}"}]


def fetch_all(dates: list[dt.date], workers: int = 6) -> dict[str, list[dict[str, str]]]:
    cache = load_cache()
    today_iso = TODAY.isoformat()
    # Retry recent (last 3 days) empty-cached entries — Apple may have published since.
    recent_cutoff = TODAY - dt.timedelta(days=3)
    stale_empty = [
        d for d in dates
        if d >= recent_cutoff
        and isinstance(cache.get(d.isoformat()), list)
        and len(cache[d.isoformat()]) == 0
    ]
    for d in stale_empty:
        cache.pop(d.isoformat(), None)
    if stale_empty:
        print(f"Retrying {len(stale_empty)} recent empty-cached dates: {[d.isoformat() for d in stale_empty]}")
    pending = [d for d in dates if d.isoformat() not in cache]

    if pending:
        print(f"Fetching {len(pending)} daily reports (caching {len(cache)} from prior runs)…")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_daily, d): d for d in pending}
            for i, fut in enumerate(as_completed(futures), 1):
                iso, rows = fut.result()
                cache[iso] = rows
                err = next((r.get("_error") for r in rows if "_error" in r), None) if rows else None
                tag = f"ERR {err}" if err else f"{len(rows)} rows"
                print(f"  [{i:>2}/{len(pending)}] {iso}  {tag}")
        save_cache(cache)
    else:
        print(f"All {len(dates)} dates cached.")

    # Return only the requested dates
    return {d.isoformat(): cache[d.isoformat()] for d in dates}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def build_parent_lookup() -> dict[str, str]:
    """Map { sku|app_id -> app name }. In sales reports, IAP rows' `Parent Identifier`
    is the parent app's SKU, not its Apple ID — but we index both for safety."""
    path = appmate_config.data_path("apps_full.json")
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    lookup: dict[str, str] = {}
    for a in payload["apps"]:
        core = a.get("core") or {}
        name = core.get("name")
        if not name:
            continue
        if a.get("id"):
            lookup[a["id"]] = name
        if core.get("sku"):
            lookup[core["sku"]] = name
    return lookup


def aggregate_by_day(reports: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, dict[str, float]]]:
    """Returns: { iso_date: { app_name: { 'downloads': N, 'iap_units': N, 'revenue_usd': X } } }.

    IAP rows are linked back to their parent app via the `Parent Identifier` column
    (Apple App Store ID). Title on IAP rows is the IAP product reference name, not
    the parent app name.
    """
    parent_lookup = build_parent_lookup()
    out: dict[str, dict[str, dict[str, float]]] = {}
    for iso, rows in reports.items():
        per_app: dict[str, dict[str, float]] = defaultdict(
            lambda: {"downloads": 0.0, "iap_units": 0.0, "revenue_usd": 0.0, "iap_revenue_usd": 0.0}
        )
        for r in rows:
            if "_error" in r:
                continue
            ptid = r.get("Product Type Identifier") or ""
            try:
                units = int(r.get("Units") or 0)
            except ValueError:
                units = 0
            try:
                proceeds_per = float(r.get("Developer Proceeds") or 0)
            except ValueError:
                proceeds_per = 0.0
            currency = r.get("Currency of Proceeds") or ""
            row_rev_usd = to_usd(units * proceeds_per, currency)

            # Resolve which app this row belongs to
            if is_iap_ptid(ptid):
                # IAP: Title = IAP product name; Parent Identifier = parent app's App Store ID
                parent_id = r.get("Parent Identifier") or r.get("Apple Identifier") or ""
                app_name = parent_lookup.get(parent_id) or r.get("Title") or "?"
            else:
                app_name = r.get("Title") or r.get("SKU") or "?"

            slot = per_app[app_name]
            if is_download_ptid(ptid):
                slot["downloads"] += units
                slot["revenue_usd"] += row_rev_usd  # paid-app download revenue
            elif is_iap_ptid(ptid):
                slot["iap_units"] += units
                slot["revenue_usd"] += row_rev_usd
                slot["iap_revenue_usd"] += row_rev_usd
        out[iso] = dict(per_app)
    return out


def sum_range(by_day: dict[str, dict[str, dict[str, float]]], start: dt.date, end: dt.date) -> dict[str, dict[str, float]]:
    """Inclusive sum of metrics from start..end."""
    acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"downloads": 0.0, "iap_units": 0.0, "revenue_usd": 0.0, "iap_revenue_usd": 0.0}
    )
    d = start
    while d <= end:
        for app, m in by_day.get(d.isoformat(), {}).items():
            for k in ("downloads", "iap_units", "revenue_usd", "iap_revenue_usd"):
                acc[app][k] += m.get(k, 0.0)
        d += dt.timedelta(days=1)
    return dict(acc)


def pct_change(current: float, previous: float) -> str:
    if previous == 0 and current == 0:
        return "  —  "
    if previous == 0:
        return "  ∞↑ "
    delta = (current - previous) / previous * 100
    arrow = "↑" if delta >= 0 else "↓"
    return f"{arrow}{abs(delta):5.1f}%"


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def build_dimensions(by_day: dict[str, dict[str, dict[str, float]]]) -> list[dict[str, Any]]:
    # Anchor "yesterday" to the most recent day that has any data — Apple's daily
    # report often lags 1–2 days. DATA_TODAY is set by main() before this runs.
    yesterday = DATA_TODAY
    day_before = DATA_TODAY - dt.timedelta(days=1)
    last7_start = yesterday - dt.timedelta(days=6)        # inclusive 7-day window
    last7_prev_end = last7_start - dt.timedelta(days=1)
    last7_prev_start = last7_prev_end - dt.timedelta(days=6)
    last30_start = yesterday - dt.timedelta(days=29)
    last30_prev_end = last30_start - dt.timedelta(days=1)
    last30_prev_start = last30_prev_end - dt.timedelta(days=29)

    # This week: Monday = weekday 0. If yesterday < this_mon (data lag past weekend),
    # we end up with empty current range and 0 totals — sum_range handles start>end safely.
    weekday = TODAY.weekday()
    this_mon = TODAY - dt.timedelta(days=weekday)
    this_week_end = yesterday
    last_week_mon = this_mon - dt.timedelta(days=7)
    # Match the same number of days as the current period (could be negative => empty)
    span = (this_week_end - this_mon).days
    last_week_end = last_week_mon + dt.timedelta(days=max(span, -1))

    # This month: 1st of month → most recent day with data.
    # Previous period = entire previous calendar month (not same-day-range).
    this_month_start = TODAY.replace(day=1)
    this_month_end = yesterday
    prev_month_last_day = this_month_start - dt.timedelta(days=1)
    last_month_start = prev_month_last_day.replace(day=1)
    last_month_end = prev_month_last_day

    dims = [
        {
            "label": "昨天 / Yesterday",
            "current": (yesterday, yesterday),
            "previous": (day_before, day_before),
        },
        {
            "label": "前7天 / Last 7 days",
            "current": (last7_start, yesterday),
            "previous": (last7_prev_start, last7_prev_end),
        },
        {
            "label": "前30天 / Last 30 days",
            "current": (last30_start, yesterday),
            "previous": (last30_prev_start, last30_prev_end),
        },
        {
            "label": "本周 / This week",
            "current": (this_mon, this_week_end),
            "previous": (last_week_mon, last_week_end),
        },
        {
            "label": "本月 / This month",
            "current": (this_month_start, this_month_end),
            "previous": (last_month_start, last_month_end),
        },
    ]

    for d in dims:
        d["current_data"] = sum_range(by_day, *d["current"])
        d["previous_data"] = sum_range(by_day, *d["previous"])
    return dims


# ---------------------------------------------------------------------------
# Live apps filter
# ---------------------------------------------------------------------------
def load_live_apps() -> set[str]:
    """Use apps_full.json to identify live apps (any version READY_FOR_SALE)."""
    path = appmate_config.data_path("apps_full.json")
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    live: set[str] = set()
    for a in payload["apps"]:
        info_state = (a.get("appInfo") or {}).get("attributes", {}).get("appStoreState")
        any_live = any(
            v.get("attributes", {}).get("appStoreState") == "READY_FOR_SALE"
            for v in (a.get("versions") or [])
            if isinstance(v, dict)
        )
        if info_state == "READY_FOR_SALE" or any_live:
            name = (a.get("core") or {}).get("name")
            if name:
                live.add(name)
    return live


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def fmt_int(n: float) -> str:
    return f"{int(round(n)):,}"


def fmt_usd(x: float) -> str:
    if x == 0:
        return "$0"
    if abs(x) >= 1000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def pct_change_md(current: float, previous: float) -> str:
    """Plain-text Δ for markdown output. No leading spaces."""
    if previous == 0 and current == 0:
        return "—"
    if previous == 0:
        return "∞ ↑"
    delta = (current - previous) / previous * 100
    arrow = "↑" if delta >= 0 else "↓"
    return f"{arrow} {abs(delta):.1f}%"


def _range_label(d: dict[str, Any]) -> str:
    start, end = d["current"]
    if start > end:
        return "(数据未到)"
    if start == end:
        return f"{start:%Y-%m-%d}"
    return f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"


def _prev_range_label(d: dict[str, Any]) -> str:
    start, end = d["previous"]
    if start > end:
        return "(N/A)"
    if start == end:
        return f"{start:%Y-%m-%d}"
    return f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"


def load_icon_map() -> dict[str, str]:
    """Map { app_name -> icon URL } using app_icons.json + apps_full.json."""
    icons_path = appmate_config.data_path("app_icons.json")
    apps_path = appmate_config.data_path("apps_full.json")
    if not icons_path.exists() or not apps_path.exists():
        return {}
    icons = json.loads(icons_path.read_text())
    apps = json.loads(apps_path.read_text())["apps"]
    out: dict[str, str] = {}
    for a in apps:
        aid = a["id"]
        name = (a.get("core") or {}).get("name")
        if not name:
            continue
        rec = icons.get(aid) or {}
        url = rec.get("artworkUrl60") or rec.get("artworkUrl100")
        if url:
            out[name] = url
    return out


def name_with_icon(name: str, icons: dict[str, str], size: int = 20) -> str:
    url = icons.get(name)
    if not url:
        return name
    return f'<img src="{url}" width="{size}" height="{size}" align="absmiddle"/> {name}'


DIM_LABELS_CN = {
    "昨天 / Yesterday": "昨天",
    "前7天 / Last 7 days": "前 7 天",
    "前30天 / Last 30 days": "前 30 天",
    "本周 / This week": "本周",
    "本月 / This month": "本月",
}


def _short_range(d: tuple[dt.date, dt.date]) -> str:
    start, end = d
    if start > end:
        return "—"
    if start == end:
        return f"{start:%Y-%m-%d}"
    return f"{start:%Y-%m-%d} → {end:%Y-%m-%d}"


def _short_range_compact(d: tuple[dt.date, dt.date]) -> str:
    """Like 05-10 or 05-04~05-10. Empty range → 暂无."""
    start, end = d
    if start > end:
        return "暂无"
    if start == end:
        return f"{start:%m-%d}"
    return f"{start:%m-%d}~{end:%m-%d}"


def _top_n(
    cur: dict[str, dict[str, float]],
    prev: dict[str, dict[str, float]],
    live: set[str],
    metric: str,
    n: int = 3,
) -> list[tuple[str, float, float]]:
    """Top-N apps by `metric` in `cur`, restricted to live apps, with prev value attached.
    Apps with zero current value are excluded."""
    rows: list[tuple[str, float, float]] = []
    for name, m in cur.items():
        if name not in live:
            continue
        c = m.get(metric, 0.0)
        if c <= 0:
            continue
        p = (prev.get(name) or {}).get(metric, 0.0)
        rows.append((name, c, p))
    rows.sort(key=lambda r: -r[1])
    return rows[:n]


def render(dims: list[dict[str, Any]], live_apps: set[str]) -> None:
    icons = load_icon_map()
    lines: list[str] = []

    # One-line top summary: yesterday + this-week + this-month revenue
    def _rev(dim_label_prefix: str) -> tuple[str, float]:
        d = next((x for x in dims if x["label"].startswith(dim_label_prefix)), None)
        if d is None:
            return "—", 0.0
        start, end = d["current"]
        rev = sum(m["revenue_usd"] for n, m in d["current_data"].items() if n in live_apps)
        if start > end:
            return "暂无", 0.0
        return fmt_usd(rev), rev

    yest_rev_str, _ = _rev("昨天")
    week_rev_str, _ = _rev("本周")
    month_rev_str, _ = _rev("本月")

    lines.append("# 📊 App Store 销售与下载日报")
    lines.append("")
    lines.append(
        f"**昨天({DATA_TODAY:%m-%d}) 收入 {yest_rev_str}** · "
        f"本周收入 {week_rev_str} · "
        f"本月收入 {month_rev_str}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🧮 总和")
    lines.append("")

    for d in dims:
        cur = d["current_data"]
        prev = d["previous_data"]
        cur_dl = sum(m["downloads"] for n, m in cur.items() if n in live_apps)
        prv_dl = sum(m["downloads"] for n, m in prev.items() if n in live_apps)
        cur_rev = sum(m["revenue_usd"] for n, m in cur.items() if n in live_apps)
        prv_rev = sum(m["revenue_usd"] for n, m in prev.items() if n in live_apps)
        cn_label = DIM_LABELS_CN.get(d["label"], d["label"])
        rng_short = _short_range_compact(d["current"])

        lines.append(f"### {cn_label}({rng_short})")
        lines.append("")
        start, end = d["current"]
        if start > end:
            lines.append("> ⏳ 数据尚未由 Apple 生成")
            lines.append("")
            continue

        # Revenue + top 3 apps
        lines.append(f"- 💰 营收: **{fmt_usd(cur_rev)}**  ·  {pct_change_md(cur_rev, prv_rev)}")
        top_rev = _top_n(cur, prev, live_apps, "revenue_usd", n=3)
        for rank_i, (name, c_val, p_val) in enumerate(top_rev, 1):
            share = (c_val / cur_rev * 100) if cur_rev else 0.0
            lines.append(
                f"    {rank_i}. **{fmt_usd(c_val)}** ({share:.1f}%)  ·  "
                f"{pct_change_md(c_val, p_val)}  ·  {name}"
            )

        # Downloads + top 3 apps
        lines.append(f"- 📥 下载: **{fmt_int(cur_dl)}**  ·  {pct_change_md(cur_dl, prv_dl)}")
        top_dl = _top_n(cur, prev, live_apps, "downloads", n=3)
        for rank_i, (name, c_val, p_val) in enumerate(top_dl, 1):
            share = (c_val / cur_dl * 100) if cur_dl else 0.0
            lines.append(
                f"    {rank_i}. **{fmt_int(c_val)}** ({share:.1f}%)  ·  "
                f"{pct_change_md(c_val, p_val)}  ·  {name}"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> ⓘ 营收为多币种按近似汇率折算为 USD（非财务对账数据）。Apple 日报延迟 1–2 天。")
    lines.append("> 本月对比的是上月**整月**；前 7/30 天对比的是再往前 7/30 天。")

    md = "\n".join(lines)
    print(md)
    out = appmate_config.data_path("report.md")
    out.write_text(md)
    print(f"\n[saved] {out}", file=sys.stderr)


# ---------------------------------------------------------------------------
def main() -> int:
    appmate_config.require_credentials_or_exit()
    global DATA_TODAY
    dates = needed_dates()
    print(f"Window: {dates[0].isoformat()} → {dates[-1].isoformat()} ({len(dates)} days)")
    reports = fetch_all(dates)

    # Retry any dates that errored on the previous fetch.
    bad = [d for d in dates if any("_error" in r for r in reports.get(d.isoformat(), []))]
    if bad:
        print(f"Retrying {len(bad)} dates that errored before…")
        cache = load_cache()
        for d in bad:
            iso, rows = fetch_daily(d)
            if rows and "_error" not in rows[0]:
                cache[iso] = rows
                reports[iso] = rows
                print(f"  retry ok: {iso}  {len(rows)} rows")
        save_cache(cache)

    # Auto-anchor DATA_TODAY to most recent date that has actual sales rows
    for d in sorted(dates, reverse=True):
        rows = reports.get(d.isoformat(), [])
        if rows and not any("_error" in r for r in rows):
            DATA_TODAY = d
            break
    print(f"Anchoring 'yesterday' to {DATA_TODAY.isoformat()} (most recent day with data)")

    by_day = aggregate_by_day(reports)
    dims = build_dimensions(by_day)
    live = load_live_apps()
    if not live:
        print("⚠ apps_full.json missing or contained no live apps — falling back to all titles in reports.")
        live = {name for day in by_day.values() for name in day.keys()}
    render(dims, live)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
