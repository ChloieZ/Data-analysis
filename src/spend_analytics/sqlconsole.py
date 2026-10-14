"""SQL 工作台：在 DuckDB 上执行用户输入的 SQL（建表 / 查询 / 预览）。

供 Web 的「SQL 工作台」页面使用，也便于命令行与测试复用。
"""
from __future__ import annotations

import datetime as _dt
import re
import time
from decimal import Decimal

# 单次查询最多返回的行数（避免把大结果集塞进前端）
DEFAULT_LIMIT = 500


def split_statements(sql: str) -> list[str]:
    """按顶层分号拆分多条语句，忽略引号内的分号与 -- 行注释。"""
    stmts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == quote:          # 简单处理转义：'' / "" 会自然闭合再开启
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                break
            i = j
            buf.append("\n")
            i += 1
            continue
        elif ch == ";":
            stmts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s]


def quote_ident(name: str) -> str:
    """安全地把表名包成标识符。"""
    return '"' + str(name).replace('"', '""') + '"'


def _cell(value):
    """把 DuckDB 返回的值转成可 JSON 序列化的形式。"""
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


def is_query(stmt: str) -> bool:
    """按首个关键字判断语句是否返回结果集（DuckDB 对 CTAS 也会返回 Count 结果集，
    因此不能只看 cur.description）。"""
    head = stmt.lstrip().split(None, 1)[0].lower().strip("();")
    return head in {"select", "with", "show", "describe", "desc", "explain",
                    "pragma", "summarize", "values", "from", "table"}


# SQL 工作台的语句白名单
#   READONLY_HEADS —— 纯查询（导出接口也用它）
#   DDL_HEADS      —— 建表 / 建视图
#   CONSOLE_HEADS  —— 工作台默认允许：查询 + 建表
READONLY_HEADS = {"select", "with", "show", "describe", "desc", "explain",
                  "summarize", "pragma", "values", "from", "table"}
DDL_HEADS = {"create"}
CONSOLE_HEADS = READONLY_HEADS | DDL_HEADS


class StatementNotAllowed(ValueError):
    """语句不在允许范围内。"""


def assert_allowed(stmt: str, allowed: set[str] = CONSOLE_HEADS) -> None:
    """校验单条语句的首关键字在 allowed 内，否则抛 StatementNotAllowed。"""
    head = stmt.lstrip().split(None, 1)[0].lower().strip("();") if stmt.strip() else ""
    if head not in allowed:
        raise StatementNotAllowed(
            f"该语句不被允许（{head.upper() or '空语句'}）；"
            f"仅支持：{'、'.join(sorted(h.upper() for h in allowed))}"
        )


def run_checked(con, sql: str, limit: int = DEFAULT_LIMIT,
                allowed: set[str] = CONSOLE_HEADS) -> dict:
    """按白名单执行：默认允许 SELECT 查询与 CREATE 建表，改数/删表（UPDATE/DELETE/DROP）拒绝。"""
    statements = split_statements(sql)
    if not statements:
        raise ValueError("SQL 为空")
    for stmt in statements:
        assert_allowed(stmt, allowed)
    return run_sql(con, sql, limit)


def result_to_csv(columns: list[str], rows: list[list]) -> str:
    """把一次查询结果转成 CSV 文本。"""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue()


# 表名白名单：中英文 / 数字 / 下划线，不能以数字开头
_IDENT_RE = re.compile(r"^[A-Za-z_\u4e00-\u9fa5][A-Za-z0-9_\u4e00-\u9fa5]{0,63}$")


def validate_table_name(name: str) -> str:
    name = (name or "").strip()
    if not _IDENT_RE.match(name):
        raise ValueError("表名不合法：仅支持中英文、数字、下划线，且不以数字开头（≤64 字符）")
    return name


def save_as_table(con, name: str, sql: str, replace: bool = True) -> dict:
    """把一条 SELECT 查询的结果保存为库内表（CREATE TABLE AS SELECT）。

    - 只接受单条只读查询（SELECT / WITH）；
    - replace=True 时用 CREATE OR REPLACE，同名表会被覆盖。
    """
    table = validate_table_name(name)
    statements = split_statements(sql)
    if not statements:
        raise ValueError("SQL 为空")
    if len(statements) > 1:
        raise ValueError("保存为表只接受单条 SELECT 查询（当前有多条语句）")
    assert_allowed(statements[0], READONLY_HEADS)

    verb = "CREATE OR REPLACE TABLE" if replace else "CREATE TABLE"
    con.execute(f"{verb} {quote_ident(table)} AS {statements[0]}")
    rows = int(con.execute(f"SELECT count(*) FROM {quote_ident(table)}").fetchone()[0])
    return {"name": table, "rows": rows, "replaced": bool(replace)}


def run_sql(con, sql: str, limit: int = DEFAULT_LIMIT) -> dict:
    """执行 SQL（可多条），返回每条语句的结果。

    - 查询语句：返回 columns / rows（最多 limit 行）
    - 其他语句（DDL/DML）：返回影响行数
    """
    statements = split_statements(sql)
    if not statements:
        raise ValueError("SQL 为空")

    results = []
    started = time.perf_counter()
    for stmt in statements:
        cur = con.execute(stmt)
        if is_query(stmt):
            cols = [d[0] for d in (cur.description or [])]
            rows = [[_cell(v) for v in r] for r in cur.fetchmany(limit)]
            results.append({
                "type": "query", "sql": stmt, "columns": cols, "rows": rows,
                "row_count": len(rows), "truncated": len(rows) >= limit,
            })
        else:
            results.append({"type": "exec", "sql": stmt, "rowcount": affected(cur)})

    return {
        "results": results,
        "statement_count": len(statements),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def affected(cur) -> int | None:
    """取 DDL/DML 的影响行数（CTAS/INSERT..SELECT 会返回 Count 结果集）。"""
    if cur.description:
        try:
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:
            pass
    rc = getattr(cur, "rowcount", None)
    return rc if rc is not None and rc >= 0 else None


def list_tables(con) -> list[dict]:
    """列出 main schema 下的表及行数。"""
    names = [
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    ]
    out = []
    for name in names:
        try:
            cnt = int(con.execute(f"SELECT count(*) FROM {quote_ident(name)}").fetchone()[0])
        except Exception:
            cnt = None
        out.append({"name": name, "rows": cnt})
    return out


def preview_table(con, name: str, limit: int = 100) -> dict:
    """预览某张表的前若干行。"""
    if name not in {t["name"] for t in list_tables(con)}:
        raise ValueError(f"表不存在：{name}")
    cur = con.execute(f"SELECT * FROM {quote_ident(name)} LIMIT {int(limit)}")
    cols = [d[0] for d in cur.description]
    rows = [[_cell(v) for v in r] for r in cur.fetchall()]
    return {"name": name, "columns": cols, "rows": rows}
