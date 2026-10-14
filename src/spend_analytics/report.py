"""固定报表：把指标与查询组装成终端场景所需的数据结构。

场景 -> 报表：
    月度复盘 -> dashboard 指标卡
    分类分析 -> category_share（饼图）
    趋势观察 -> trend（折线图）
    环比对比 -> category_mom（按月+类别交叉表）
    明细追溯 -> detail（明细表）
"""
from __future__ import annotations

from . import metrics, query


def category_mom(con, month: str) -> dict:
    """本月 vs 上月的分类对比表。"""
    prev = metrics._prev_month(month)
    cur = {r["category"]: r["total_amount"] for r in metrics.category_spend(con, month)}
    old = {r["category"]: r["total_amount"] for r in metrics.category_spend(con, prev)}
    rows = []
    for cat in sorted(set(cur) | set(old)):
        c, o = cur.get(cat, 0.0), old.get(cat, 0.0)
        delta = round(c - o, 2)
        rows.append({
            "category": cat,
            "prev_amount": o,
            "current_amount": c,
            "delta": delta,
            "pct": round(delta / o * 100, 2) if o else None,
        })
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {"month": month, "prev_month": prev, "rows": rows}


def trend(con) -> list[dict]:
    """月度趋势序列。"""
    return metrics.monthly_totals(con)


def dashboard(con, month: str | None = None) -> dict:
    """一次性返回看板所需全部数据。"""
    months = metrics.list_months(con)
    if not months:
        return {"empty": True, "months": [], "month": None, "cards": None,
                "category_share": [], "trend": [], "category_mom": None,
                "categories": []}
    month = month if month in months else months[-1]
    return {
        "empty": False,
        "months": months,
        "month": month,
        "cards": metrics.summary(con, month),
        "category_share": metrics.category_share(con, month),
        "trend": trend(con),
        "category_mom": category_mom(con, month),
        "categories": metrics.list_categories(con),
    }


def detail(con, **kwargs):
    return query.detail(con, **kwargs)
