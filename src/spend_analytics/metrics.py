"""指标管理：核心指标的口径定义与查询实现。

指标口径（详见 docs/指标口径.md）：
    月总支出   当月所有有效记录金额之和               SUM(amount) WHERE month = ?
    分类支出   当月某类别金额之和                     SUM(amount) GROUP BY category
    分类占比   分类支出 / 月总支出                    分类支出 / 月总支出
    环比变化   本月总支出 - 上月总支出                本月月总支出 - 上月月总支出
    笔均支出   月总支出 / 当月记录数                  SUM(amount) / COUNT(*)

口径约定：
    - “有效记录”指金额 > 0 且日期可解析；
    - 退款（负数）当前版本不计入支出；
    - 月份按自然月（YYYY-MM），不按滚动 30 天。
"""
from __future__ import annotations

from . import config

_DWS = config.DWS_TABLE
_DWD = config.DWD_TABLE

# 指标字典（供界面展示与文档生成）
METRIC_CATALOG = [
    {"key": "monthly_total", "name": "月总支出", "unit": "元",
     "formula": "SUM(amount) WHERE month = ?",
     "desc": "当月所有有效记录金额之和"},
    {"key": "category_spend", "name": "分类支出", "unit": "元",
     "formula": "SUM(amount) GROUP BY category",
     "desc": "当月某类别金额之和"},
    {"key": "category_share", "name": "分类占比", "unit": "%",
     "formula": "分类支出 / 月总支出",
     "desc": "某类别支出占当月总支出的比例"},
    {"key": "mom_change", "name": "环比变化", "unit": "元",
     "formula": "本月月总支出 - 上月月总支出",
     "desc": "本月总支出相对上月的增减额与百分比"},
    {"key": "avg_per_order", "name": "笔均支出", "unit": "元",
     "formula": "SUM(amount) / COUNT(*)",
     "desc": "月总支出除以当月有效记录笔数"},
]


def _df(con, sql, params=None):
    return con.execute(sql, params or []).df()


def list_months(con) -> list[str]:
    """返回所有有数据的月份（升序）。"""
    rows = con.execute(f"SELECT DISTINCT month FROM {_DWS} ORDER BY month").fetchall()
    return [r[0] for r in rows]


def list_categories(con) -> list[str]:
    rows = con.execute(f"SELECT DISTINCT category FROM {_DWS} ORDER BY category").fetchall()
    return [r[0] for r in rows]


def monthly_total(con, month: str) -> float:
    """月总支出。"""
    row = con.execute(
        f"SELECT round(coalesce(sum(total_amount), 0), 2) FROM {_DWS} WHERE month = ?",
        [month],
    ).fetchone()
    return float(row[0] or 0)


def category_spend(con, month: str) -> list[dict]:
    """分类支出明细（含笔数），按金额降序。"""
    df = _df(
        con,
        f"""SELECT category, total_amount, order_count
            FROM {_DWS} WHERE month = ? ORDER BY total_amount DESC""",
        [month],
    )
    return df.to_dict("records")


def category_share(con, month: str) -> list[dict]:
    """分类占比，返回 [{category, total_amount, order_count, share}]。"""
    rows = category_spend(con, month)
    total = sum(r["total_amount"] for r in rows) or 0.0
    for r in rows:
        r["share"] = round(r["total_amount"] / total * 100, 2) if total else 0.0
    return rows


def monthly_totals(con) -> list[dict]:
    """每个月总支出（用于趋势折线图）。"""
    df = _df(
        con,
        f"""SELECT month, round(sum(total_amount), 2) AS total_amount,
                   sum(order_count) AS order_count
            FROM {_DWS} GROUP BY month ORDER BY month""",
    )
    return df.to_dict("records")


def _prev_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"


def mom_change(con, month: str) -> dict:
    """环比变化：本月 vs 上月。"""
    current = monthly_total(con, month)
    prev_month = _prev_month(month)
    previous = monthly_total(con, prev_month)
    delta = round(current - previous, 2)
    pct = round(delta / previous * 100, 2) if previous else None
    return {
        "month": month,
        "current": current,
        "prev_month": prev_month,
        "previous": previous,
        "delta": delta,
        "pct": pct,
    }


def avg_per_order(con, month: str) -> float:
    """笔均支出。"""
    row = con.execute(
        f"""SELECT CASE WHEN sum(order_count) > 0
                        THEN round(sum(total_amount) / sum(order_count), 2)
                        ELSE 0 END
            FROM {_DWS} WHERE month = ?""",
        [month],
    ).fetchone()
    return float(row[0] or 0)


def summary(con, month: str) -> dict:
    """某月的指标卡数据。"""
    if not month:
        months = list_months(con)
        month = months[-1] if months else None
    if not month:
        return {"month": None, "monthly_total": 0.0, "order_count": 0,
                "avg_per_order": 0.0, "mom": None, "category_count": 0}
    order_count = int(
        con.execute(
            f"SELECT coalesce(sum(order_count), 0) FROM {_DWS} WHERE month = ?", [month]
        ).fetchone()[0]
    )
    return {
        "month": month,
        "monthly_total": monthly_total(con, month),
        "order_count": order_count,
        "avg_per_order": avg_per_order(con, month),
        "mom": mom_change(con, month),
        "category_count": len(category_spend(con, month)),
    }
