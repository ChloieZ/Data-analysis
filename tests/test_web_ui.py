"""Web 层测试：三个页面的结构 + API 契约。

用临时 DuckDB 覆盖 app 的全局连接，避免依赖 data/spend.duckdb。
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from scripts.generate_sample_data import build_dataset
from spend_analytics import db, etl, ingest

PAGES = ("/", "/source", "/charts")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import web.app as appmod

    con = db.connect(tmp_path / "web.duckdb")
    db.init_schema(con)
    monkeypatch.setattr(appmod.config, "INPUT_DIR", tmp_path)

    seed = tmp_path / "seed.csv"
    build_dataset(["2025-01", "2025-02"], with_dirty=False).to_csv(
        seed, index=False, encoding="utf-8-sig")
    ingest.ingest_file(con, seed)
    etl.run_etl(con)

    appmod._con = con
    with TestClient(appmod.app) as c:
        yield c
    appmod._con = None
    con.close()


# --------------------------- 页面结构 ---------------------------
def test_all_pages_serve(client):
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "/static/app.css" in r.text


def test_nav_links_between_pages(client):
    for path in PAGES:
        html = client.get(path).text
        for target in PAGES:
            assert f'href="{target}"' in html, (path, target)


def test_dashboard_page_anchors(client):
    html = client.get("/").text
    for anchor in ('id="cards"', 'id="dimChips"', 'id="measChips"',
                   'id="chartTypes"', 'id="trendBox"', 'id="pieBox"',
                   'id="momBox"', 'id="detailBox"'):
        assert anchor in html, anchor
    # 大屏页不应该再混入上传 / SQL 编辑器
    assert 'id="dropZone"' not in html
    assert 'id="editor"' not in html


def test_source_page_has_upload_entry(client):
    """上传入口必须在「源数据」页（回归点）。"""
    html = client.get("/source").text
    for anchor in ('id="fileInput"', 'id="dropZone"', 'id="ingestMode"',
                   "上传花销表格", "上传并导入", "triggerEtl()"):
        assert anchor in html, anchor


def test_source_page_shows_file_list_and_preview(client):
    html = client.get("/source").text
    assert 'id="fileList"' in html and 'id="previewBox"' in html
    assert 'id="layerCards"' in html


def test_source_page_has_sql_append(client):
    """源数据页的 SQL 追加入口（回归点）。"""
    html = client.get("/source").text
    for anchor in ('id="appendSql"', 'id="appendDedup"', 'id="appendBtn"',
                   "SQL 追加", "appendBySql()"):
        assert anchor in html, anchor


def test_source_page_has_sql_workspace(client):
    """SQL 工作台已并入数据管理页（子标签）。"""
    html = client.get("/source").text
    for anchor in ('data-tab="files"', 'data-tab="sql"', "switchTab(",
                   'id="editor"', 'id="tableList"', 'id="resultBox"', 'id="runBtn"'):
        assert anchor in html, anchor


def test_sql_route_redirects_to_source(client):
    r = client.get("/sql", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/source"


def test_charts_page_anchors(client):
    html = client.get("/charts").text
    for anchor in ('id="metricLib"', 'id="canvas"', 'id="canvasDrop"',
                   'id="canvasEmpty"', 'id="dimChips"', 'id="measChips"',
                   'id="dimZone"', 'id="measZone"', 'id="chartTypes"',
                   "addCustomChart()", "内置指标"):
        assert anchor in html, anchor
    assert "/static/charts.js" in html


def test_charts_page_has_builtin_metrics(client):
    """内置指标清单与维度/度量定义一致（防止前后端漂移）。"""
    import re
    js = client.get("/static/charts.js").text
    metric_ids = re.findall(r'id:\s*"(m_[a-z_]+)"', js)
    assert len(metric_ids) >= 8
    meta = client.get("/api/meta").json()
    dims = {d["key"] for d in meta["dimensions"]}
    meas = {m["key"] for m in meta["measures"]}
    used_dims = set(re.findall(r'dimension:\s*"(\w+)"', js))
    used_meas = set(re.findall(r'measure:\s*"(\w+)"', js))
    assert used_dims <= dims, used_dims - dims
    assert used_meas <= meas, used_meas - meas


# --------------------------- 大屏 API ---------------------------
def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["tables"]["dwd_spending"] > 0

    m = client.get("/api/meta").json()
    assert {"month", "category", "weekday", "note"} <= {d["key"] for d in m["dimensions"]}
    assert {"total_amount", "order_count", "avg_amount"} <= {x["key"] for x in m["measures"]}
    assert m["months"] == ["2025-01", "2025-02"]


def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["empty"] is False
    assert d["month"] == "2025-02"
    assert d["cards"]["monthly_total"] > 0
    assert d["trend"] and d["category_share"]


def test_chart_and_filters(client):
    r = client.post("/api/chart", json={"dimension": "category", "measure": "total_amount"})
    assert r.status_code == 200 and r.json()["rows"]

    r = client.post("/api/chart", json={"dimension": "weekday", "measure": "order_count"})
    assert len(r.json()["rows"]) == 7

    r = client.post("/api/chart", json={"dimension": "nope", "measure": "total_amount"})
    assert r.status_code == 400


def test_crosstab_and_detail(client):
    ct = client.post("/api/crosstab", json={"months": ["2025-01"]}).json()
    assert ct["columns"] and ct["rows"][0]["month"] == "2025-01"

    d = client.post("/api/detail", json={"min_amount": 100, "limit": 10}).json()
    assert d["count"] and all(r["amount"] >= 100 for r in d["rows"])


# --------------------------- 源数据 API ---------------------------
def _upload(client, name, content, mode="append"):
    return client.post("/api/ingest", data={"mode": mode},
                       files={"file": (name, io.BytesIO(content), "text/csv")})


def test_upload_txt(client):
    r = _upload(client, "花销.txt", "日期,类别,金额\n2025-03-01,餐饮,12.5\n".encode("utf-8"))
    assert r.status_code == 200 and r.json()["ingest"]["inserted"] == 1


def test_upload_rejects_unknown_suffix(client):
    r = _upload(client, "a.doc", b"x")
    assert r.status_code == 400 and ".txt" in r.json()["detail"]


def _wide_xlsx_bytes():
    """内存里造一个「宽表」Excel（日期 + 各分类各占一列）。"""
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([["日期", "餐饮", "交通"], ["2025-03-01", 10, 5]]).to_excel(
            w, sheet_name="Jan", index=False, header=False)
    return buf.getvalue()


def test_source_parse_to_canonical_and_export(client):
    """宽表 Excel → 解析成规范四列 → 导出 CSV 数据文件。"""
    assert _upload(client, "wide.xlsx", _wide_xlsx_bytes()).status_code == 200

    d = client.post("/api/sources/parse", json={"name": "wide.xlsx"}).json()
    assert d["columns"] == ["日期", "类别", "金额", "备注"]
    assert d["total"] == 2 and d["amount_total"] == 15.0
    assert d["rows"][0] == ["2025-03-01", "餐饮", "10", ""]

    r = client.post("/api/sources/parse/export", json={"name": "wide.xlsx"})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert r.text.lstrip("\ufeff").splitlines()[0] == "日期,类别,金额,备注"

    assert client.post("/api/sources/parse", json={"name": "missing.xlsx"}).status_code == 404


# --------------------------- 年份维度 / 筛选 ---------------------------
def test_api_meta_exposes_years(client):
    d = client.get("/api/meta").json()
    assert d["years"] == ["2025"]                       # 种子数据是 2025-01/02
    assert {"key": "year", "label": "年份"} in d["dimensions"]


def test_api_chart_by_year_and_years_filter(client):
    y = client.post("/api/chart", json={"dimension": "year", "measure": "total_amount"}).json()
    assert [r["dimension"] for r in y["rows"]] == ["2025"]

    m = client.post("/api/chart", json={
        "dimension": "month", "measure": "total_amount", "years": ["2025"]}).json()
    assert len(m["rows"]) == 2                          # 2025-01 / 2025-02

    empty = client.post("/api/chart", json={
        "dimension": "month", "measure": "total_amount", "years": ["2024"]}).json()
    assert empty["rows"] == [] and empty["total"] == 0


def test_source_list_and_preview(client):
    files = client.get("/api/sources").json()["files"]
    assert [f["name"] for f in files] == ["seed.csv"]
    assert files[0]["rows"] > 0 and files[0]["error"] is None

    p = client.post("/api/sources/preview", json={"name": "seed.csv", "limit": 5}).json()
    assert p["columns"] == ["日期", "类别", "金额", "备注"]
    assert len(p["rows"]) == 5


def test_source_preview_rejects_traversal(client):
    r = client.post("/api/sources/preview", json={"name": "../../../etc/passwd"})
    assert r.status_code == 404


def test_source_delete(client):
    assert client.delete("/api/sources", params={"name": "seed.csv"}).status_code == 200
    assert client.get("/api/sources").json()["files"] == []


def test_upload_endpoint(client):
    body = _upload(client, "月度花销.csv",
                   b"date,category,amount,note\n2025-03-01,Food,12.5,lunch\n").json()
    assert body["ingest"]["inserted"] == 1
    assert body["etl"]["months"] == 3

    again = _upload(client, "月度花销.csv",
                    b"date,category,amount,note\n2025-03-01,Food,12.5,lunch\n").json()
    assert again["ingest"]["inserted"] == 0 and again["ingest"]["skipped"] == 1


def test_upload_rejects_bad_extension(client):
    r = _upload(client, "hack.exe", b"MZ")
    assert r.status_code == 400


def test_upload_rejects_bad_mode(client):
    r = _upload(client, "a.csv", b"date,category,amount,note\n2025-03-01,Food,1,x\n", mode="drop")
    assert r.status_code == 400


def test_etl_endpoint(client):
    body = client.post("/api/etl").json()
    assert body["dwd_count"] > 0 and body["dws_count"] > 0


# --------------------------- 源数据：SQL 追加 ---------------------------
_APPEND_SELECT = ("SELECT * FROM (VALUES ('2025-03-01','餐饮',38.5,'午餐'),"
                  "('2025-03-02','交通',12.0,'地铁')) AS t(日期,类别,金额,备注)")


def test_sql_append_select_endpoint(client):
    before = client.get("/api/health").json()["tables"]["dwd_spending"]
    body = client.post("/api/append/sql", json={"sql": _APPEND_SELECT, "dedup": True}).json()
    assert body["append"]["form"] == "select"
    assert body["append"]["inserted"] == 2
    assert body["etl"]["dwd_count"] == before + 2
    # 幂等：再来一次全部跳过
    again = client.post("/api/append/sql", json={"sql": _APPEND_SELECT, "dedup": True}).json()
    assert again["append"]["inserted"] == 0 and again["append"]["skipped_already_exists"] == 2


def test_sql_append_insert_statement_endpoint(client):
    body = client.post("/api/append/sql", json={
        "sql": 'INSERT INTO raw_spending ("日期","类别","金额","备注") '
               "VALUES ('2025-04-01','购物',99.9,'日用品')",
        "dedup": True,
    }).json()
    assert body["append"]["form"] == "statement" and body["append"]["affected"] == 1
    assert "2025-04" in client.get("/api/meta").json()["months"]


def test_sql_append_dedup_off(client):
    payload = {"sql": "SELECT '2025-06-01' AS 日期, '餐饮' AS 类别, 1 AS 金额", "dedup": False}
    assert client.post("/api/append/sql", json=payload).json()["append"]["inserted"] == 1
    assert client.post("/api/append/sql", json=payload).json()["append"]["inserted"] == 1


def test_sql_append_errors(client):
    assert client.post("/api/append/sql", json={"sql": "SELECT 1 AS x"}).status_code == 400
    assert client.post("/api/append/sql", json={"sql": "SELECT 1; SELECT 2"}).status_code == 400
    assert client.post("/api/append/sql", json={"sql": "-- 注释"}).status_code == 400
    assert client.post("/api/append/sql", json={"sql": "SELECT * FROM nope"}).status_code == 400


# --------------------------- SQL 工作台 API ---------------------------
def test_tables_listing(client):
    names = [t["name"] for t in client.get("/api/tables").json()["tables"]]
    assert {"raw_spending", "dwd_spending", "dws_monthly_category"} <= set(names)


def test_table_preview(client):
    d = client.post("/api/table/preview", json={"name": "dws_monthly_category", "limit": 3}).json()
    assert d["columns"] == ["month", "category", "total_amount", "order_count"]
    assert len(d["rows"]) == 3

    assert client.post("/api/table/preview", json={"name": "no_such"}).status_code == 404


def test_sql_query(client):
    d = client.post("/api/sql", json={"sql": "SELECT count(*) AS n FROM dwd_spending"}).json()
    assert d["results"][0]["type"] == "query"
    assert d["results"][0]["columns"] == ["n"]
    assert d["results"][0]["rows"][0][0] > 0


def test_sql_console_create_and_reject_writes(client):
    """SQL 工作台：允许 CREATE 建表，拒绝改数/删表。"""
    d = client.post("/api/sql", json={
        "sql": "CREATE OR REPLACE TABLE my_monthly AS SELECT month FROM dws_monthly_category"}).json()
    assert d["results"][0]["type"] == "exec"
    assert "my_monthly" in [t["name"] for t in client.get("/api/tables").json()["tables"]]

    r = client.post("/api/sql", json={"sql": "DROP TABLE dwd_spending"})
    assert r.status_code == 400
    # 表还在
    assert "dwd_spending" in [t["name"] for t in client.get("/api/tables").json()["tables"]]


def test_sql_export_csv(client):
    r = client.post("/api/sql/export",
                    json={"sql": "SELECT month, category FROM dwd_spending "
                                 "ORDER BY month, category LIMIT 2"})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.lstrip("\ufeff").strip().splitlines()
    assert lines[0] == "month,category"
    assert len(lines) == 3


def test_sql_export_rejects_write(client):
    assert client.post("/api/sql/export", json={"sql": "DROP TABLE dwd_spending"}).status_code == 400


def test_sql_save_as_table(client):
    """SELECT 结果可落库保存为表。"""
    r = client.post("/api/sql/save", json={
        "sql": "SELECT category, round(sum(amount), 2) AS total FROM dwd_spending GROUP BY category",
        "name": "cat_sum"})
    assert r.status_code == 200
    assert r.json()["name"] == "cat_sum"
    assert "cat_sum" in [t["name"] for t in client.get("/api/tables").json()["tables"]]


def test_sql_save_as_table_rejects_bad_input(client):
    assert client.post("/api/sql/save",
                       json={"sql": "SELECT 1", "name": "1 bad"}).status_code == 400
    assert client.post("/api/sql/save",
                       json={"sql": "DROP TABLE dwd_spending", "name": "x"}).status_code == 400


def test_sql_error_returns_400(client):
    r = client.post("/api/sql", json={"sql": "SELECT * FROM nope"})
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_sql_empty_returns_400(client):
    assert client.post("/api/sql", json={"sql": "   -- 只有注释\n"}).status_code == 400
