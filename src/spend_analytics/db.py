"""DuckDB 连接管理与表结构定义。

数据流向：
    Excel/CSV -> raw_spending -> dwd_spending -> dws_monthly_category
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import config

# ---------------------------------------------------------------------------
# 建表 DDL（字段与需求 4.1 保持一致，原始层沿用中文列名）
# ---------------------------------------------------------------------------
DDL = [
    # 原始层：原样落地，全部 VARCHAR，保留脏数据痕迹便于排查
    f"""
    CREATE TABLE IF NOT EXISTS {config.RAW_TABLE} (
        "日期"     VARCHAR,
        "类别"     VARCHAR,
        "金额"     VARCHAR,
        "备注"     VARCHAR,
        "_源文件"   VARCHAR,
        "_导入时间" TIMESTAMP
    )
    """,
    # 明细层：清洗后的逐笔有效记录
    f"""
    CREATE TABLE IF NOT EXISTS {config.DWD_TABLE} (
        spend_date DATE,
        month      VARCHAR,
        category   VARCHAR,
        amount     DOUBLE,
        note       VARCHAR
    )
    """,
    # 汇总层：月 × 类别 聚合，供自助分析与加速查询命中
    f"""
    CREATE TABLE IF NOT EXISTS {config.DWS_TABLE} (
        month        VARCHAR,
        category     VARCHAR,
        total_amount DOUBLE,
        order_count  INTEGER
    )
    """,
]


def connect(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """打开（或创建）DuckDB 数据库连接。"""
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """初始化三张表（幂等）。"""
    for stmt in DDL:
        con.execute(stmt)


def reset_all(con: duckdb.DuckDBPyConnection) -> None:
    """清空全部数据层（保留表结构）。"""
    for table in (config.RAW_TABLE, config.DWD_TABLE, config.DWS_TABLE):
        con.execute(f"DELETE FROM {table}")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """返回各层记录数，用于校验。"""
    out = {}
    for table in (config.RAW_TABLE, config.DWD_TABLE, config.DWS_TABLE):
        out[table] = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    return out
