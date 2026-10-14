"""ETL：raw_spending -> dwd_spending -> dws_monthly_category。

转换规则（需求 3.2）：
    1. 日期 → 标准 DATE 类型（多格式兼容）
    2. 提取 month 字段，格式 YYYY-MM
    3. 过滤金额为空或 <= 0 的记录（退款负数不计入支出）
    4. 类别去空格、统一大写
    5. 过滤日期无法解析 / 类别为空的记录
加载：
    - dwd_spending          清洗后的逐笔记录
    - dws_monthly_category  按月份 + 类别聚合
"""
from __future__ import annotations

from . import config

_RAW = config.RAW_TABLE
_DWD = config.DWD_TABLE
_DWS = config.DWS_TABLE

# 金额清洗：去除货币符号、千分位、空格，再转 DOUBLE
_AMOUNT_EXPR = r"""try_cast(
        regexp_replace(trim(coalesce("金额", '')), '[^0-9.\-]', '', 'g')
    AS DOUBLE)"""

# 日期解析：逐格式尝试，全部失败则为 NULL
_DATE_EXPR = r"""coalesce(
        try_strptime(trim("日期"), '%Y-%m-%d')::DATE,
        try_strptime(trim("日期"), '%Y/%m/%d')::DATE,
        try_strptime(trim("日期"), '%Y.%m.%d')::DATE,
        try_strptime(trim("日期"), '%Y%m%d')::DATE,
        try_strptime(trim("日期"), '%Y年%m月%d日')::DATE,
        try_strptime(trim("日期"), '%Y-%m-%d %H:%M:%S')::DATE,
        try_strptime(trim("日期"), '%Y/%m/%d %H:%M:%S')::DATE,
        try_cast(trim("日期") AS DATE)
    )"""

_CATEGORY_EXPR = 'upper(trim(coalesce("类别", \'\')))'

# 对外暴露：其他模块（如数据接入的替换模式）复用同一套日期解析
DATE_EXPR = _DATE_EXPR
AMOUNT_EXPR = _AMOUNT_EXPR


def _scalar(con, sql: str) -> float:
    row = con.execute(sql).fetchone()
    return row[0] if row else 0


def build_dwd(con) -> int:
    """清洗并写入明细层，返回写入行数。"""
    con.execute(f"DELETE FROM {_DWD}")
    con.execute(
        f"""
        INSERT INTO {_DWD} (spend_date, month, category, amount, note)
        SELECT
            {_DATE_EXPR}                        AS spend_date,
            strftime({_DATE_EXPR}, '%Y-%m')     AS month,
            {_CATEGORY_EXPR}                    AS category,
            {_AMOUNT_EXPR}                      AS amount,
            trim(coalesce("备注", ''))          AS note
        FROM {_RAW}
        WHERE {_DATE_EXPR} IS NOT NULL
          AND {_AMOUNT_EXPR} IS NOT NULL
          AND {_AMOUNT_EXPR} > 0
          AND {_CATEGORY_EXPR} <> ''
        """
    )
    return int(_scalar(con, f"SELECT count(*) FROM {_DWD}"))


def build_dws(con) -> int:
    """聚合月 × 类别汇总层，返回写入行数。"""
    con.execute(f"DELETE FROM {_DWS}")
    con.execute(
        f"""
        INSERT INTO {_DWS} (month, category, total_amount, order_count)
        SELECT
            month,
            category,
            round(sum(amount), 2)   AS total_amount,
            count(*)::INTEGER       AS order_count
        FROM {_DWD}
        GROUP BY month, category
        ORDER BY month, total_amount DESC
        """
    )
    return int(_scalar(con, f"SELECT count(*) FROM {_DWS}"))


def run_etl(con) -> dict:
    """执行完整 ETL，返回统计与清洗明细。"""
    raw_total = int(_scalar(con, f"SELECT count(*) FROM {_RAW}"))
    invalid_date = int(
        _scalar(con, f"SELECT count(*) FROM {_RAW} WHERE {_DATE_EXPR} IS NULL")
    )
    invalid_amount = int(
        _scalar(
            con,
            f"SELECT count(*) FROM {_RAW} "
            f"WHERE {_DATE_EXPR} IS NOT NULL AND {_AMOUNT_EXPR} IS NULL",
        )
    )
    non_positive = int(
        _scalar(
            con,
            f"SELECT count(*) FROM {_RAW} "
            f"WHERE {_DATE_EXPR} IS NOT NULL AND {_AMOUNT_EXPR} IS NOT NULL "
            f"AND {_AMOUNT_EXPR} <= 0",
        )
    )
    empty_category = int(
        _scalar(
            con,
            f"SELECT count(*) FROM {_RAW} "
            f"WHERE {_DATE_EXPR} IS NOT NULL AND {_AMOUNT_EXPR} IS NOT NULL "
            f"AND {_AMOUNT_EXPR} > 0 AND {_CATEGORY_EXPR} = ''",
        )
    )

    dwd_count = build_dwd(con)
    dws_count = build_dws(con)

    return {
        "raw_total": raw_total,
        "dropped_invalid_date": invalid_date,
        "dropped_invalid_amount": invalid_amount,
        "dropped_non_positive_amount": non_positive,
        "dropped_empty_category": empty_category,
        "dropped_total": invalid_date + invalid_amount + non_positive + empty_category,
        "dwd_count": dwd_count,
        "dws_count": dws_count,
        "months": int(_scalar(con, f"SELECT count(DISTINCT month) FROM {_DWD}")),
        "categories": int(_scalar(con, f"SELECT count(DISTINCT category) FROM {_DWD}")),
    }
