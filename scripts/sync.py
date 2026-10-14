"""手动触发数据重新同步：导入 data/input 下所有表格 + 重跑 ETL。

用法：
    python scripts/sync.py                # 导入 data/input 全部文件（追加模式）
    python scripts/sync.py --mode replace # 用文件内容替换对应月份的旧数据
    python scripts/sync.py --file 某月.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

from spend_analytics import db, etl, ingest  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="手动同步花销数据")
    ap.add_argument("--file", default=None, help="导入单个文件（默认导入 data/input 全部）")
    ap.add_argument("--mode", choices=["append", "replace"], default="append")
    args = ap.parse_args()

    con = db.connect()
    db.init_schema(con)

    if args.file:
        ing = [ingest.ingest_file(con, args.file, mode=args.mode)]
    else:
        ing = ingest.ingest_directory(con, mode=args.mode)

    print("== 数据接入 ==")
    for r in ing:
        print(f"  {r['file']}: 读取 {r['total_read']} 行, 写入 {r['inserted']} 行, "
              f"跳过 {r['skipped']} 行（文件内重复 {r['skipped_duplicate_in_file']}, "
              f"库中已存在 {r['skipped_already_exists']}）, 删除旧数据 {r['removed']} 行")

    stats = etl.run_etl(con)
    print("== ETL ==")
    print(f"  原始层 {stats['raw_total']} 行")
    print(f"  过滤：非法日期 {stats['dropped_invalid_date']}, "
          f"非法金额 {stats['dropped_invalid_amount']}, "
          f"非正金额(含退款) {stats['dropped_non_positive_amount']}, "
          f"空类别 {stats['dropped_empty_category']}")
    print(f"  明细层 {stats['dwd_count']} 行（{stats['months']} 个月, {stats['categories']} 个类别）")
    print(f"  汇总层 {stats['dws_count']} 行")
    print("同步完成。")


if __name__ == "__main__":
    main()
