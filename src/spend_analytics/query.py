"""自助分析查询构造器：维度 × 度量 × 筛选。

维度（对应需求 3.2 自助分析）：
    月份 month / 类别 category / 星期 weekday / 备注关键词 note
度量：
    月总支出 total_amount / 笔数 order_count / 笔均支出 avg_amount
筛选：
    月份多选、类别多选、月份区间、备注关键词、最小金额
"""
from __future__ import annotations

from . import config

_DWD = config.DWD_TABLE

# 维度白名单：expr 为分组表达式，order 决定排序
DIMENSIONS = {
    "year": {
        "label": "年份",
        "expr": "substr(month, 1, 4)",
        "order": "dimension",
    },
    "quarter": {
        "label": "季度",
        "expr": "substr(month, 1, 4) || '-Q' || cast(quarter(spend_date) AS VARCHAR)",
        "order": "dimension",
    },
    "month": {
        "label": "月份",
        "expr": "month",
        "order": "dimension",
    },
    "day": {
        "label": "日期",
        "expr": "strftime(spend_date, '%Y-%m-%d')",
        "order": "dimension",
    },
    "weekday": {
        "label": "星期",
        "expr": """CASE dayofweek(spend_date)
                     WHEN 0 THEN '周日' WHEN 1 THEN '周一' WHEN 2 THEN '周二'
                     WHEN 3 THEN '周三' WHEN 4 THEN '周四' WHEN 5 THEN '周五'
                     ELSE '周六' END""",
        "order": "_ord",
        "extra": "min(dayofweek(spend_date)) AS _ord",
    },
    "category": {
        "label": "类别",
        "expr": "category",
        "order": "measure DESC",
    },
    "amount_band": {
        "label": "金额区间",
        "expr": """CASE WHEN amount < 50 THEN '＜50'
                        WHEN amount < 100 THEN '50~100'
                        WHEN amount < 500 THEN '100~500'
                        WHEN amount < 1000 THEN '500~1000'
                        ELSE '≥1000' END""",
        "order": "_ord",
        "extra": "min(amount) AS _ord",
    },
    "note": {
        "label": "备注关键词",
        "expr": "coalesce(nullif(note, ''), '（无备注）')",
        "order": "measure DESC",
    },
}

# 度量白名单
MEASURES = {
    "total_amount": {"label": "总支出", "sql": "round(sum(amount), 2)", "unit": "元"},
    "order_count": {"label": "笔数", "sql": "count(*)", "unit": "笔"},
    "avg_amount": {"label": "笔均支出", "sql": "round(avg(amount), 2)", "unit": "元"},
    "max_amount": {"label": "最大单笔", "sql": "round(max(amount), 2)", "unit": "元"},
    "min_amount": {"label": "最小单笔", "sql": "round(min(amount), 2)", "unit": "元"},
    "median_amount": {"label": "单笔中位数", "sql": "round(median(amount), 2)", "unit": "元"},
    "active_days": {"label": "消费天数", "sql": "count(distinct spend_date)", "unit": "天"},
}


class QueryError(ValueError):
    pass


def meta() -> dict:
    """返回可用的维度/度量清单，供前端渲染拖拽项。"""
    return {
        "dimensions": [{"key": k, "label": v["label"]} for k, v in DIMENSIONS.items()],
        "measures": [{"key": k, "label": v["label"], "unit": v["unit"]} for k, v in MEASURES.items()],
    }


def _build_filters(years=None, months=None, categories=None, month_from=None,
                   month_to=None, note_kw=None, min_amount=None, max_amount=None):
    clauses, params = [], []
    if years:                                 # 年份多选（留空 = 全部年份）
        clauses.append(f"substr(month, 1, 4) IN ({', '.join(['?'] * len(years))})")
        params.extend(years)
    if months:
        clauses.append(f"month IN ({', '.join(['?'] * len(months))})")
        params.extend(months)
    if categories:
        clauses.append(f"category IN ({', '.join(['?'] * len(categories))})")
        params.extend(categories)
    if month_from:
        clauses.append("month >= ?")
        params.append(month_from)
    if month_to:
        clauses.append("month <= ?")
        params.append(month_to)
    if note_kw:
        clauses.append("note ILIKE ?")
        params.append(f"%{note_kw}%")
    if min_amount is not None:
        clauses.append("amount >= ?")
        params.append(float(min_amount))
    if max_amount is not None:
        clauses.append("amount <= ?")
        params.append(float(max_amount))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def chart_data(con, dimension: str, measure: str, *, years=None, months=None, categories=None,
               month_from=None, month_to=None, note_kw=None,
               min_amount=None, max_amount=None, limit: int = 100) -> dict:
    """按维度聚合度量，返回 [{dimension, measure}]。"""
    if dimension not in DIMENSIONS:
        raise QueryError(f"未知维度：{dimension}")
    if measure not in MEASURES:
        raise QueryError(f"未知度量：{measure}")

    dim = DIMENSIONS[dimension]
    extra = (dim.get("extra") + ", ") if dim.get("extra") else ""
    where, params = _build_filters(years, months, categories, month_from, month_to,
                                   note_kw, min_amount, max_amount)
    order = dim["order"].replace("measure", "measure")
    sql = f"""
        SELECT {extra}{dim['expr']} AS dimension,
               {MEASURES[measure]['sql']} AS measure
        FROM {_DWD}
        {where}
        GROUP BY dimension
        ORDER BY {order}
        LIMIT {int(limit)}
    """
    df = con.execute(sql, params).df()
    rows = df[["dimension", "measure"]].to_dict("records")
    return {
        "dimension": dimension,
        "dimension_label": dim["label"],
        "measure": measure,
        "measure_label": MEASURES[measure]["label"],
        "unit": MEASURES[measure]["unit"],
        "rows": rows,
        "total": round(sum(r["measure"] or 0 for r in rows), 2),
    }


def crosstab(con, *, years=None, months=None, categories=None, measure: str = "total_amount",
             month_from=None, month_to=None, note_kw=None) -> dict:
    """月份 × 类别 交叉表（环比对比场景）。"""
    if measure not in MEASURES:
        raise QueryError(f"未知度量：{measure}")
    where, params = _build_filters(years, months, categories, month_from, month_to, note_kw)
    sql = f"""
        SELECT month, category, {MEASURES[measure]['sql']} AS value
        FROM {_DWD} {where}
        GROUP BY month, category
        ORDER BY month, category
    """
    df = con.execute(sql, params).df()
    cols = sorted(df["category"].unique().tolist()) if len(df) else []
    rows = []
    for month, grp in df.groupby("month", sort=True):
        row = {"month": month}
        for c in cols:
            row[c] = 0.0
        for _, r in grp.iterrows():
            row[r["category"]] = r["value"]
        row["_total"] = round(sum(row[c] for c in cols), 2)
        rows.append(row)
    return {
        "measure": measure,
        "measure_label": MEASURES[measure]["label"],
        "columns": cols,
        "rows": rows,
    }


def detail(con, *, years=None, months=None, categories=None, month_from=None, month_to=None,
           note_kw=None, min_amount=None, max_amount=None, limit: int = 200) -> list[dict]:
    """明细查询：筛选逐笔记录。"""
    where, params = _build_filters(years, months, categories, month_from, month_to,
                                   note_kw, min_amount, max_amount)
    sql = f"""
        SELECT strftime(spend_date, '%Y-%m-%d') AS spend_date, month, category,
               round(amount, 2) AS amount, note
        FROM {_DWD} {where}
        ORDER BY spend_date DESC, amount DESC
        LIMIT {int(limit)}
    """
    return con.execute(sql, params).df().to_dict("records")
