from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r"C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\feishu-long-term-sync\data\latest.xlsx")
OUT = ROOT / "xinshiji.html"
STANDALONE_OUT = ROOT / "xinshiji-offline.html"
ECHARTS_JS = ROOT / "echarts.min.js"

START = pd.Timestamp("2026-07-27")
BASELINE_START = START - pd.Timedelta(days=7)
BASELINE_END = START - pd.Timedelta(days=1)
POST_WEEK_END = START + pd.Timedelta(days=6)

PRODUCTS = [
    {"id": "cheese", "barcode": 6973029302261, "short": "厚厚奶酪", "color": "#16a34a"},
    {"id": "coconut", "barcode": 6973029303688, "short": "生椰奶酪", "color": "#d97706"},
    {"id": "jasmine", "barcode": 6973029303671, "short": "七窨茉莉", "color": "#2563eb"},
    {"id": "chocolate", "barcode": 6973029307198, "short": "浓浓巧克力", "color": "#0f766e"},
]
TIER_ORDER = ["0-1", "1-2", "2-5", "5+"]
NAV_ITEMS = [
    ("index.html", "大润发 70g 价格测试", "drf"),
    ("yonghui.html", "永辉 112g 促销分析", "yonghui"),
    ("xinshiji.html", "新世纪 70g 价格弹性", "xinshiji"),
]


def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def round_or_none(value, digits=2):
    if value is None or pd.isna(value):
        return None
    value = float(value)
    if math.isinf(value) or math.isnan(value):
        return None
    return round(value, digits)


def week_label(start: pd.Timestamp) -> str:
    end = start + pd.Timedelta(days=6)
    return f"{start.month}/{start.day}-{end.month}/{end.day}"


def tier_label(value: float) -> str:
    if value <= 0:
        return "0"
    if value < 1:
        return "0-1"
    if value < 2:
        return "1-2"
    if value < 5:
        return "2-5"
    return "5+"


def month_week_start(month: int, week: int) -> pd.Timestamp:
    first = pd.Timestamp(2026, month, 1)
    return first - pd.Timedelta(days=first.weekday()) + pd.Timedelta(weeks=week - 1)


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[int, str]]:
    df = pd.read_excel(SOURCE, sheet_name=0)
    df.columns = [str(c).strip() for c in df.columns]
    df["条码"] = pd.to_numeric(df["条码"], errors="coerce").fillna(0).astype("int64")
    df = df[df["条码"].isin([p["barcode"] for p in PRODUCTS])].copy()
    for col in ["销售数量", "销售成本", "销售收入"]:
        df[col] = clean_num(df[col])
    df["销售日期"] = pd.to_datetime(df["销售日期"], errors="coerce").dt.normalize()
    df["仓位编码"] = df["仓位编码"].fillna("").astype(str).str.strip()

    product_names = {
        int(row["条码"]): str(row["商品名称"]).replace("70g70g", "70g").strip()
        for _, row in df[["条码", "商品名称"]].drop_duplicates().iterrows()
    }
    for product in PRODUCTS:
        product["name"] = product_names.get(product["barcode"], product["short"])

    month_col = df.columns[1]
    week_col = df.columns[2]
    days_col = df.columns[3]
    date_col = df.columns[4]
    df["_month"] = df[month_col].astype(str).str.extract(r"(\d+)").astype(int)
    df["_week"] = df[week_col].astype(str).str.extract(r"(\d+)").astype(int)
    df["_actual_week_start"] = df.apply(lambda row: month_week_start(int(row["_month"]), int(row["_week"])), axis=1)
    df[days_col] = pd.to_numeric(df[days_col], errors="coerce").fillna(0).astype(int)

    daily = df[df[date_col].notna() & (df[date_col] >= START)].copy()
    if daily.empty:
        raise RuntimeError("No daily Xinshiji data found after 2026-07-27.")
    daily["_actual_week_start"] = daily[date_col] - pd.to_timedelta(daily[date_col].dt.weekday, unit="D")

    historical = df[df[date_col].isna()].copy()
    complete_historical = historical[historical[days_col].eq(7)].copy()
    if complete_historical.empty:
        raise RuntimeError("No complete pre-period weekly Xinshiji data found.")
    latest_month = complete_historical["_month"].max()
    latest_month = complete_historical[complete_historical["_month"].eq(latest_month)]
    latest_week = latest_month["_week"].max()
    baseline = latest_month[latest_month["_week"].eq(latest_week)].copy()
    return df, daily, baseline, product_names


def aggregate_daily(daily: pd.DataFrame) -> tuple[list[str], dict]:
    dates = pd.date_range(daily["销售日期"].min(), daily["销售日期"].max(), freq="D")
    result: dict[str, dict] = {}
    present_dates = set(daily["销售日期"])
    for product in PRODUCTS:
        part = daily[daily["条码"].eq(product["barcode"])]
        grouped = part.groupby("销售日期").agg(
            qty=("销售数量", "sum"),
            sales=("销售收入", "sum"),
            stores=("仓位编码", "nunique"),
        ).reindex(dates)
        present = grouped.index.isin(set(part["销售日期"]))
        grouped.loc[present, ["qty", "sales", "stores"]] = grouped.loc[present, ["qty", "sales", "stores"]].fillna(0)
        grouped.loc[~present, ["qty", "sales", "stores"]] = pd.NA
        grouped["price"] = grouped["sales"] / grouped["qty"].replace(0, pd.NA)
        result[product["id"]] = {
            "qty": [round_or_none(v, 2) for v in grouped["qty"]],
            "sales": [round_or_none(v, 2) for v in grouped["sales"]],
            "stores": [int(v) if pd.notna(v) else None for v in grouped["stores"]],
            "price": [round_or_none(v, 2) for v in grouped["price"]],
        }

    total = daily.groupby("销售日期").agg(
        qty=("销售数量", "sum"),
        sales=("销售收入", "sum"),
        stores=("仓位编码", "nunique"),
    ).reindex(dates)
    present_total = total.index.isin(present_dates)
    total.loc[present_total, ["qty", "sales", "stores"]] = total.loc[present_total, ["qty", "sales", "stores"]].fillna(0)
    total.loc[~present_total, ["qty", "sales", "stores"]] = pd.NA
    total["price"] = total["sales"] / total["qty"].replace(0, pd.NA)
    result["total"] = {
        "qty": [round_or_none(v, 2) for v in total["qty"]],
        "sales": [round_or_none(v, 2) for v in total["sales"]],
        "stores": [int(v) if pd.notna(v) else None for v in total["stores"]],
        "price": [round_or_none(v, 2) for v in total["price"]],
    }
    return [f"{d.month}/{d.day}" for d in dates], result

def weekly_payload(full: pd.DataFrame, daily: pd.DataFrame) -> list[dict]:
    date_col = full.columns[4]
    days_col = full.columns[3]
    store_col = full.columns[5]
    barcode_col = full.columns[7]
    qty_col = full.columns[9]
    revenue_col = full.columns[11]

    historical = full[full[date_col].isna() & (full["_actual_week_start"] < START)].copy()
    historical_days = (
        historical[["_actual_week_start", "_month", "_week", days_col]]
        .drop_duplicates()
        .groupby("_actual_week_start")[days_col]
        .sum()
    )
    daily_days = daily.groupby("_actual_week_start")[date_col].nunique()

    week_cols = ["_actual_week_start", store_col, barcode_col, qty_col, revenue_col]
    week_data = pd.concat([historical[week_cols], daily[week_cols]], ignore_index=True)
    complete_weeks = sorted(
        set(historical_days[historical_days.eq(7)].index)
        | set(daily_days[daily_days.eq(7)].index)
    )
    complete_weeks = [week for week in complete_weeks if week >= pd.Timestamp("2026-04-01")]

    rows = []
    for week_start in complete_weeks:
        week_part = week_data[week_data["_actual_week_start"].eq(week_start)]
        items = {}
        for product in PRODUCTS:
            sku = week_part[week_part[barcode_col].eq(product["barcode"])]
            qty = float(sku[qty_col].sum())
            sales = float(sku[revenue_col].sum())
            stores = int(sku[store_col].nunique())
            items[product["id"]] = {
                "qty": int(round(qty)),
                "sales": round_or_none(sales, 2),
                "stores": stores,
                "price": round_or_none(sales / qty if qty else None, 2),
                "psd": round_or_none(qty / stores / 7 if stores else None, 3),
            }
        qty = float(week_part[qty_col].sum())
        sales = float(week_part[revenue_col].sum())
        stores = int(week_part[store_col].nunique())
        items["total"] = {
            "qty": int(round(qty)),
            "sales": round_or_none(sales, 2),
            "stores": stores,
            "price": round_or_none(sales / qty if qty else None, 2),
            "psd": round_or_none(qty / stores / 7 if stores else None, 3),
        }
        rows.append({"start": week_start.strftime("%Y-%m-%d"), "label": week_label(week_start), "items": items})
    return rows


def product_period_metrics(part: pd.DataFrame) -> tuple[float, float, int, float]:
    qty = float(part["销售数量"].sum())
    sales = float(part["销售收入"].sum())
    stores = int(part["仓位编码"].nunique())
    price = sales / qty if qty else None
    return qty, sales, stores, price


def elasticity_payload(daily: pd.DataFrame, baseline: pd.DataFrame) -> list[dict]:
    post_week = daily[(daily["销售日期"] >= START) & (daily["销售日期"] <= POST_WEEK_END)].copy()
    rows = []
    for product in PRODUCTS:
        pre = baseline[baseline["条码"].eq(product["barcode"])]
        post = post_week[post_week["条码"].eq(product["barcode"])]
        pre_qty, pre_sales, pre_stores, pre_price = product_period_metrics(pre)
        post_qty, post_sales, post_stores, post_price = product_period_metrics(post)
        qty_change = post_qty / pre_qty - 1 if pre_qty else None
        price_change = post_price / pre_price - 1 if pre_price and post_price else None
        elasticity = qty_change / price_change if qty_change is not None and price_change not in (None, 0) else None
        rows.append({
            "id": product["id"],
            "short": product["short"],
            "color": product["color"],
            "preQty": int(round(pre_qty)),
            "postQty": int(round(post_qty)),
            "preSales": round_or_none(pre_sales, 2),
            "postSales": round_or_none(post_sales, 2),
            "preStores": pre_stores,
            "postStores": post_stores,
            "prePrice": round_or_none(pre_price, 2),
            "postPrice": round_or_none(post_price, 2),
            "qtyChange": round_or_none(qty_change, 4),
            "priceChange": round_or_none(price_change, 4),
            "elasticity": round_or_none(elasticity, 3),
        })
    return rows


def tier_payload(daily: pd.DataFrame, baseline: pd.DataFrame) -> list[dict]:
    post_week = daily[(daily["销售日期"] >= START) & (daily["销售日期"] <= POST_WEEK_END)].copy()
    pre_store = baseline.groupby("仓位编码")["销售数量"].sum().rename("pre_qty")
    post_store = post_week.groupby("仓位编码")["销售数量"].sum().rename("post_qty").reindex(pre_store.index, fill_value=0)
    stores = pd.concat([pre_store, post_store], axis=1).fillna(0)
    stores["pre_psd"] = stores["pre_qty"] / 7
    stores["post_psd"] = stores["post_qty"] / 7
    stores["tier"] = stores["pre_psd"].map(tier_label)
    rows = []
    grouped = stores.groupby("tier")
    for tier in TIER_ORDER:
        if tier not in grouped.groups:
            continue
        part = grouped.get_group(tier)
        pre_psd = part["pre_psd"].mean()
        post_psd = part["post_psd"].mean()
        rows.append({
            "tier": tier,
            "stores": int(len(part)),
            "prePsd": round_or_none(pre_psd, 3),
            "postPsd": round_or_none(post_psd, 3),
            "uplift": round_or_none(post_psd / pre_psd - 1 if pre_psd else None, 4),
        })
    return rows


def summary_payload(daily: pd.DataFrame) -> list[dict]:
    rows = []
    for product in PRODUCTS:
        sku = daily[daily["条码"].eq(product["barcode"])]
        qty, sales, stores, price = product_period_metrics(sku)
        rows.append({
            "id": product["id"],
            "name": product["name"],
            "short": product["short"],
            "color": product["color"],
            "qty": int(round(qty)),
            "sales": round_or_none(sales, 2),
            "stores": stores,
            "price": round_or_none(price, 2),
        })
    return sorted(rows, key=lambda row: row["qty"], reverse=True)


def table_payload(daily: pd.DataFrame) -> list[dict]:
    rows = []
    for date, part in daily.groupby("销售日期"):
        items = {}
        for product in PRODUCTS:
            sku = part[part["条码"].eq(product["barcode"])]
            items[product["id"]] = {
                "qty": int(round(float(sku["销售数量"].sum()))),
                "sales": round_or_none(float(sku["销售收入"].sum()), 2),
            }
        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "label": f"{date.month}/{date.day}",
            "items": items,
            "totalQty": int(round(float(part["销售数量"].sum()))),
            "totalSales": round_or_none(float(part["销售收入"].sum()), 2),
        })
    return rows

def build_data() -> dict:
    full, daily, baseline, _ = load_data()
    dates, daily_metrics = aggregate_daily(daily)
    weeks = weekly_payload(full, daily)
    elasticity = elasticity_payload(daily, baseline)
    tiers = tier_payload(daily, baseline)
    summary = summary_payload(daily)
    table = table_payload(daily)

    total_qty, total_sales, total_stores, total_price = product_period_metrics(daily)
    pre_qty, pre_sales, _, pre_price = product_period_metrics(baseline)
    post_week = daily[(daily["销售日期"] >= START) & (daily["销售日期"] <= POST_WEEK_END)]
    post_qty, post_sales, _, post_price = product_period_metrics(post_week)
    qty_change = post_qty / pre_qty - 1 if pre_qty else None
    price_change = post_price / pre_price - 1 if pre_price and post_price else None
    elasticity_value = qty_change / price_change if qty_change is not None and price_change not in (None, 0) else None

    return {
        "meta": {
            "start": START.strftime("%Y-%m-%d"),
            "last": daily["销售日期"].max().strftime("%Y-%m-%d"),
            "generatedAt": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "baselineRange": f"{BASELINE_START.month}/{BASELINE_START.day}-{BASELINE_END.month}/{BASELINE_END.day}",
            "postWeekRange": f"{START.month}/{START.day}-{POST_WEEK_END.month}/{POST_WEEK_END.day}",
            "incompleteWeekNote": "周度走势纳入 2026 年 4 月以来的完整自然周，跨月周已合并；数据截止日所在的未满周自动剔除。",
        },
        "products": [{"id": p["id"], "name": p["name"], "short": p["short"], "color": p["color"]} for p in PRODUCTS],
        "dates": dates,
        "daily": daily_metrics,
        "weeks": weeks,
        "summary": summary,
        "elasticity": elasticity,
        "tiers": tiers,
        "table": table,
        "kpi": {
            "totalQty": int(round(total_qty)),
            "totalSales": round_or_none(total_sales, 2),
            "totalStores": total_stores,
            "totalPrice": round_or_none(total_price, 2),
            "prePrice": round_or_none(pre_price, 2),
            "postPrice": round_or_none(post_price, 2),
            "qtyChange": round_or_none(qty_change, 4),
            "priceChange": round_or_none(price_change, 4),
            "elasticity": round_or_none(elasticity_value, 3),
        },
    }


def nav_block(active: str) -> str:
    links = []
    for href, label, key in NAV_ITEMS:
        cls = ' class="active"' if key == active else ""
        links.append(f'    <a{cls} href="{href}">{label}</a>')
    links_html = "\n".join(links)
    return f'''<!-- dashboard-nav:start -->
  <style>
    .dashboard-nav {{ position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 8px; padding: 10px 28px; background: rgba(255,255,255,.94); border-bottom: 1px solid #e5e7eb; backdrop-filter: blur(8px); }}
    .dashboard-nav .brand {{ color: #6b7280; font-weight: 750; margin-right: 6px; white-space: nowrap; }}
    .dashboard-nav a {{ padding: 7px 12px; border-radius: 6px; color: #374151; text-decoration: none; font-size: 13px; font-weight: 700; white-space: nowrap; }}
    .dashboard-nav a.active {{ background: #111827; color: #fff; }}
    @media (max-width: 640px) {{ .dashboard-nav {{ padding-left: 16px; padding-right: 16px; overflow-x: auto; }} }}
  </style>
  <nav class="dashboard-nav">
    <span class="brand">销售看板</span>
{links_html}
  </nav>
  <!-- dashboard-nav:end -->'''

HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>新世纪 70g 玉米片价格弹性看板</title>
  <style>
    :root { --bg:#f5f6f8; --panel:#fff; --border:#e5e7eb; --text:#111827; --muted:#6b7280; --green:#16a34a; --red:#dc2626; --blue:#2563eb; --amber:#d97706; --teal:#0f766e; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; font-size:14px; }
    .topbar { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; padding:22px 28px 14px; }
    h1 { margin:0 0 6px; font-size:22px; letter-spacing:0; }
    h2 { margin:0; font-size:15px; }
    p { margin:0; color:var(--muted); }
    main { padding:0 28px 34px; }
    .kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:16px; }
    .kpi { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:16px; }
    .kpi-label { color:var(--muted); font-size:13px; margin-bottom:10px; }
    .kpi-value { font-size:28px; font-weight:750; line-height:1.1; margin-bottom:8px; }
    .kpi-sub { color:var(--muted); font-size:12px; display:flex; justify-content:space-between; gap:8px; align-items:center; }
    .up { color:var(--green); font-weight:750; }
    .down { color:var(--red); font-weight:750; }
    .neutral { color:var(--muted); }
    .grid { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; }
    .panel { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:16px; min-width:0; }
    .panel-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px; }
    .panel-head span { color:var(--muted); font-size:12px; white-space:nowrap; }
    .wide { grid-column:span 7; }
    .half { grid-column:span 5; }
    .full { grid-column:span 12; }
    .chart { width:100%; height:340px; }
    .chart.short { height:300px; }
    .table-wrap { max-height:380px; overflow:auto; border:1px solid #eef0f3; border-radius:6px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { padding:9px 10px; border-bottom:1px solid #eef0f3; text-align:right; white-space:nowrap; }
    th:first-child,td:first-child { text-align:left; }
    th { position:sticky; top:0; background:#fff; color:var(--muted); font-weight:700; z-index:1; }
    .note { margin-top:12px; color:var(--muted); font-size:12px; line-height:1.7; }
    .section-title { margin:22px 0 12px; font-size:16px; font-weight:750; }
    .pill { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border-radius:999px; background:#f3f4f6; color:#374151; font-size:12px; font-weight:700; }
    .good { color:var(--green); }
    .bad { color:var(--red); }
    @media (max-width:1100px) { .topbar { flex-direction:column; } .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } .wide,.half { grid-column:span 12; } }
    @media (max-width:640px) { .topbar,main { padding-left:16px; padding-right:16px; } .kpis { grid-template-columns:1fr; } .panel-head { flex-direction:column; } .chart { height:280px; } .kpi-value { font-size:24px; } }
  </style>
  <script src="echarts.min.js"></script>
</head>
<body>
__NAV__
  <header class="topbar">
    <div>
      <h1>新世纪 70g 玉米片价格弹性看板</h1>
      <p id="meta"></p>
    </div>
    <span class="pill" id="data-state">每日更新</span>
  </header>

  <main>
    <section class="kpis">
      <article class="kpi"><div class="kpi-label">7/27 后累计销量</div><div class="kpi-value" id="kpi-qty">--</div><div class="kpi-sub"><span id="kpi-stores"></span><span class="neutral">包</span></div></article>
      <article class="kpi"><div class="kpi-label">7/27 后累计销额</div><div class="kpi-value" id="kpi-sales">--</div><div class="kpi-sub"><span id="kpi-date-range"></span><span class="neutral">元</span></div></article>
      <article class="kpi"><div class="kpi-label">累计成交单价</div><div class="kpi-value" id="kpi-price">--</div><div class="kpi-sub"><span id="kpi-price-move"></span><span class="neutral">销额/销量</span></div></article>
      <article class="kpi"><div class="kpi-label">降价首周价格弹性</div><div class="kpi-value" id="kpi-elasticity">--</div><div class="kpi-sub"><span id="kpi-change"></span><span class="neutral">销量/价格</span></div></article>
    </section>

    <div class="section-title">每日价格弹性走势</div>
    <section class="grid">
      <article class="panel wide"><div class="panel-head"><h2>每日销量走势</h2><span>7/27 起，按 SKU 汇总</span></div><div id="chart-qty" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>每日销额走势</h2><span>销售收入合计</span></div><div id="chart-sales" class="chart"></div></article>
      <article class="panel wide"><div class="panel-head"><h2>每日单价走势</h2><span>每日销售收入 / 销售数量</span></div><div id="chart-price" class="chart"></div></article>
    </section>

    <div class="section-title">完整周长期走势（4月-8月）</div>
    <section class="grid">
      <article class="panel full"><div class="panel-head"><h2>完整周销量走势</h2><span>仅完整自然周，跨月周已合并</span></div><div id="chart-weekly-qty" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>完整周销额走势</h2><span>4月-8月完整周</span></div><div id="chart-weekly-sales" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>完整周单价走势</h2><span>周销额 / 周销量</span></div><div id="chart-weekly-price" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>完整周 PSD 走势</h2><span>周销量 / 周去重门店 / 7</span></div><div id="chart-weekly-psd" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>完整周动销门店</h2><span>每周去重仓位数</span></div><div id="chart-weekly-stores" class="chart"></div></article>
    </section>

    <div class="section-title">降价效果与门店分层</div>
    <section class="grid">
      <article class="panel wide"><div class="panel-head"><h2>降价首周销量与价格变化</h2><span>对比降价前完整周</span></div><div id="chart-elasticity" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>SKU 累计销量排行</h2><span>最大值绿色强调</span></div><div id="chart-rank" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>门店分层 PSD 对比</h2><span>按降价前单店日销量分层</span></div><div id="chart-tier" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>分层明细</h2><span>合计为四个 SKU 口径</span></div><div class="table-wrap"><table id="tier-table"></table></div></article>
      <article class="panel full"><div class="panel-head"><h2>SKU 汇总表</h2><span>7/27 后累计口径</span></div><div class="table-wrap"><table id="summary-table"></table></div></article>
      <article class="panel full"><div class="panel-head"><h2>每日销量与销额明细</h2><span>每个 SKU 分别汇总</span></div><div class="table-wrap"><table id="daily-table"></table></div><div class="note" id="week-note"></div></article>
    </section>
  </main>
'''

HTML_TEMPLATE += r'''
  <script>
    const DATA = __DATA__;
    const products = DATA.products;
    const dates = DATA.dates;
    const productById = Object.fromEntries(products.map(p => [p.id, p]));

    const fmtInt = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
    const fmtMoney = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    function pct(value) {
      if (value === null || value === undefined) return "--";
      return (value > 0 ? "+" : "") + (value * 100).toFixed(1) + "%";
    }

    function setText(id, text) { document.getElementById(id).textContent = text; }

    setText("meta", "数据范围：" + DATA.meta.start + " 至 " + DATA.meta.last + "；生成时间：" + DATA.meta.generatedAt);
    setText("data-state", "数据截止 " + DATA.meta.last);
    setText("kpi-qty", fmtInt.format(DATA.kpi.totalQty));
    setText("kpi-sales", "¥" + fmtMoney.format(DATA.kpi.totalSales));
    setText("kpi-price", "¥" + DATA.kpi.totalPrice.toFixed(2));
    setText("kpi-elasticity", DATA.kpi.elasticity.toFixed(2));
    setText("kpi-stores", "覆盖 " + DATA.kpi.totalStores + " 家门店");
    setText("kpi-date-range", DATA.meta.start + " 至 " + DATA.meta.last);
    setText("kpi-price-move", DATA.kpi.prePrice.toFixed(2) + "元 -> " + DATA.kpi.postPrice.toFixed(2) + "元");
    setText("kpi-change", "单价 " + pct(DATA.kpi.priceChange) + "，销量 " + pct(DATA.kpi.qtyChange));
    setText("week-note", DATA.meta.incompleteWeekNote);

    const chartFont = { color: "#374151", fontFamily: "-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif" };
    function axisStyle() {
      return {
        axisLine: { lineStyle: { color: "#d1d5db" } },
        axisTick: { show: false },
        axisLabel: { color: "#6b7280", hideOverlap: true },
        splitLine: { lineStyle: { color: "#eef0f3" } },
      };
    }
    function baseOption(extra) {
      return Object.assign({
        color: products.map(p => p.color),
        textStyle: chartFont,
        grid: { left: 48, right: 24, top: 58, bottom: 42, containLabel: true },
        legend: { top: 8, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: "#4b5563" } },
        tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : fmtMoney.format(value) },
      }, extra);
    }

    const qtyChart = echarts.init(document.getElementById("chart-qty"));
    qtyChart.setOption(baseOption({
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : fmtInt.format(value) },
      xAxis: Object.assign({ type: "category", data: dates }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "包" }, axisStyle()),
      series: products.map(p => ({ name: p.short, type: "line", data: DATA.daily[p.id].qty, smooth: false, symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: p.color }, emphasis: { focus: "series" } })).concat([{
        name: "合计", type: "line", data: DATA.daily.total.qty, smooth: false, symbol: "none",
        lineStyle: { width: 2, color: "#111827", type: "dashed" }, itemStyle: { color: "#111827" }, z: 1,
      }]),
    }));

    const salesChart = echarts.init(document.getElementById("chart-sales"));
    salesChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: dates }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "元" }, axisStyle()),
      series: products.map(p => ({ name: p.short, type: "line", data: DATA.daily[p.id].sales, smooth: false, symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: p.color }, areaStyle: { opacity: 0.04 }, emphasis: { focus: "series" } })),
    }));

    const priceChart = echarts.init(document.getElementById("chart-price"));
    priceChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: dates }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "元/包" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : value.toFixed(2) + " 元" },
      series: products.map(p => ({ name: p.short, type: "line", data: DATA.daily[p.id].price, smooth: false, symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: p.color }, emphasis: { focus: "series" } })).concat([{
        name: "合计单价", type: "line", data: DATA.daily.total.price, smooth: false, symbol: "none",
        lineStyle: { width: 2.5, color: "#111827", type: "dashed" }, itemStyle: { color: "#111827" },
      }]),
    }));

    const weekLabels = DATA.weeks.map(w => w.label);
    function weeklySeries(metric, options = {}) {
      return products.map(p => ({
        name: p.short, type: "line", data: DATA.weeks.map(w => w.items[p.id][metric]),
        smooth: false, symbol: "circle", symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: p.color },
        emphasis: { focus: "series" }, ...options,
      }));
    }
    const weeklyQtyChart = echarts.init(document.getElementById("chart-weekly-qty"));
    weeklyQtyChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: weekLabels, axisLabel: { color: "#6b7280", rotate: 35, hideOverlap: true } }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "?" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : fmtInt.format(value) },
      series: weeklySeries("qty"),
    }));

    const weeklySalesChart = echarts.init(document.getElementById("chart-weekly-sales"));
    weeklySalesChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: weekLabels, axisLabel: { color: "#6b7280", rotate: 35, hideOverlap: true } }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "?" }, axisStyle()),
      series: weeklySeries("sales", { areaStyle: { opacity: 0.04 } }),
    }));

    const weeklyPriceChart = echarts.init(document.getElementById("chart-weekly-price"));
    weeklyPriceChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: weekLabels, axisLabel: { color: "#6b7280", rotate: 35, hideOverlap: true } }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "?/?" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : Number(value).toFixed(2) + " ?" },
      series: weeklySeries("price"),
    }));

    const weeklyPsdChart = echarts.init(document.getElementById("chart-weekly-psd"));
    weeklyPsdChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: weekLabels, axisLabel: { color: "#6b7280", rotate: 35, hideOverlap: true } }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "PSD" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : Number(value).toFixed(3) },
      series: weeklySeries("psd"),
    }));

    const weeklyStoresChart = echarts.init(document.getElementById("chart-weekly-stores"));
    weeklyStoresChart.setOption(baseOption({
      xAxis: Object.assign({ type: "category", data: weekLabels, axisLabel: { color: "#6b7280", rotate: 35, hideOverlap: true } }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "??" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : fmtInt.format(value) },
      series: products.map(p => ({ name: p.short, type: "line", data: DATA.weeks.map(w => w.items[p.id].stores), smooth: false, symbol: "circle", symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: p.color }, emphasis: { focus: "series" } })),
    }));

    const elasticityChart = echarts.init(document.getElementById("chart-elasticity"));
    elasticityChart.setOption(baseOption({
      legend: { top: 8, data: ["销量变化", "单价变化"] },
      xAxis: Object.assign({ type: "category", data: DATA.elasticity.map(d => d.short) }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "变化率", axisLabel: { color: "#6b7280", formatter: value => (value * 100).toFixed(0) + "%" } }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, formatter: params => params.map(p => p.marker + p.seriesName + ": " + pct(p.value)).join("<br>") },
      series: [
        { name: "销量变化", type: "bar", barMaxWidth: 24, itemStyle: { color: "#16a34a", borderRadius: [4,4,0,0] }, data: DATA.elasticity.map(d => d.qtyChange) },
        { name: "单价变化", type: "bar", barMaxWidth: 24, itemStyle: { color: "#dc2626", borderRadius: [4,4,0,0] }, data: DATA.elasticity.map(d => d.priceChange) },
      ],
    }));

    const rankValues = DATA.summary.map(d => d.qty);
    const rankChart = echarts.init(document.getElementById("chart-rank"));
    rankChart.setOption({
      textStyle: chartFont,
      grid: { left: 78, right: 42, top: 16, bottom: 24, containLabel: true },
      xAxis: Object.assign({ type: "value" }, axisStyle()),
      yAxis: Object.assign({ type: "category", data: DATA.summary.map(d => d.short), axisLabel: { color: "#374151", fontWeight: 650 } }, axisStyle(), { splitLine: { show: false } }),
      tooltip: { confine: true, formatter: params => params[0].name + "<br>累计销量：" + fmtInt.format(params[0].value) + " 包" },
      series: [{
        type: "bar",
        barMaxWidth: 20,
        data: DATA.summary.map(d => {
          const sorted = Array.from(new Set(rankValues)).sort((a,b) => b-a);
          const rank = sorted.indexOf(d.qty);
          const opacities = [0.86, 0.66, 0.48, 0.34];
          const opacity = rank === 0 ? 1 : (opacities[Math.min(rank - 1, 3)] || 0.34);
          return { value: d.qty, itemStyle: { color: rank === 0 ? "#16a34a" : "rgba(17,24,39," + opacity + ")", borderRadius: [0,4,4,0] } };
        }),
        label: { show: true, position: "right", color: "#374151", formatter: p => fmtInt.format(p.value) },
      }],
    });

    const tierChart = echarts.init(document.getElementById("chart-tier"));
    tierChart.setOption(baseOption({
      legend: { top: 8, data: ["降价前 PSD", "降价后 PSD"] },
      xAxis: Object.assign({ type: "category", data: DATA.tiers.map(d => d.tier) }, axisStyle()),
      yAxis: Object.assign({ type: "value", name: "PSD" }, axisStyle()),
      tooltip: { trigger: "axis", confine: true, valueFormatter: value => value === null || value === undefined ? "--" : Number(value).toFixed(3) },
      series: [
        { name: "降价前 PSD", type: "bar", barMaxWidth: 22, itemStyle: { color: "#9ca3af", borderRadius: [4,4,0,0] }, data: DATA.tiers.map(d => d.prePsd) },
        { name: "降价后 PSD", type: "bar", barMaxWidth: 22, itemStyle: { color: "#16a34a", borderRadius: [4,4,0,0] }, data: DATA.tiers.map(d => d.postPsd) },
      ],
    }));

    function tableHtml(headers, rows) {
      return "<thead><tr>" + headers.map(h => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>" +
        rows.map(row => "<tr>" + row.map(cell => "<td>" + (cell === null || cell === undefined || cell === "" ? "--" : cell) + "</td>").join("") + "</tr>").join("") + "</tbody>";
    }

    document.getElementById("tier-table").innerHTML = tableHtml(
      ["层级", "门店数", "降价前 PSD", "降价后 PSD", "变化"],
      DATA.tiers.map(t => [t.tier, t.stores, t.prePsd === null ? "--" : t.prePsd.toFixed(3), t.postPsd === null ? "--" : t.postPsd.toFixed(3), "<span class=\"" + (t.uplift >= 0 ? "good" : "bad") + "\">" + pct(t.uplift) + "</span>"])
    );

    document.getElementById("summary-table").innerHTML = tableHtml(
      ["SKU", "累计销量", "累计销额", "成交单价", "动销门店", "降价首周销量变化", "价格弹性"],
      DATA.elasticity.map(e => {
        const s = DATA.summary.find(x => x.id === e.id);
        return [s.name, fmtInt.format(s.qty), "¥" + fmtMoney.format(s.sales), "¥" + s.price.toFixed(2), s.stores, "<span class=\"" + (e.qtyChange >= 0 ? "good" : "bad") + "\">" + pct(e.qtyChange) + "</span>", e.elasticity === null ? "--" : e.elasticity.toFixed(2)];
      })
    );

    const dailyHeaders = ["日期"].concat(products.flatMap(p => [p.short + "销量", p.short + "销额"])).concat(["合计销量", "合计销额"]);
    document.getElementById("daily-table").innerHTML = tableHtml(
      dailyHeaders,
      DATA.table.map(row => [row.date].concat(products.flatMap(p => [fmtInt.format(row.items[p.id].qty), "¥" + fmtMoney.format(row.items[p.id].sales)])).concat([fmtInt.format(row.totalQty), "¥" + fmtMoney.format(row.totalSales)]))
    );

    window.addEventListener("resize", () => {
      [qtyChart, salesChart, priceChart, weeklyQtyChart, weeklySalesChart, weeklyPriceChart, weeklyPsdChart, weeklyStoresChart, elasticityChart, rankChart, tierChart].forEach(chart => chart.resize());
    });
  </script>
</body>
</html>
'''


def write_standalone(html: str) -> None:
    if not ECHARTS_JS.exists():
        print(f"Skipped standalone because {ECHARTS_JS} was not found")
        return
    echarts = ECHARTS_JS.read_text(encoding="utf-8")
    standalone = html.replace('  <script src="echarts.min.js"></script>', f'  <script>\n{echarts}\n  </script>')
    STANDALONE_OUT.write_text(standalone, encoding="utf-8")
    print(f"Built {STANDALONE_OUT.name}")


def patch_nav(path: Path, active: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig")
    block = nav_block(active)
    pattern = re.compile(r"<!-- dashboard-nav:start -->.*?<!-- dashboard-nav:end -->", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text)
    else:
        text = text.replace("<body>", "<body>\n" + block, 1)
    path.write_text(text, encoding="utf-8")


def patch_all_nav() -> None:
    for filename, _label, key in NAV_ITEMS:
        patch_nav(ROOT / filename, key)
        offline_name = filename.replace(".html", "-offline.html") if filename != "index.html" else "offline.html"
        patch_nav(ROOT / offline_name, key)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source workbook: {SOURCE}")
    data = build_data()
    html = HTML_TEMPLATE.replace("__NAV__", nav_block("xinshiji")).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"Built {OUT.name}")
    write_standalone(html)
    patch_all_nav()


if __name__ == "__main__":
    main()
