from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r"C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\feishu-long-term-sync\data\latest.xlsx")
OUT = ROOT / "yonghui.html"
STANDALONE_OUT = ROOT / "yonghui-offline.html"
ECHARTS_JS = ROOT / "echarts.min.js"

PRODUCTS = [
    {"id": "butter", "name": "永辉定制&食验室黄油太妃巴旦木玉米片112g", "short": "黄油太妃112g", "color": "#dc2626"},
    {"id": "cheese", "name": "食验室厚厚奶酪玉米片70g", "short": "厚厚奶酪70g", "color": "#16a34a"},
    {"id": "jasmine", "name": "食验室七窨茉莉奶酪玉米片70g", "short": "七窨茉莉70g", "color": "#2563eb"},
    {"id": "coconut", "name": "食验室生椰奶酪玉米片70g", "short": "生椰奶酪70g", "color": "#d97706"},
]
PROMO_START = pd.Timestamp("2026-07-21")
PROMO_END = pd.Timestamp("2026-08-01")
TIERS = [("0", 0.0, 0.0, True), ("0-1", 0.0, 1.0, False), ("1-2", 1.0, 2.0, False), ("2-5", 2.0, 5.0, False), ("5+", 5.0, math.inf, False)]


def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def clean_store_code(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def round_or_none(value, digits=2):
    if value is None or pd.isna(value):
        return None
    value = float(value)
    if math.isinf(value) or math.isnan(value):
        return None
    return round(value, digits)


def tier_label(value: float) -> str:
    for label, low, high, exact in TIERS:
        if exact:
            if value == low:
                return label
        elif low < value < high:
            return label
    return "5+"


def week_label(start: pd.Timestamp) -> str:
    end = start + pd.Timedelta(days=6)
    return f"{start.month}/{start.day}-{end.month}/{end.day}"


def load_data() -> tuple[pd.DataFrame, set[tuple[str, str, pd.Timestamp]]]:
    df = pd.read_excel(SOURCE, sheet_name=1)
    df.columns = [str(c).strip() for c in df.columns]
    date_col = df.columns[10]
    product_col = df.columns[6]
    store_code_col = df.columns[7]
    store_name_col = df.columns[8]
    qty_col = df.columns[11]
    final_col = df.columns[15]

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df[df[date_col].notna()].copy()
    df[product_col] = df[product_col].astype(str).str.strip()
    df = df[df[product_col].isin([p["name"] for p in PRODUCTS])].copy()
    for col in [qty_col, final_col, df.columns[12], df.columns[13], df.columns[14]]:
        df[col] = clean_num(df[col])
    df[store_code_col] = df[store_code_col].map(clean_store_code)
    df[store_name_col] = df[store_name_col].fillna("?????").astype(str).str.strip()

    # The exported workbook leaves formula results blank, so reconstruct the
    # exact promotion flag from the lookup sheet: store + product + date.
    promo_raw = pd.read_excel(SOURCE, sheet_name=3, header=1)
    promo_raw.columns = [str(c).strip() for c in promo_raw.columns]
    promo_flag_col = promo_raw.columns[-1]
    flag_series = promo_raw[promo_flag_col].dropna().astype(str).str.strip()
    promo_keys = set()
    if not flag_series.empty:
        yes = flag_series.iloc[0]
        flagged = promo_raw[promo_raw[promo_flag_col].astype(str).str.strip().eq(yes)].copy()
        flagged_code_col = flagged.columns[1]
        flagged_product_col = flagged.columns[3]
        flagged_date_col = flagged.columns[4]
        flagged[flagged_date_col] = pd.to_datetime(flagged[flagged_date_col], errors="coerce").dt.normalize()
        for _, row in flagged.iterrows():
            code = clean_store_code(row[flagged_code_col])
            product = str(row[flagged_product_col]).strip()
            event_date = row[flagged_date_col]
            if code and pd.notna(event_date):
                promo_keys.add((code, product, event_date))

    df["is_promo"] = df.apply(
        lambda row: (row[store_code_col], str(row[product_col]).strip(), row[date_col]) in promo_keys,
        axis=1,
    )
    return df, promo_keys


def daily_payload(part: pd.DataFrame, full_dates: pd.DatetimeIndex, present_dates: set[pd.Timestamp]) -> dict:
    grouped = part.groupby("日期").agg(
        qty=("销售数量", "sum"),
        sales=("最终销售金额(销售金额+优惠券金额)", "sum"),
        stores=("门店编码", "nunique"),
    ).reindex(full_dates)
    existing = grouped.index.isin(present_dates)
    grouped.loc[existing, ["qty", "sales", "stores"]] = grouped.loc[existing, ["qty", "sales", "stores"]].fillna(0)
    grouped.loc[~existing, ["qty", "sales", "stores"]] = pd.NA
    grouped["price"] = grouped["sales"] / grouped["qty"].replace(0, pd.NA)
    return {
        "qty": [round_or_none(v, 2) for v in grouped["qty"]],
        "sales": [round_or_none(v, 2) for v in grouped["sales"]],
        "stores": [int(v) if pd.notna(v) else None for v in grouped["stores"]],
        "price": [round_or_none(v, 2) for v in grouped["price"]],
    }


def weekly_payload(part: pd.DataFrame, complete_weeks: list[pd.Timestamp]) -> list[dict]:
    grouped = part.groupby("week_start").agg(
        qty=("销售数量", "sum"),
        sales=("最终销售金额(销售金额+优惠券金额)", "sum"),
        stores=("门店编码", "nunique"),
    )
    rows = []
    for week_start in complete_weeks:
        row = grouped.loc[week_start] if week_start in grouped.index else None
        qty = float(row["qty"]) if row is not None else 0.0
        stores = int(row["stores"]) if row is not None else 0
        rows.append({
            "week": week_start.strftime("%Y-%m-%d"),
            "label": week_label(week_start),
            "qty": int(round(qty)),
            "stores": stores,
            "sales": round_or_none(row["sales"] if row is not None else 0, 2),
            "psd": round_or_none(qty / stores / 7 if stores else None, 3),
        })
    return rows


def product_summary(product: dict, part: pd.DataFrame) -> dict:
    qty = float(part["销售数量"].sum())
    sales = float(part["最终销售金额(销售金额+优惠券金额)"].sum())
    return {
        "id": product["id"],
        "name": product["name"],
        "short": product["short"],
        "color": product["color"],
        "qty": int(round(qty)),
        "sales": round_or_none(sales, 2),
        "stores": int(part["门店编码"].nunique()),
        "price": round_or_none(sales / qty if qty else None, 2),
    }

def promo_analysis(target: pd.DataFrame, promo_keys: set[tuple[str, str, pd.Timestamp]], present_dates: set[pd.Timestamp]) -> dict:
    date_col = target.columns[10]
    product_col = target.columns[6]
    store_code_col = target.columns[7]
    qty_col = target.columns[11]
    sales_col = target.columns[15]

    target_product = str(target[product_col].iloc[0]).strip()
    flag_keys = {key for key in promo_keys if key[1] == target_product}
    if not flag_keys:
        return {
            "promoStoreCount": 0, "promoStoreDays": 0, "promoStart": None, "promoEnd": None,
            "promoDates": [], "promoDaily": [], "otherDaily": [], "verticalDaily": [],
            "summary": {}, "storeTiers": [], "periodTiers": [],
        }

    promo_rows = target[target["is_promo"]].copy()
    promo_dates = sorted({key[2] for key in flag_keys})
    promo_date_set = set(promo_dates)
    all_promo_stores = sorted({key[0] for key in flag_keys})
    promo_store_sets = {}
    for store, _product, date in flag_keys:
        promo_store_sets.setdefault(date, set()).add(store)
    promo_store_days = sum(len(stores) for stores in promo_store_sets.values())

    target_dates = pd.date_range(target[date_col].min(), target[date_col].max(), freq="D")
    promo_pivot = (
        promo_rows.pivot_table(index=store_code_col, columns=date_col, values=qty_col, aggfunc="sum", fill_value=0)
        .reindex(all_promo_stores)
        .reindex(columns=promo_dates, fill_value=0)
    )
    promo_sales_pivot = (
        promo_rows.pivot_table(index=store_code_col, columns=date_col, values=sales_col, aggfunc="sum", fill_value=0)
        .reindex(all_promo_stores)
        .reindex(columns=promo_dates, fill_value=0)
    )
    all_pivot = (
        target.pivot_table(index=store_code_col, columns=date_col, values=qty_col, aggfunc="sum", fill_value=0)
        .reindex(all_promo_stores)
        .reindex(columns=target_dates, fill_value=0)
    )
    flag_df = pd.DataFrame(
        [(store, date, 1) for store, _product, date in flag_keys],
        columns=[store_code_col, date_col, "flag"],
    )
    promo_flag_pivot = (
        flag_df.pivot_table(index=store_code_col, columns=date_col, values="flag", aggfunc="max", fill_value=0)
        .reindex(all_promo_stores)
        .reindex(columns=target_dates, fill_value=0)
        .gt(0)
    )

    promo_daily = []
    for date in promo_dates:
        qty = float(promo_pivot[date].sum())
        stores = int((promo_pivot[date] > 0).sum())
        assigned = len(promo_store_sets[date])
        promo_daily.append({
            "date": date.strftime("%m-%d"),
            "assignedCount": assigned,
            "qty": int(round(qty)),
            "sales": round_or_none(float(promo_sales_pivot[date].sum()), 2),
            "stores": stores,
            "psdActive": round_or_none(qty / stores if stores else None, 3),
            "psdAssigned": round_or_none(qty / assigned if assigned else None, 3),
        })

    other_group = target[target[date_col].isin(promo_date_set) & ~target["is_promo"]].copy()
    other_grouped = other_group.groupby(date_col).agg(
        qty=(qty_col, "sum"), sales=(sales_col, "sum"), stores=(store_code_col, "nunique")
    ).reindex(promo_dates).fillna(0)
    other_daily = []
    for date, row in other_grouped.iterrows():
        qty = float(row["qty"])
        stores = int(row["stores"])
        other_daily.append({
            "date": date.strftime("%m-%d"),
            "assignedCount": None,
            "qty": int(round(qty)),
            "sales": round_or_none(float(row["sales"]), 2),
            "stores": stores,
            "psdActive": round_or_none(qty / stores if stores else None, 3),
            "psdAssigned": None,
        })

    promo_qty = sum(r["qty"] for r in promo_daily)
    other_qty = sum(r["qty"] for r in other_daily)
    promo_store_days_active = sum(r["stores"] for r in promo_daily)
    other_store_days_active = sum(r["stores"] for r in other_daily)
    promo_psd_assigned = promo_qty / promo_store_days if promo_store_days else None
    promo_psd_active = promo_qty / promo_store_days_active if promo_store_days_active else None
    other_psd_active = other_qty / other_store_days_active if other_store_days_active else None

    vertical_daily = []
    for date in promo_dates:
        stores_for_date = sorted(promo_store_sets[date])
        same_weekday_dates = [d for d in target_dates if d.weekday() == date.weekday()]
        baseline_total = 0.0
        baseline_denominator = 0
        for base_date in same_weekday_dates:
            store_mask = ~promo_flag_pivot.loc[stores_for_date, base_date]
            baseline_total += float(all_pivot.loc[stores_for_date, base_date][store_mask].sum())
            baseline_denominator += int(store_mask.sum())
        promo_value = float(all_pivot.loc[stores_for_date, date].sum()) / len(stores_for_date)
        baseline_value = baseline_total / baseline_denominator if baseline_denominator else None
        vertical_daily.append({
            "date": date.strftime("%m-%d"),
            "promo": round_or_none(promo_value, 3),
            "baseline": round_or_none(baseline_value, 3),
            "delta": round_or_none(promo_value / baseline_value - 1 if baseline_value else None, 3),
        })

    store_tier_inputs = []
    for store in all_promo_stores:
        store_promo_dates = sorted(promo_rows[promo_rows[store_code_col].eq(store)][date_col].unique())
        weekdays = {d.weekday() for d in store_promo_dates}
        baseline_dates = [
            d for d in target_dates
            if d.weekday() in weekdays and not bool(promo_flag_pivot.loc[store, d])
        ]
        baseline_avg = float(all_pivot.loc[store, baseline_dates].sum()) / len(baseline_dates) if baseline_dates else 0.0
        promo_avg = float(all_pivot.loc[store, store_promo_dates].sum()) / len(store_promo_dates) if store_promo_dates else 0.0
        store_tier_inputs.append((store, baseline_avg, promo_avg))

    tier_rows = []
    for label, _, _, _ in TIERS:
        selected = [item for item in store_tier_inputs if tier_label(item[1]) == label]
        count = len(selected)
        base = sum(item[1] for item in selected) / count if count else 0.0
        promo_avg = sum(item[2] for item in selected) / count if count else 0.0
        tier_rows.append({
            "tier": label,
            "stores": count,
            "baseline": round_or_none(base, 3),
            "promo": round_or_none(promo_avg, 3),
            "uplift": round_or_none(promo_avg / base - 1 if base else None, 3),
        })

    promo_period_avgs = [item[2] for item in store_tier_inputs]
    other_pivot = other_group.pivot_table(
        index=store_code_col, columns=date_col, values=qty_col, aggfunc="sum", fill_value=0
    )
    other_period_avgs = []
    for _, row in other_pivot.iterrows():
        active_days = int((row > 0).sum())
        if active_days:
            other_period_avgs.append(float(row.sum()) / active_days)
    period_tiers = []
    for label, _, _, _ in TIERS:
        period_tiers.append({
            "tier": label,
            "promoStores": sum(1 for v in promo_period_avgs if tier_label(v) == label),
            "otherStores": sum(1 for v in other_period_avgs if tier_label(v) == label),
        })

    baseline_psd = sum(item[1] for item in store_tier_inputs) / len(store_tier_inputs) if store_tier_inputs else None
    return {
        "promoStoreCount": len(all_promo_stores),
        "promoStoreDays": promo_store_days,
        "promoStart": min(promo_dates).strftime("%Y-%m-%d"),
        "promoEnd": max(promo_dates).strftime("%Y-%m-%d"),
        "promoDates": [d.strftime("%Y-%m-%d") for d in promo_dates],
        "promoDaily": promo_daily,
        "otherDaily": other_daily,
        "verticalDaily": vertical_daily,
        "summary": {
            "promoQty": int(promo_qty),
            "otherQty": int(other_qty),
            "promoDailyQty": round_or_none(promo_qty / len(promo_dates), 1),
            "otherDailyQty": round_or_none(other_qty / len(promo_dates), 1),
            "promoActiveStores": round_or_none(promo_store_days_active / len(promo_dates), 1),
            "otherActiveStores": round_or_none(other_store_days_active / len(promo_dates), 1),
            "promoPsdActive": round_or_none(promo_psd_active, 3),
            "otherPsdActive": round_or_none(other_psd_active, 3),
            "promoPsdAssigned": round_or_none(promo_psd_assigned, 3),
            "baselinePsdAssigned": round_or_none(baseline_psd, 3),
            "promoAssignedUplift": round_or_none(promo_psd_assigned / baseline_psd - 1 if baseline_psd else None, 3),
        },
        "storeTiers": tier_rows,
        "periodTiers": period_tiers,
    }


def opportunity_stores(df: pd.DataFrame, products: dict[str, dict], present_dates: set[pd.Timestamp]) -> list[dict]:
    recent_dates = sorted(present_dates)[-28:]
    recent = df[df["日期"].isin(recent_dates)]
    butter_stores = set(recent[recent["商品名称"].eq(products["butter"]["name"])]["门店编码"])
    cheese = recent[recent["商品名称"].eq(products["cheese"]["name"])]
    grouped = cheese[~cheese["门店编码"].isin(butter_stores)].groupby(["门店编码", "门店名称"]).agg(
        qty=("销售数量", "sum"), sales=("最终销售金额(销售金额+优惠券金额)", "sum")
    ).reset_index().sort_values("qty", ascending=False).head(20)
    return [
        {"name": row["门店名称"], "code": row["门店编码"], "qty": int(round(row["qty"])), "sales": round_or_none(row["sales"], 2)}
        for _, row in grouped.iterrows()
    ]

def build_data() -> dict:
    df, promo_keys = load_data()
    product_map = {p["id"]: p for p in PRODUCTS}
    full_dates = pd.date_range(df["日期"].min(), df["日期"].max(), freq="D")
    present_dates = set(df["日期"].dropna().unique())
    df["week_start"] = df["日期"] - pd.to_timedelta(df["日期"].dt.weekday, unit="D")
    week_counts = df.groupby("week_start")["日期"].nunique()
    complete_weeks = sorted(week_counts[week_counts.eq(7)].index)

    products_payload = {}
    monthly_rows = []
    month_days = df.groupby(df["日期"].dt.strftime("%Y-%m"))["日期"].nunique().sort_index()
    months = [{"id": idx, "label": f"{int(idx.split('-')[1])}月", "days": int(days)} for idx, days in month_days.items()]

    for product in PRODUCTS:
        part = df[df["商品名称"].eq(product["name"])].copy()
        first_week = part["日期"].min() - pd.Timedelta(days=part["日期"].min().weekday())
        product_weeks = [w for w in complete_weeks if w > first_week]
        payload = {
            **product_summary(product, part),
            "daily": daily_payload(part, full_dates, present_dates),
            "weekly": weekly_payload(part, product_weeks),
            "monthly": [],
        }
        products_payload[product["id"]] = payload

        for month_id, days in month_days.items():
            month_part = part[part["日期"].dt.strftime("%Y-%m").eq(month_id)]
            if month_part.empty:
                continue
            daily_active = month_part.groupby("日期")["门店编码"].nunique()
            payload["monthly"].append({
                "month": month_id,
                "days": int(days),
                "activeStoresAvg": round_or_none(daily_active.mean(), 1),
                "qty": int(round(month_part["销售数量"].sum())),
                "sales": round_or_none(month_part["最终销售金额(销售金额+优惠券金额)"].sum(), 2),
            })
            store_group = month_part.groupby(["门店编码", "门店名称"]).agg(
                qty=("销售数量", "sum"), sales=("最终销售金额(销售金额+优惠券金额)", "sum")
            ).reset_index()
            for _, row in store_group.iterrows():
                monthly_rows.append({
                    "product": product["id"],
                    "month": month_id,
                    "store": row["门店编码"],
                    "name": row["门店名称"],
                    "qty": int(round(row["qty"])),
                    "sales": round_or_none(row["sales"], 2),
                    "days": int(days),
                })

    target = df[df["商品名称"].eq(product_map["butter"]["name"])].copy()
    latest_week = complete_weeks[-1]
    latest_mix = []
    for product in PRODUCTS:
        part = df[(df["商品名称"].eq(product["name"])) & (df["week_start"].eq(latest_week))]
        latest_mix.append({
            "name": product["short"],
            "qty": int(round(part["销售数量"].sum())),
            "sales": round_or_none(part["最终销售金额(销售金额+优惠券金额)"].sum(), 2),
            "stores": int(part["门店编码"].nunique()),
            "color": product["color"],
        })
    latest_mix = sorted(latest_mix, key=lambda item: item["sales"] or 0, reverse=True)

    last_week_end = latest_week + pd.Timedelta(days=6)
    return {
        "meta": {
            "dataStart": full_dates.min().strftime("%Y-%m-%d"),
            "dataEnd": full_dates.max().strftime("%Y-%m-%d"),
            "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "completeWeeks": len(complete_weeks),
            "lastCompleteWeek": week_label(latest_week),
            "missingDates": [d.strftime("%Y-%m-%d") for d in full_dates if d not in present_dates],
        },
        "dates": [d.strftime("%Y-%m-%d") for d in full_dates],
        "months": months,
        "defaultMonths": [months[-2]["id"]] if len(months) >= 2 else [months[-1]["id"]],
        "products": products_payload,
        "productOrder": [p["id"] for p in PRODUCTS],
        "promo": promo_analysis(target, promo_keys, present_dates),
        "latestMix": latest_mix,
        "storeMonthly": monthly_rows,
        "opportunity": opportunity_stores(df, product_map, present_dates),
        "lastWeek": {"start": latest_week.strftime("%Y-%m-%d"), "end": last_week_end.strftime("%Y-%m-%d")},
    }


def nav_block(active: str) -> str:
    drf_class = "active" if active == "drf" else ""
    yh_class = "active" if active == "yonghui" else ""
    return f'''<!-- dashboard-nav:start -->
  <style>
    .dashboard-nav {{ position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 8px; padding: 10px 28px; background: rgba(255,255,255,.94); border-bottom: 1px solid #e5e7eb; backdrop-filter: blur(8px); }}
    .dashboard-nav .brand {{ color: #6b7280; font-weight: 750; margin-right: 6px; }}
    .dashboard-nav a {{ padding: 7px 12px; border-radius: 6px; color: #374151; text-decoration: none; font-size: 13px; font-weight: 700; }}
    .dashboard-nav a.active {{ background: #111827; color: #fff; }}
    @media (max-width: 640px) {{ .dashboard-nav {{ padding-left: 16px; padding-right: 16px; overflow-x: auto; }} }}
  </style>
  <nav class="dashboard-nav">
    <span class="brand">销售看板</span>
    <a class="{drf_class}" href="index.html">大润发 70g 价格测试</a>
    <a class="{yh_class}" href="yonghui.html">永辉 112g 促销分析</a>
  </nav>
  <!-- dashboard-nav:end -->'''


def write_standalone(html: str) -> None:
    if not ECHARTS_JS.exists():
        print(f"Skipped standalone because {ECHARTS_JS} was not found")
        return
    start = html.find('  <script src="echarts.min.js"></script>')
    data_const = html.find("const DATA = ", start)
    next_script = html.rfind("  <script>", 0, data_const)
    if start < 0 or data_const < 0 or next_script < 0:
        print("Skipped standalone because ECharts block was not found")
        return
    echarts = ECHARTS_JS.read_text(encoding="utf-8")
    standalone = html[:start] + f"  <script>\n{echarts}\n  </script>\n\n" + html[next_script:]
    STANDALONE_OUT.write_text(standalone, encoding="utf-8")
    print(f"Built {STANDALONE_OUT.name}")


def patch_existing_drf_nav() -> None:
    for filename in ["index.html", "offline.html"]:
        path = ROOT / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        block = nav_block("drf")
        pattern = re.compile(r"<!-- dashboard-nav:start -->.*?<!-- dashboard-nav:end -->", re.S)
        if pattern.search(text):
            text = pattern.sub(block, text)
        else:
            text = text.replace("<body>", "<body>\n" + block, 1)
        path.write_text(text, encoding="utf-8")

HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>永辉 112g 促销分析看板</title>
  <style>
    :root { --bg:#f5f6f8; --panel:#fff; --border:#e5e7eb; --text:#111827; --muted:#6b7280; --green:#16a34a; --red:#dc2626; --blue:#2563eb; --amber:#d97706; }
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
    .kpi-sub { color:var(--muted); font-size:12px; display:flex; justify-content:space-between; gap:8px; }
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
    .table-wrap { max-height:340px; overflow:auto; border:1px solid #eef0f3; border-radius:6px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { padding:9px 10px; border-bottom:1px solid #eef0f3; text-align:right; white-space:nowrap; }
    th:first-child,td:first-child { text-align:left; }
    th { position:sticky; top:0; background:#fff; color:var(--muted); font-weight:700; z-index:1; }
    .note { margin-top:12px; color:var(--muted); font-size:12px; line-height:1.7; }
    .filters { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:center; }
    .month-check { display:inline-flex; align-items:center; gap:4px; padding:4px 8px; border:1px solid #e5e7eb; border-radius:999px; color:#374151; background:#fff; font-size:12px; cursor:pointer; }
    .month-check input { margin:0; }
    .section-title { margin: 22px 0 12px; font-size:16px; font-weight:750; }
    @media (max-width:1100px) { .topbar { flex-direction:column; } .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } .wide,.half { grid-column:span 12; } }
    @media (max-width:640px) { .topbar,main { padding-left:16px; padding-right:16px; } .kpis { grid-template-columns:1fr; } .panel-head { flex-direction:column; } .chart { height:280px; } .kpi-value { font-size:24px; } }
  </style>
</head>
<body>
__NAV__
  <header class="topbar">
    <div>
      <h1>永辉 112g 黄油太妃巴旦木玉米片促销分析</h1>
      <p id="meta"></p>
    </div>
  </header>

  <main>
    <section class="kpis">
      <article class="kpi"><div class="kpi-label">112g 累计销量</div><div class="kpi-value" id="kpi-qty">--</div><div class="kpi-sub"><span id="kpi-stores"></span><span class="neutral">包</span></div></article>
      <article class="kpi"><div class="kpi-label">112g 累计销额</div><div class="kpi-value" id="kpi-sales">--</div><div class="kpi-sub"><span id="kpi-price"></span><span class="neutral">最终成交</span></div></article>
      <article class="kpi"><div class="kpi-label">推广门店数</div><div class="kpi-value" id="kpi-promo-stores">--</div><div class="kpi-sub"><span id="kpi-promo-dates"></span><span class="neutral">货架促销</span></div></article>
      <article class="kpi"><div class="kpi-label">推广期门店 PSD 提升</div><div class="kpi-value" id="kpi-uplift">--</div><div class="kpi-sub"><span id="kpi-psd-base"></span><span id="kpi-psd-delta"></span></div></article>
    </section>

    <div class="section-title">一、每日销量、销额、单价走势</div>
    <section class="grid">
      <article class="panel wide"><div class="panel-head"><h2>每日销售数量</h2><span>按商品名称分别汇总</span></div><div id="chart-qty" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>最近完整周销额结构</h2><span id="last-week"></span></div><div id="chart-mix" class="chart"></div></article>
      <article class="panel wide"><div class="panel-head"><h2>每日最终销额</h2><span>销售金额 + 优惠券金额</span></div><div id="chart-sales" class="chart"></div></article>
      <article class="panel half"><div class="panel-head"><h2>每日成交单价</h2><span>最终销额 / 销售数量</span></div><div id="chart-price" class="chart"></div></article>
      <article class="panel full"><div class="panel-head"><h2>周度 PSD 走势</h2><span>完整自然周；当周销量 / 当周去重门店 / 7</span></div><div id="chart-psd" class="chart short"></div></article>
    </section>

    <div class="section-title">二、门店分层与推广效果</div>
    <section class="grid">
      <article class="panel half">
        <div class="panel-head"><h2>各产品门店分层</h2><span>单店日均销量</span></div>
        <div id="month-filters" class="filters" style="margin-bottom:12px"></div>
        <div id="chart-tier" class="chart short"></div>
      </article>
      <article class="panel half"><div class="panel-head"><h2>月内日均动销门店</h2><span>每日去重门店求和 / 当月日期数</span></div><div class="table-wrap"><table id="month-table"></table></div></article>
      <article class="panel wide"><div class="panel-head"><h2>横向对比：已标记 vs 未标记</h2><span>仅巴旦木玉米片；按“推广促销=是”标记</span></div><div id="chart-promo-compare" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>推广期核心差异</h2><span>同日期数量与 PSD</span></div><div class="table-wrap"><table id="promo-table"></table></div></article>
      <article class="panel wide"><div class="panel-head"><h2>推广门店纵向同星期对比</h2><span>推广日 vs 非推广同星期均值</span></div><div id="chart-vertical" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>推广门店基线分层</h2><span>按非推广同星期单店日均分层</span></div><div id="chart-promo-tier" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>推广期活动层级分布</h2><span>按推广期单店日均销量分层</span></div><div id="chart-period-tier" class="chart short"></div></article>
    </section>

    <div class="section-title">三、增量机会与商品产出</div>
    <section class="grid">
      <article class="panel wide"><div class="panel-head"><h2>近 28 个有数据日期：卖厚厚奶酪但未卖 112g 的门店 Top 20</h2><span>铺货与转化机会</span></div><div id="chart-opportunity" class="chart short"></div></article>
      <article class="panel half"><div class="panel-head"><h2>SKU 累计产出</h2><span>全周期</span></div><div class="table-wrap"><table id="sku-table"></table></div></article>
    </section>
    <p class="note" id="footnote"></p>
  </main>

  <script src="echarts.min.js"></script>
  <script>
    if (typeof echarts === 'undefined') {
      document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\/script>');
    }
  </script>
  <script>
    const DATA = __DATA__;
    const chartInstances = {};
    const money = new Intl.NumberFormat('zh-CN', { style:'currency', currency:'CNY', maximumFractionDigits: 0 });
    const money2 = new Intl.NumberFormat('zh-CN', { style:'currency', currency:'CNY', minimumFractionDigits:2, maximumFractionDigits:2 });
    const intFmt = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });
    const dec1 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits:1, maximumFractionDigits:1 });
    const dec3 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits:3, maximumFractionDigits:3 });
    const state = { months: new Set(DATA.defaultMonths) };

    function chart(id) { if (!chartInstances[id]) chartInstances[id] = echarts.init(document.getElementById(id), null, { renderer:'svg' }); return chartInstances[id]; }
    function fmtMoney(v) { return v == null ? '--' : money.format(v); }
    function fmtMoney2(v) { return v == null ? '--' : money2.format(v); }
    function fmtInt(v) { return v == null ? '--' : intFmt.format(v); }
    function fmtDec(v,d=1) { if (v == null) return '--'; return d === 3 ? dec3.format(v) : dec1.format(v); }
    function pct(v) { return v == null ? '--' : (v * 100).toFixed(1) + '%'; }
    function deltaHtml(value, base) { if (value == null || base == null || base === 0) return '<span class="neutral">--</span>'; const d = value / base - 1; return `<span class="${d>=0?'up':'down'}">${d>=0?'▲':'▼'} ${pct(d)}</span>`; }
    function tierLabel(v) { if (v === 0) return '0'; if (v < 1) return '0-1'; if (v < 2) return '1-2'; if (v < 5) return '2-5'; return '5+'; }

    function lineOption(metric, yName, isMoney) {
      const series = DATA.productOrder.map(id => {
        const p = DATA.products[id];
        return {
          name: p.short, type:'line', data:p.daily[metric], smooth:true, showSymbol:false, connectNulls:false,
          lineStyle:{width: id==='butter'?2.6:1.9, color:p.color}, itemStyle:{color:p.color}, emphasis:{focus:'series'},
          markLine: id==='butter' ? {symbol:'none', label:{formatter:'推广期'}, lineStyle:{color:'#dc2626',type:'dashed'}, data: DATA.promo.promoDates.map(d => ({xAxis: d}))} : undefined
        };
      });
      return {
        color: DATA.productOrder.map(id => DATA.products[id].color), tooltip:{trigger:'axis', confine:true, valueFormatter:v => isMoney ? fmtMoney2(v) : fmtInt(v)},
        legend:{top:8, textStyle:{color:'#374151'}}, grid:{left:56,right:38,top:54,bottom:72},
        xAxis:{type:'category', data:DATA.dates, boundaryGap:false, axisLabel:{color:'#6b7280', rotate:45, formatter:v=>v.slice(5)}, axisLine:{lineStyle:{color:'#d1d5db'}}},
        yAxis:{type:'value', name:yName, nameTextStyle:{color:'#6b7280'}, splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280', formatter:v => isMoney ? Math.round(v) : fmtInt(v)}},
        dataZoom:[{type:'inside', start:0, end:100},{type:'slider', height:18, bottom:18, borderColor:'#e5e7eb'}], series
      };
    }

    function psdOption() {
      return {
        color: DATA.productOrder.map(id => DATA.products[id].color), tooltip:{trigger:'axis', confine:true, valueFormatter:v => fmtDec(v,3)},
        legend:{top:8}, grid:{left:56,right:36,top:54,bottom:58},
        xAxis:{type:'category', data:DATA.products.butter.weekly.map(w=>w.label), axisLabel:{color:'#6b7280', rotate:35}},
        yAxis:{type:'value', name:'PSD', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}},
        series: DATA.productOrder.map(id => ({name:DATA.products[id].short, type:'line', smooth:true, showSymbol:false, data:DATA.products[id].weekly.map(w=>w.psd)}))
      };
    }

    function rankedOption(items, valueKey, currency=false) {
      const sorted = [...items].sort((a,b)=>(a[valueKey]||0)-(b[valueKey]||0));
      const max = Math.max(...sorted.map(x=>x[valueKey]||0));
      return {
        tooltip:{trigger:'axis', axisPointer:{type:'shadow'}, confine:true, formatter:p => { const item=sorted[p[0].dataIndex]; return `${item.name}<br/>销量: ${fmtInt(item.qty || 0)}<br/>销额: ${fmtMoney(item.sales||0)}`; }},
        grid:{left:128,right:66,top:12,bottom:24}, xAxis:{type:'value', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280', formatter:v=>currency?Math.round(v):fmtInt(v)}},
        yAxis:{type:'category', data:sorted.map(x=>x.name), axisTick:{show:false}, axisLine:{show:false}, axisLabel:{color:'#374151', width:116, overflow:'truncate'}},
        series:[{type:'bar', barWidth:18, data:sorted.map((item,index) => ({value:item[valueKey], itemStyle:{color: (item[valueKey]||0)===max ? '#16a34a' : `rgba(17,24,39,${Math.max(.34,.9-(sorted.length-1-index)*.09).toFixed(2)})`}})), label:{show:true, position:'right', color:'#374151', formatter:p=>currency?fmtMoney(p.value):fmtInt(p.value)}}]
      };
    }
    function tierOption() {
      const labels = ['0','0-1','1-2','2-5','5+'];
      const monthDays = DATA.months.filter(m=>state.months.has(m.id)).reduce((a,m)=>a+m.days,0);
      const series = DATA.productOrder.map(id => {
        const rows = DATA.storeMonthly.filter(r=>r.product===id && state.months.has(r.month));
        const byStore = {};
        rows.forEach(r => { byStore[r.store] = (byStore[r.store]||0) + r.qty; });
        const counts = labels.map(l => Object.values(byStore).filter(q => tierLabel(q / monthDays) === l).length);
        return { name: DATA.products[id].short, type:'bar', stack:'stores', emphasis:{focus:'series'}, data:counts, itemStyle:{color:DATA.products[id].color} };
      });
      return { color:DATA.productOrder.map(id=>DATA.products[id].color), tooltip:{trigger:'axis', axisPointer:{type:'shadow'}, confine:true}, legend:{top:8}, grid:{left:48,right:24,top:52,bottom:36}, xAxis:{type:'category', data:labels, name:'单店日均销量(包)', axisLabel:{color:'#6b7280'}}, yAxis:{type:'value', name:'门店数', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}}, series };
    }

    function renderMonthFilters() {
      document.getElementById('month-filters').innerHTML = DATA.months.map(m => `<label class="month-check"><input type="checkbox" value="${m.id}" ${state.months.has(m.id)?'checked':''}>${m.label}<span style="color:#9ca3af">(${m.days}天)</span></label>`).join('');
      document.querySelectorAll('#month-filters input').forEach(input => input.addEventListener('change', () => {
        if (input.checked) state.months.add(input.value); else state.months.delete(input.value);
        if (state.months.size === 0) { state.months.add(input.value); input.checked = true; }
        chart('chart-tier').setOption(tierOption(), true);
        renderTables();
      }));
    }

    function promoCompareOption() {
      const dates = DATA.promo.promoDaily.map(x=>x.date);
      return {
        color:['#dc2626','#d1d5db','#2563eb','#60a5fa'], tooltip:{trigger:'axis', confine:true}, legend:{top:8}, grid:{left:56,right:56,top:54,bottom:42},
        xAxis:{type:'category', data:dates, axisLabel:{color:'#6b7280'}},
        yAxis:[{type:'value', name:'销量', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}},{type:'value', name:'PSD', splitLine:{show:false}, axisLabel:{color:'#6b7280'}}],
        series:[
          {name:'推广门店销量', type:'bar', data:DATA.promo.promoDaily.map(x=>x.qty), itemStyle:{color:'#dc2626'}, barMaxWidth:24},
          {name:'其他门店销量', type:'bar', data:DATA.promo.otherDaily.map(x=>x.qty), itemStyle:{color:'#d1d5db'}, barMaxWidth:24},
          {name:'推广门店PSD', type:'line', yAxisIndex:1, data:DATA.promo.promoDaily.map(x=>x.psdActive), smooth:true, itemStyle:{color:'#2563eb'}},
          {name:'其他门店PSD', type:'line', yAxisIndex:1, data:DATA.promo.otherDaily.map(x=>x.psdActive), smooth:true, itemStyle:{color:'#60a5fa'}}
        ]
      };
    }

    function verticalOption() {
      const d = DATA.promo.verticalDaily;
      return {
        color:['#dc2626','#6b7280','#16a34a'], tooltip:{trigger:'axis', confine:true}, legend:{top:8}, grid:{left:56,right:42,top:54,bottom:42},
        xAxis:{type:'category', data:d.map(x=>x.date), axisLabel:{color:'#6b7280'}},
        yAxis:{type:'value', name:'推广门店 PSD / 店 / 日', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}},
        series:[
          {name:'推广日', type:'bar', data:d.map(x=>x.promo), itemStyle:{color:'#dc2626'}, barMaxWidth:24},
          {name:'同星期非推广基线', type:'line', data:d.map(x=>x.baseline), smooth:true, itemStyle:{color:'#6b7280'}, lineStyle:{width:2}},
          {name:'提升量', type:'line', data:d.map(x=>x.promo!=null&&x.baseline!=null?+(x.promo-x.baseline).toFixed(3):null), smooth:true, itemStyle:{color:'#16a34a'}, lineStyle:{width:2,type:'dashed'}}
        ]
      };
    }

    function promoTierOption() {
      const rows = DATA.promo.storeTiers;
      return {
        color:['#e5e7eb','#dc2626','#6b7280'], tooltip:{trigger:'axis', confine:true}, legend:{top:8}, grid:{left:48,right:42,top:54,bottom:36},
        xAxis:{type:'category', data:rows.map(x=>x.tier), name:'基线单店日均', axisLabel:{color:'#6b7280'}},
        yAxis:[{type:'value', name:'门店数', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}},{type:'value', name:'PSD', splitLine:{show:false}, axisLabel:{color:'#6b7280'}}],
        series:[
          {name:'门店数', type:'bar', data:rows.map(x=>x.stores), itemStyle:{color:'#e5e7eb'}, barMaxWidth:28},
          {name:'推广期PSD', type:'line', yAxisIndex:1, data:rows.map(x=>x.promo), itemStyle:{color:'#dc2626'}, smooth:true},
          {name:'基线PSD', type:'line', yAxisIndex:1, data:rows.map(x=>x.baseline), itemStyle:{color:'#6b7280'}, smooth:true}
        ]
      };
    }

    function periodTierOption() {
      const rows = DATA.promo.periodTiers;
      return {
        color:['#dc2626','#9ca3af'], tooltip:{trigger:'axis', axisPointer:{type:'shadow'}, confine:true}, legend:{top:8}, grid:{left:48,right:24,top:54,bottom:36},
        xAxis:{type:'category', data:rows.map(x=>x.tier), name:'推广期单店日均', axisLabel:{color:'#6b7280'}},
        yAxis:{type:'value', name:'门店数', splitLine:{lineStyle:{color:'#eef0f3'}}, axisLabel:{color:'#6b7280'}},
        series:[{name:'推广门店', type:'bar', data:rows.map(x=>x.promoStores), itemStyle:{color:'#dc2626'}},{name:'其他动销门店', type:'bar', data:rows.map(x=>x.otherStores), itemStyle:{color:'#d1d5db'}}]
      };
    }
    function renderTables() {
      const s = DATA.promo.summary;
      document.getElementById('promo-table').innerHTML = `<thead><tr><th>指标</th><th>推广门店</th><th>其他门店</th><th>差异</th></tr></thead><tbody>
        <tr><td>日均销量</td><td>${fmtDec(s.promoDailyQty)}</td><td>${fmtDec(s.otherDailyQty)}</td><td>${fmtDec(s.promoDailyQty-s.otherDailyQty)}</td></tr>
        <tr><td>总销量</td><td>${fmtInt(s.promoQty)}</td><td>${fmtInt(s.otherQty)}</td><td>${fmtInt(s.promoQty-s.otherQty)}</td></tr>
        <tr><td>日均动销门店</td><td>${fmtDec(s.promoActiveStores)}</td><td>${fmtDec(s.otherActiveStores)}</td><td>${fmtDec(s.promoActiveStores-s.otherActiveStores)}</td></tr>
        <tr><td>动销门店 PSD</td><td>${fmtDec(s.promoPsdActive,3)}</td><td>${fmtDec(s.otherPsdActive,3)}</td><td>${deltaHtml(s.promoPsdActive,s.otherPsdActive)}</td></tr>
      </tbody>`;
      document.getElementById('sku-table').innerHTML = `<thead><tr><th>SKU</th><th>销量</th><th>销额</th><th>门店</th><th>单价</th></tr></thead><tbody>${DATA.productOrder.map(id=>{const p=DATA.products[id];return `<tr><td>${p.short}</td><td>${fmtInt(p.qty)}</td><td>${fmtMoney(p.sales)}</td><td>${fmtInt(p.stores)}</td><td>${fmtMoney2(p.price)}</td></tr>`}).join('')}</tbody>`;
      const monthRows = DATA.productOrder.flatMap(id => DATA.products[id].monthly.filter(m=>state.months.has(m.month)).map(m => ({product:DATA.products[id].short, ...m})));
      document.getElementById('month-table').innerHTML = `<thead><tr><th>月份</th><th>SKU</th><th>日均动销门店</th><th>销量</th><th>销额</th></tr></thead><tbody>${monthRows.map(r=>`<tr><td>${r.month}</td><td>${r.product}</td><td>${fmtDec(r.activeStoresAvg)}</td><td>${fmtInt(r.qty)}</td><td>${fmtMoney(r.sales)}</td></tr>`).join('')}</tbody>`;
    }

    function renderKpis() {
      const butter = DATA.products.butter;
      const s = DATA.promo.summary;
      document.getElementById('kpi-qty').textContent = fmtInt(butter.qty);
      document.getElementById('kpi-sales').textContent = fmtMoney(butter.sales);
      document.getElementById('kpi-promo-stores').textContent = fmtInt(DATA.promo.promoStoreCount);
      document.getElementById('kpi-uplift').textContent = pct(s.promoAssignedUplift);
      document.getElementById('kpi-stores').textContent = `动销门店 ${fmtInt(butter.stores)}`;
      document.getElementById('kpi-price').textContent = `均价 ${fmtMoney2(butter.price)}`;
      document.getElementById('kpi-promo-dates').textContent = `${DATA.promo.promoStart.slice(5)} 至 ${DATA.promo.promoEnd.slice(5)}`;
      document.getElementById('kpi-psd-base').textContent = `基线 ${fmtDec(s.baselinePsdAssigned,3)}，推广期 ${fmtDec(s.promoPsdAssigned,3)}`;
      document.getElementById('kpi-psd-delta').innerHTML = deltaHtml(s.promoPsdAssigned, s.baselinePsdAssigned);
    }

    function render() {
      renderKpis();
      chart('chart-qty').setOption(lineOption('qty','销量',false), true);
      chart('chart-sales').setOption(lineOption('sales','销额(元)',true), true);
      chart('chart-price').setOption(lineOption('price','单价(元)',true), true);
      chart('chart-psd').setOption(psdOption(), true);
      chart('chart-mix').setOption(rankedOption(DATA.latestMix, 'sales', true), true);
      chart('chart-tier').setOption(tierOption(), true);
      chart('chart-promo-compare').setOption(promoCompareOption(), true);
      chart('chart-vertical').setOption(verticalOption(), true);
      chart('chart-promo-tier').setOption(promoTierOption(), true);
      chart('chart-period-tier').setOption(periodTierOption(), true);
      chart('chart-opportunity').setOption(rankedOption(DATA.opportunity, 'qty', false), true);
      renderTables();
    }

    document.getElementById('meta').textContent = `数据区间 ${DATA.meta.dataStart} 至 ${DATA.meta.dataEnd} | 最近完整周 ${DATA.meta.lastCompleteWeek} | 生成于 ${DATA.meta.generatedAt}`;
    document.getElementById('last-week').textContent = `${DATA.lastWeek.start} 至 ${DATA.lastWeek.end}`;
    document.getElementById('footnote').textContent = `说明：${DATA.meta.missingDates.length ? DATA.meta.missingDates.slice(0,6).join('、') + ' 等日期' : '无日期'}源表无记录，不纳入周度 PSD；8月10日至8月16日因当前源表未满7天也已剔除。单价为最终销额除以销量，不等于标价。推广门店来自飞书“永辉活动门店”清单，共 ${DATA.promo.promoStoreCount} 家；推广资源期按补充信息固定为 ${DATA.promo.promoStart} 至 ${DATA.promo.promoEnd}。`;
    renderMonthFilters();
    render();
    window.addEventListener('resize', () => Object.values(chartInstances).forEach(c => c.resize()));
  </script>
</body>
</html>
'''


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source workbook: {SOURCE}")
    data = build_data()
    html = HTML_TEMPLATE.replace("__NAV__", nav_block("yonghui")).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"Built {OUT.name}")
    write_standalone(html)
    patch_existing_drf_nav()


if __name__ == "__main__":
    main()
