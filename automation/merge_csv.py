"""
将永辉导出的CSV门店明细合并到 latest.xlsx 的永辉sheet中。
用法: python merge_csv.py <csv_path>
会自动:
  - 去重(同日期+门店编码+商品编码)
  - 填充 渠道名称/月别/周别/当周天数
  - 保留其他sheet不变
"""
import sys, os
import pandas as pd
from openpyxl import load_workbook
from datetime import date

XLSX = r"C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\feishu-long-term-sync\data\latest.xlsx"

# Week mapping: date -> (月别, 周别, 当周天数)
# Week starts Monday
def get_week_info(d):
    month = f"{d.month}月"
    # Monday of that week
    monday = d - pd.Timedelta(days=d.weekday())
    # Week number within month: count Mondays from start of month
    first_day = pd.Timestamp(d.year, d.month, 1)
    first_monday = first_day - pd.Timedelta(days=first_day.weekday())
    if first_monday < first_day - pd.Timedelta(days=first_day.weekday()):
        first_monday = first_monday + pd.Timedelta(days=7)
    week_num = ((monday - first_monday).days // 7) + 1
    if week_num < 1:
        week_num = 1
    # Days in that week within this month
    week_start = monday
    week_end = monday + pd.Timedelta(days=6)
    month_start = pd.Timestamp(d.year, d.month, 1)
    if d.month == 12:
        month_end = pd.Timestamp(d.year, 12, 31)
    else:
        month_end = pd.Timestamp(d.year, d.month + 1, 1) - pd.Timedelta(days=1)
    overlap_start = max(week_start, month_start)
    overlap_end = min(week_end, month_end)
    days_in_month = (overlap_end - overlap_start).days + 1
    return month, f"{week_num}周", days_in_month


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else r"downloads\永辉20260818_01.csv"
    print(f"Reading CSV: {csv_path}")
    csv = pd.read_csv(csv_path)
    print(f"  {len(csv)} rows, date={csv['日期'].unique()}, stores={csv['门店编码'].nunique()}")

    # Read existing yonghui sheet
    print("Reading existing xlsx sheet 1...")
    existing = pd.read_excel(XLSX, sheet_name=1)
    existing.columns = [str(c).strip() for c in existing.columns]
    print(f"  {len(existing)} existing rows, date range: {existing['日期'].min()} to {existing['日期'].max()}")

    # Transform CSV to match xlsx columns
    csv["日期"] = pd.to_datetime(csv["日期"])
    rows = []
    for _, r in csv.iterrows():
        d = r["日期"]
        month, week, days = get_week_info(d)
        rows.append({
            "渠道名称": "永辉",
            "月别": month,
            "周别": week,
            "当周天数": days,
            "商品编码": int(r["商品编码"]),
            "商品条码": int(r["商品条码"]),
            "商品名称": str(r["商品名称"]).strip(),
            "门店编码": str(r["门店编码"]).strip(),
            "门店名称": str(r["门店名称"]).strip(),
            "品牌名称": str(r["品牌名称"]).strip(),
            "日期": d,
            "销售数量": float(r["销售数量"]),
            "销售金额": float(r["销售金额"]),
            "促销扣款": float(r["促销扣款"]),
            "优惠券金额": float(r["优惠券金额"]),
            "最终销售金额(销售金额+优惠券金额)": float(r["最终销售金额(销售金额+优惠券金额)"]),
            "推广促销": None,
        })
    new_df = pd.DataFrame(rows)
    print(f"  Transformed {len(new_df)} new rows")

    # Check for duplicates with existing data (same date + store + product)
    existing["日期"] = pd.to_datetime(existing["日期"])
    existing["门店编码"] = existing["门店编码"].astype(str).str.strip()
    new_df["门店编码"] = new_df["门店编码"].astype(str).str.strip()
    merge_keys = ["日期", "门店编码", "商品编码"]
    dup = new_df.merge(existing[merge_keys], on=merge_keys, how="inner")
    if len(dup) > 0:
        print(f"  WARNING: {len(dup)} duplicate rows found, removing from new data")
        new_df = new_df[~new_df.set_index(merge_keys).index.isin(dup.set_index(merge_keys).index)]

    if len(new_df) == 0:
        print("No new rows to add.")
        return

    # Append using openpyxl to preserve other sheets
    print(f"Appending {len(new_df)} rows to xlsx...")
    wb = load_workbook(XLSX)
    ws = wb.worksheets[1]  # sheet index 1 = Yonghui

    # Get column order from header
    headers = [cell.value for cell in ws[1]]
    col_map = {h: i+1 for i, h in enumerate(headers)}

    start_row = ws.max_row + 1
    for idx, (_, r) in enumerate(new_df.iterrows()):
        for h in headers:
            if h in r.index:
                val = r[h]
                if pd.isna(val):
                    val = None
                elif h == "日期":
                    val = val.to_pydatetime() if hasattr(val, "to_pydatetime") else val
                ws.cell(row=start_row + idx, column=col_map[h], value=val)

    wb.save(XLSX)
    wb.close()
    print(f"Saved. New max row: {start_row + len(new_df) - 1}")

    # Verify
    verify = pd.read_excel(XLSX, sheet_name=1)
    verify["日期"] = pd.to_datetime(verify["日期"])
    print(f"\nVerification: {len(verify)} total rows")
    new_date = new_df["日期"].iloc[0]
    day_rows = verify[verify["日期"] == new_date]
    print(f"  {new_date.strftime('%Y-%m-%d')}: {len(day_rows)} rows, {day_rows['门店编码'].nunique()} stores")
    print(f"  Products: {day_rows['商品名称'].unique()}")

if __name__ == "__main__":
    main()
