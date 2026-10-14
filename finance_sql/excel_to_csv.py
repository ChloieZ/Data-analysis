import pandas as pd
import re
from datetime import datetime, timedelta

EXCEL_FILE = "2024年个人收入支出表(1).xlsx"
OUTPUT_CSV = "records.csv"

EXCEL_EPOCH = datetime(1899, 12, 30)


def parse_date(raw, year=2024):
    """把各种奇怪的日期格式统一成 YYYY-MM-DD"""
    if pd.isna(raw):
        return None

    # datetime / Timestamp（Excel 里被识别为日期类型的单元格，如 '2023-02-01 00:00:00'）
    if isinstance(raw, (datetime, pd.Timestamp)):
        return pd.Timestamp(raw).strftime("%Y-%m-%d")

    # 数字类型
    if isinstance(raw, (int, float)):
        num = float(raw)
        # 情况1：Excel 日期序列号（45323 这种大数）
        if num > 1000:
            return (EXCEL_EPOCH + timedelta(days=int(num))).strftime("%Y-%m-%d")
        # 情况2：月.日（1.01 / 1.1 / 1.31）
        month = int(num)
        day = round((num - month) * 100)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"
        return None

    # 字符串类型
    s = str(raw).strip()

    # 已带完整日期的字符串（'2023-02-01' / '2023-02-01 00:00:00' / '2023/2/1 0:00'）
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{y:04d}-{month:02d}-{day:02d}"

    # '1.01' / '1.1' / '1.31'
    m = re.match(r"^(\d{1,2})\.(\d{1,2})$", s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"
        return None

    # 已经是日期字符串
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def process_sheet(df, year=2024):
    header_row = None
    for i in range(min(5, len(df))):
        if df.iloc[i].astype(str).str.contains("日期").any():
            header_row = i
            break

    if header_row is None:
        return pd.DataFrame()

    header = df.iloc[header_row].tolist()
    data = df.iloc[header_row + 1:].copy()
    data.columns = header

    date_col = header[0]
    category_cols = [c for c in header[1:] if pd.notna(c) and str(c).strip()]

    rows = []
    for _, row in data.iterrows():
        d = parse_date(row[date_col], year)
        if d is None:
            continue
        for cat in category_cols:
            val = row[cat]
            if pd.isna(val):
                continue
            try:
                amt = float(val)
            except (ValueError, TypeError):
                continue
            if amt == 0:
                continue
            rows.append({
                "date": d,
                "type": "expense",
                "category": str(cat).strip(),
                "amount": round(amt, 2),
            })
    return pd.DataFrame(rows)


def main():
    xls = pd.ExcelFile(EXCEL_FILE)
    all_rows = []

    for sheet in xls.sheet_names:
        print(f"处理 {sheet} ...")
        df = pd.read_excel(EXCEL_FILE, sheet_name=sheet, header=None)
        long_df = process_sheet(df)
        if not long_df.empty:
            all_rows.append(long_df)
            print(f"  -> {len(long_df)} 行")

    if not all_rows:
        print("没有解析到数据")
        return

    result = pd.concat(all_rows, ignore_index=True)
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n完成！共 {len(result)} 行，已写入 {OUTPUT_CSV}")


if __name__ == "__main__":
    main()