"""SQL 工作台核心逻辑测试（纯函数，不起 Web）。"""
from __future__ import annotations

import pytest

from spend_analytics import db, sqlconsole


@pytest.fixture()
def con(tmp_path):
    c = db.connect(tmp_path / "sql.duckdb")
    db.init_schema(c)
    c.execute("INSERT INTO dwd_spending VALUES "
              "('2025-01-01','2025-01','餐饮',10.5,'午餐'),"
              "('2025-01-02','2025-01','交通',20,'地铁'),"
              "('2025-02-01','2025-02','餐饮',5,'早餐')")
    yield c
    c.close()


def test_split_statements_basic():
    assert sqlconsole.split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]
    assert sqlconsole.split_statements("SELECT 1;") == ["SELECT 1"]
    assert sqlconsole.split_statements("  ") == []


def test_split_statements_ignores_quotes_and_comments():
    sql = "SELECT ';' AS a; -- 注释里的 ;\nSELECT 2"
    assert sqlconsole.split_statements(sql) == ["SELECT ';' AS a", "SELECT 2"]


def test_quote_ident_escapes():
    assert sqlconsole.quote_ident('a"b') == '"a""b"'


def test_run_sql_query(con):
    d = sqlconsole.run_sql(con, "SELECT category, amount FROM dwd_spending ORDER BY amount DESC")
    assert d["results"][0]["columns"] == ["category", "amount"]
    assert d["results"][0]["rows"][0] == ["交通", 20.0]
    assert d["statement_count"] == 1


def test_run_sql_ddl_and_limit(con):
    d = sqlconsole.run_sql(con, "CREATE TABLE t AS SELECT * FROM dwd_spending")
    assert d["results"][0]["type"] == "exec"

    d2 = sqlconsole.run_sql(con, "SELECT * FROM dwd_spending", limit=2)
    assert d2["results"][0]["row_count"] == 2 and d2["results"][0]["truncated"] is True


def test_run_sql_empty_raises(con):
    with pytest.raises(ValueError):
        sqlconsole.run_sql(con, "  -- nothing\n")


def test_run_checked_allows_select_and_create(con):
    d = sqlconsole.run_checked(con, "SELECT count(*) AS n FROM dwd_spending")
    assert d["results"][0]["type"] == "query"
    assert d["results"][0]["rows"][0][0] == 3
    # 建表（DDL）允许
    d2 = sqlconsole.run_checked(con, "CREATE OR REPLACE TABLE my_monthly AS SELECT month FROM dws_monthly_category")
    assert d2["results"][0]["type"] == "exec"
    assert "my_monthly" in [t["name"] for t in sqlconsole.list_tables(con)]
    # WITH（CTE）也属于只读查询
    d3 = sqlconsole.run_checked(con, "WITH t AS (SELECT 1 AS x) SELECT * FROM t")
    assert d3["results"][0]["rows"][0][0] == 1


def test_run_checked_rejects_destructive(con):
    for bad in ("INSERT INTO dwd_spending VALUES ('2025-03-01','2025-03','餐饮',1,'')",
                "UPDATE dwd_spending SET amount = 0",
                "DELETE FROM dwd_spending",
                "DROP TABLE dwd_spending",
                "ALTER TABLE dwd_spending ADD COLUMN x INTEGER"):
        with pytest.raises(sqlconsole.StatementNotAllowed):
            sqlconsole.run_checked(con, bad)
    # 多语句里夹带删表同样拒绝
    with pytest.raises(sqlconsole.StatementNotAllowed):
        sqlconsole.run_checked(con, "SELECT 1; DROP TABLE dwd_spending")
    assert "dwd_spending" in [t["name"] for t in sqlconsole.list_tables(con)]


def test_run_checked_readonly_policy_for_export(con):
    # 导出走严格只读白名单：连 CREATE 也被拒
    with pytest.raises(sqlconsole.StatementNotAllowed):
        sqlconsole.run_checked(con, "CREATE TABLE t3 AS SELECT 1",
                               allowed=sqlconsole.READONLY_HEADS)


def test_result_to_csv():
    csv_text = sqlconsole.result_to_csv(["a", "b"], [[1, "x"], [2, "y"]])
    lines = csv_text.splitlines()
    assert lines[0] == "a,b"
    assert "1,x" in lines and "2,y" in lines


# --------------------------- 保存为表 ---------------------------
def test_save_as_table(con):
    d = sqlconsole.save_as_table(
        con, "cat_sum",
        "SELECT category, round(sum(amount), 2) AS total FROM dwd_spending GROUP BY category")
    assert d["name"] == "cat_sum" and d["rows"] >= 1
    assert "cat_sum" in [t["name"] for t in sqlconsole.list_tables(con)]
    # 同名覆盖
    d2 = sqlconsole.save_as_table(con, "cat_sum", "SELECT 1 AS x")
    assert d2["rows"] == 1


def test_save_as_table_validations(con):
    for bad_name in ("1bad", "bad name", "a-b", ""):
        with pytest.raises(ValueError):
            sqlconsole.save_as_table(con, bad_name, "SELECT 1")
    with pytest.raises(ValueError):                 # 非查询语句
        sqlconsole.save_as_table(con, "t", "DROP TABLE dwd_spending")
    with pytest.raises(ValueError):                 # 多条语句
        sqlconsole.save_as_table(con, "t", "SELECT 1; SELECT 2")
    with pytest.raises(ValueError):                 # 空
        sqlconsole.save_as_table(con, "t", "   ")
    assert "t" not in [x["name"] for x in sqlconsole.list_tables(con)]


def test_value_serialization(con):
    con.execute("CREATE TABLE typed AS SELECT DATE '2025-03-01' AS d, 1.5::DECIMAL(6,2) AS m")
    d = sqlconsole.run_sql(con, "SELECT * FROM typed")
    cols = d["results"][0]["columns"]
    rows = d["results"][0]["rows"]
    assert cols == ["d", "m"]
    assert rows[0][0] == "2025-03-01"          # date -> ISO 字符串
    assert isinstance(rows[0][1], float)       # Decimal -> float


def test_list_and_preview_tables(con):
    names = [t["name"] for t in sqlconsole.list_tables(con)]
    assert {"raw_spending", "dwd_spending", "dws_monthly_category"} <= set(names)

    p = sqlconsole.preview_table(con, "dwd_spending", limit=2)
    assert p["columns"][0] == "spend_date" and len(p["rows"]) == 2

    with pytest.raises(ValueError):
        sqlconsole.preview_table(con, "missing")
