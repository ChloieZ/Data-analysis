"""把 DuckDB 三层数据导出为 SQLite，供 Metabase（原生支持 SQLite）自助分析使用。

产出 data/spend_mart.sqlite，包含：
    raw_spending / dwd_spending / dws_monthly_category   —— 三层原始数据
    mart_monthly_total     —— 月度总支出（趋势）
    mart_category_share    —— 月 × 类别占比
    mart_category_mom      —— 月 × 类别环比

用法：
    python -m spend_analytics.cli export
    python scripts/export_sqlite.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

from spend_analytics import config, db  # noqa: E402

_MART_SQL = {
    "mart_monthly_total": """
        SELECT month,
               round(sum(total_amount), 2) AS total_amount,
               sum(order_count)            AS order_count,
               CASE WHEN sum(order_count) > 0
                    THEN round(sum(total_amount) / sum(order_count), 2)
                    ELSE 0 END             AS avg_per_order
        FROM dws_monthly_category GROUP BY month ORDER BY month
    """,
    "mart_category_share": """
        SELECT month, category, total_amount, order_count,
               round(total_amount * 100.0 / sum(total_amount) OVER (PARTITION BY month), 2) AS share_pct
        FROM dws_monthly_category ORDER BY month, total_amount DESC
    """,
    "mart_category_mom": """
        WITH t AS (SELECT month, category, total_amount FROM dws_monthly_category)
        SELECT cur.month, cur.category,
               coalesce(prev.total_amount, 0)  AS prev_amount,
               cur.total_amount                AS current_amount,
               round(cur.total_amount - coalesce(prev.total_amount, 0), 2) AS delta
        FROM t cur
        LEFT JOIN t prev
          ON prev.month = strftime(
                (CAST(cur.month || '-01' AS DATE) - INTERVAL 1 MONTH), '%Y-%m')
         AND prev.category = cur.category
        ORDER BY cur.month, abs(cur.total_amount - coalesce(prev.total_amount, 0)) DESC
    """,
}


def export_all(con=None, path: str | Path | None = None) -> dict:
    """导出三层数据 + 三张 mart 表到 SQLite。"""
    path = Path(path) if path else config.SQLITE_PATH
    owns = con is None
    if owns:
        con = db.connect()
        db.init_schema(con)

    if path.exists():
        path.unlink()

    tables = {}
    scon = sqlite3.connect(str(path))
    try:
        for table in (config.RAW_TABLE, config.DWD_TABLE, config.DWS_TABLE):
            df = con.execute(f"SELECT * FROM {table}").df()
            df.to_sql(table, scon, index=False, if_exists="replace")
            tables[table] = len(df)
        for name, sql in _MART_SQL.items():
            df = con.execute(sql).df()
            df.to_sql(name, scon, index=False, if_exists="replace")
            tables[name] = len(df)
        scon.commit()
    finally:
        scon.close()
        if owns:
            con.close()

    return {"sqlite": str(path), "tables": tables}


if __name__ == "__main__":
    info = export_all()
    print("已导出到:", info["sqlite"])
    for t, n in info["tables"].items():
        print(f"  - {t}: {n} 行")
