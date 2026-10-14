"""验收测试：对应需求第六章验收标准。"""
from __future__ import annotations

import datetime as dt
import re
import time

import pandas as pd
import pytest

from scripts.generate_sample_data import build_dataset
from spend_analytics import db, etl, ingest, metrics, query, report

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
]


# --------------------------------------------------------------------------
# 参考实现（独立于生产代码，手工复刻 ETL 规则）
# --------------------------------------------------------------------------
def ref_parse_date(value) -> dt.date | None:
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def ref_parse_amount(value) -> float | None:
    text = re.sub(r"[^0-9.\-]", "", str(value).strip())
    try:
        return float(text)
    except ValueError:
        return None


def ref_valid(df: pd.DataFrame) -> pd.DataFrame:
    """按 ETL 口径从原始表算出的有效明细。"""
    rows = []
    for _, r in df.iterrows():
        d = ref_parse_date(r["日期"])
        a = ref_parse_amount(r["金额"])
        cat = str(r["类别"]).strip().upper()
        if d is None or a is None or a <= 0 or cat == "":
            continue
        rows.append({"spend_date": d, "month": d.strftime("%Y-%m"),
                     "category": cat, "amount": round(a, 2)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def con(tmp_path):
    c = db.connect(tmp_path / "test.duckdb")
    db.init_schema(c)
    yield c
    c.close()


@pytest.fixture()
def sample_files(tmp_path):
    """写出示例 CSV / XLSX 到临时目录。"""
    m1 = [f"2025-{m:02d}" for m in range(1, 7)]
    m2 = ["2025-07", "2025-08"]
    df_a = build_dataset(m1)
    df_b = build_dataset(m2, with_dirty=False)
    p_a = tmp_path / "月度花销_2025年1-6月.csv"
    p_b = tmp_path / "月度花销_2025年7-8月.xlsx"
    df_a.to_csv(p_a, index=False, encoding="utf-8-sig")
    df_b.to_excel(p_b, index=False)
    return p_a, p_b, df_a, df_b


@pytest.fixture()
def loaded(con, sample_files):
    p_a, p_b, df_a, df_b = sample_files
    ingest.ingest_file(con, p_a)
    stats = etl.run_etl(con)
    return con, stats, df_a, df_b


# --------------------------------------------------------------------------
# 验收 1：数据导入
# --------------------------------------------------------------------------
def test_ingest_record_count(con, sample_files):
    p_a, _, df_a, _ = sample_files
    res = ingest.ingest_file(con, p_a)
    # 文件内重复行被去重
    expected_unique = len(df_a.drop_duplicates(subset=["日期", "类别", "金额", "备注"]))
    assert res["total_read"] == len(df_a)
    assert res["inserted"] == expected_unique
    assert res["skipped_duplicate_in_file"] == len(df_a) - expected_unique
    n_raw = con.execute(f"SELECT count(*) FROM {db.config.RAW_TABLE}").fetchone()[0]
    assert n_raw == expected_unique


def test_ingest_is_idempotent(con, sample_files):
    p_a, _, _, _ = sample_files
    first = ingest.ingest_file(con, p_a)
    second = ingest.ingest_file(con, p_a)
    assert second["inserted"] == 0
    assert second["skipped_already_exists"] == first["inserted"]
    n_raw = con.execute(f"SELECT count(*) FROM {db.config.RAW_TABLE}").fetchone()[0]
    assert n_raw == first["inserted"]


def test_append_new_months(con, sample_files):
    p_a, p_b, _, df_b = sample_files
    ingest.ingest_file(con, p_a)
    res = ingest.ingest_file(con, p_b)
    assert res["inserted"] == len(df_b)
    assert set(res["months"]) == {"2025-07", "2025-08"}


# --------------------------------------------------------------------------
# 验收 2：ETL 清洗
# --------------------------------------------------------------------------
def test_etl_filters_invalid_rows(con, sample_files):
    p_a, _, df_a, _ = sample_files
    ingest.ingest_file(con, p_a)
    stats = etl.run_etl(con)
    # 脏数据：空金额1、负数1、0金额1、空日期1、非法日期1
    assert stats["dropped_invalid_date"] == 2      # 空日期 + not-a-date
    assert stats["dropped_invalid_amount"] == 1    # 空金额
    assert stats["dropped_non_positive_amount"] == 2  # -120 与 0
    assert stats["dropped_total"] == 5
    # 明细层 = 原始层 - 被过滤行
    assert stats["dwd_count"] == stats["raw_total"] - 5


def test_etl_cleans_date_and_category(loaded):
    con, _, _, _ = loaded
    df = con.execute(
        f"SELECT spend_date, month, category FROM {db.config.DWD_TABLE}"
    ).df()
    # 日期可解析、格式统一为 DATE
    assert df["spend_date"].notna().all()
    assert df["month"].str.match(r"^\d{4}-\d{2}$").all()
    # 类别去空格并大写
    assert (df["category"] == df["category"].str.strip().str.upper()).all()
    cats = set(df["category"])
    assert "餐饮" in cats and "FOOD" in cats and "SHOPPING" in cats
    assert " 餐饮 " not in cats


def test_dirty_rows_amount_parsed(loaded):
    con, _, _, _ = loaded
    row = con.execute(
        f"SELECT amount FROM {db.config.DWD_TABLE} WHERE category = 'FOOD'"
    ).fetchone()
    assert row is not None and float(row[0]) == 1280.0


# --------------------------------------------------------------------------
# 验收 3 & 4：汇总正确 / 口径一致
# --------------------------------------------------------------------------
def test_monthly_total_matches_manual(loaded):
    con, _, _, _ = loaded
    raw = con.execute(
        f'SELECT "日期","类别","金额","备注" FROM {db.config.RAW_TABLE}'
    ).df()
    ref = ref_valid(raw)
    expected = ref.groupby("month")["amount"].sum().round(2).to_dict()
    actual = {r["month"]: round(r["total_amount"], 2) for r in metrics.monthly_totals(con)}
    assert actual == expected


def test_metric_consistency(loaded):
    con, _, _, _ = loaded
    m = metrics.list_months(con)[0]
    # 同一指标多次查询结果一致
    a = metrics.monthly_total(con, m)
    b = metrics.monthly_total(con, m)
    c = sum(r["total_amount"] for r in metrics.category_spend(con, m))
    assert a == b == round(c, 2)


def test_dws_equals_dwd_aggregation(loaded):
    con, _, _, _ = loaded
    dws = con.execute(
        f"SELECT month, category, total_amount, order_count "
        f"FROM {db.config.DWS_TABLE} ORDER BY month, category"
    ).df()
    dwd = con.execute(
        f"SELECT month, category, round(sum(amount),2) AS total_amount, "
        f"count(*)::INTEGER AS order_count FROM {db.config.DWD_TABLE} "
        f"GROUP BY month, category ORDER BY month, category"
    ).df()
    pd.testing.assert_frame_equal(dws.reset_index(drop=True), dwd.reset_index(drop=True))


# --------------------------------------------------------------------------
# 验收 5 & 6：自助报表 / 分类占比
# --------------------------------------------------------------------------
def test_trend_series(loaded):
    con, _, _, _ = loaded
    trend = report.trend(con)
    assert len(trend) == 6
    assert [r["month"] for r in trend] == sorted(r["month"] for r in trend)


def test_category_share_sums_to_100(loaded):
    con, _, _, _ = loaded
    month = metrics.list_months(con)[-1]
    shares = metrics.category_share(con, month)
    assert shares
    assert abs(sum(s["share"] for s in shares) - 100.0) < 0.5


def test_query_pie_data(loaded):
    con, _, _, _ = loaded
    data = query.chart_data(con, "category", "total_amount", months=["2025-01"])
    assert data["rows"] and all(r["measure"] > 0 for r in data["rows"])


def test_query_weekday_dimension(loaded):
    con, _, _, _ = loaded
    data = query.chart_data(con, "weekday", "order_count")
    assert len(data["rows"]) == 7


def test_query_filters(loaded):
    con, _, _, _ = loaded
    data = query.chart_data(con, "category", "total_amount",
                            categories=["餐饮", "交通"], min_amount=50)
    assert all(r["dimension"] in ("餐饮", "交通") for r in data["rows"])


# --------------------------------------------------------------------------
# 验收 7：环比对比
# --------------------------------------------------------------------------
def test_mom_change(loaded):
    con, _, _, _ = loaded
    m = metrics.list_months(con)[-1]
    mom = metrics.mom_change(con, m)
    assert mom["current"] == metrics.monthly_total(con, m)
    assert mom["previous"] == metrics.monthly_total(con, mom["prev_month"])
    assert round(mom["delta"], 2) == round(mom["current"] - mom["previous"], 2)


def test_category_mom_table(loaded):
    con, _, _, _ = loaded
    m = metrics.list_months(con)[-1]
    table = report.category_mom(con, m)
    assert table["rows"]
    for r in table["rows"]:
        assert round(r["current_amount"] - r["prev_amount"], 2) == round(r["delta"], 2)


def test_crosstab(loaded):
    con, _, _, _ = loaded
    ct = query.crosstab(con, measure="total_amount")
    assert len(ct["rows"]) == 6
    assert ct["columns"]


# --------------------------------------------------------------------------
# 验收 8：响应速度
# --------------------------------------------------------------------------
def test_query_latency(loaded):
    con, _, _, _ = loaded
    start = time.perf_counter()
    for _ in range(20):
        metrics.monthly_total(con, "2025-03")
        query.crosstab(con, measure="total_amount")
    elapsed = (time.perf_counter() - start) / 20
    assert elapsed < 2.0, f"平均查询耗时 {elapsed:.3f}s 超过 2 秒"


# --------------------------------------------------------------------------
# 细节 / 报表
# --------------------------------------------------------------------------
def test_dashboard_shape(loaded):
    con, _, _, _ = loaded
    d = report.dashboard(con)
    assert d["empty"] is False
    assert d["cards"]["month"] == metrics.list_months(con)[-1]
    assert d["trend"] and d["category_share"] and d["category_mom"]


def test_detail_query(loaded):
    con, _, _, _ = loaded
    rows = query.detail(con, min_amount=1000, limit=50)
    assert all(r["amount"] >= 1000 for r in rows)


def test_reads_english_headers(con, tmp_path):
    p = tmp_path / "english.csv"
    pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03"],
        "category": ["food", "transport"],
        "amount": ["10.5", "20"],
        "note": ["a", "b"],
    }).to_csv(p, index=False, encoding="utf-8-sig")
    res = ingest.ingest_file(con, p)
    assert res["inserted"] == 2
    etl.run_etl(con)
    assert metrics.monthly_total(con, "2025-01") == 30.5


# --------------------------------------------------------------------------
# SQL 追加
# --------------------------------------------------------------------------
def test_append_via_sql_select(con):
    r = ingest.append_via_sql(con, """
        SELECT * FROM (VALUES
            ('2025-03-01', '餐饮', 38.5, '午餐'),
            ('2025-03-02', '交通', 12.0, '地铁')
        ) AS t(日期, 类别, 金额, 备注)
    """)
    assert r["form"] == "select" and r["inserted"] == 2
    etl.run_etl(con)
    assert metrics.monthly_total(con, "2025-03") == 50.5


def test_append_via_sql_dedup(con):
    sql = "SELECT '2025-03-01' AS 日期, '餐饮' AS 类别, 38.5 AS 金额, '午餐' AS 备注"
    first = ingest.append_via_sql(con, sql)
    second = ingest.append_via_sql(con, sql)
    assert first["inserted"] == 1
    assert second["inserted"] == 0 and second["skipped_already_exists"] == 1


def test_append_via_sql_dedup_off(con):
    sql = "SELECT '2025-03-01' AS 日期, '餐饮' AS 类别, 38.5 AS 金额, '午餐' AS 备注"
    ingest.append_via_sql(con, sql)
    assert ingest.append_via_sql(con, sql, dedup=False)["inserted"] == 1


def test_append_via_sql_accepts_english_aliases(con):
    r = ingest.append_via_sql(con, "SELECT '2025-05-01' AS date, 'Food' AS category, 5 AS amount")
    assert r["inserted"] == 1


def test_append_via_sql_insert_statement(con):
    r = ingest.append_via_sql(
        con,
        'INSERT INTO raw_spending ("日期","类别","金额","备注") '
        "VALUES ('2025-04-01', '购物', 99.9, '日用品')")
    assert r["form"] == "statement" and r["affected"] == 1
    etl.run_etl(con)
    assert metrics.monthly_total(con, "2025-04") == 99.9


def test_append_via_sql_rejects_bad_input(con):
    with pytest.raises(ValueError, match="缺少"):
        ingest.append_via_sql(con, "SELECT 1 AS foo")
    with pytest.raises(ValueError, match="单条"):
        ingest.append_via_sql(con, "SELECT 1; SELECT 2")
    with pytest.raises(ValueError, match="为空"):
        ingest.append_via_sql(con, "  -- 只有注释\n")


# --------------------------------------------------------------------------
# 数据接入：TXT（自动编码 + 自动分隔符）
# --------------------------------------------------------------------------
def _txt(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_read_txt_comma(tmp_path):
    p = _txt(tmp_path, "a.txt", "日期,类别,金额,备注\n2025-03-01,餐饮,12.5,午餐\n")
    df = ingest.read_spending_table(p)
    assert list(df.columns) == ["日期", "类别", "金额", "备注"]
    assert df.iloc[0].tolist() == ["2025-03-01", "餐饮", "12.5", "午餐"]


@pytest.mark.parametrize("sep", ["\t", ";", "|"])
def test_read_txt_sniffs_delimiter(tmp_path, sep):
    p = _txt(tmp_path, "d.txt", f"date{sep}category{sep}amount\n2025-03-02{sep}交通{sep}8\n")
    df = ingest.read_spending_table(p)          # 契约：始终返回规范四列
    assert list(df.columns) == ["日期", "类别", "金额", "备注"]
    assert df.iloc[0].tolist() == ["2025-03-02", "交通", "8", ""]


def test_read_txt_whitespace(tmp_path):
    p = _txt(tmp_path, "w.txt", "date category amount\n2025-03-05 餐饮 6.5\n")
    assert ingest.read_spending_table(p).iloc[0].tolist() == ["2025-03-05", "餐饮", "6.5", ""]


def test_read_txt_gbk(tmp_path):
    p = _txt(tmp_path, "g.txt", "日期,类别,金额\n2025-03-04,餐饮,6\n", encoding="gbk")
    assert ingest.read_spending_table(p).iloc[0].tolist() == ["2025-03-04", "餐饮", "6", ""]


def test_ingest_txt_writes_and_etls(con, tmp_path):
    p = _txt(tmp_path, "m.txt",
             "日期,类别,金额,备注\n2025-03-01,餐饮,10,午餐\n2025-03-01,交通,5,\n")
    assert ingest.ingest_file(con, p)["inserted"] == 2
    etl.run_etl(con)
    assert con.execute(f"SELECT count(*) FROM {db.config.DWD_TABLE}").fetchone()[0] == 2
    assert metrics.monthly_total(con, "2025-03") == 15.0


def test_unsupported_suffix_lists_supported(tmp_path):
    with pytest.raises(ValueError) as e:
        ingest.read_spending_table(_txt(tmp_path, "a.doc", "x"))
    assert ".txt" in str(e.value)
    assert set(ingest.SUPPORTED_SUFFIXES) == {".csv", ".xlsx", ".xls", ".txt"}


# --------------------------------------------------------------------------
# 宽表（原始 Excel：日期 + 各分类各占一列）自动 melt
# --------------------------------------------------------------------------
def _write_wide(path, sheet, rows):
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name=sheet, index=False, header=False)
    return path


def test_read_wide_excel_melts_to_long(tmp_path):
    p = _write_wide(tmp_path / "wide.xlsx", "Jan", [
        ["个人支出表", None, None, None],          # 标题行
        ["日期", "餐饮", "交通", "房租"],           # 表头行
        ["2025-01-01", 10.5, 3, 1850],
        ["2025-01-02", None, 8, None],
        [None, 20, 5, 1850],                      # 无日期（汇总行）→ 跳过
    ])
    df = ingest.read_spending_table(p)
    assert list(df.columns) == ["日期", "类别", "金额", "备注"]
    assert len(df) == 4
    assert set(df["类别"]) == {"餐饮", "交通", "房租"}
    assert df[df["类别"] == "房租"]["金额"].tolist() == ["1850"]
    assert df["日期"].str[:7].unique().tolist() == ["2025-01"]


def test_read_wide_excel_merges_sheets(tmp_path):
    p = tmp_path / "two.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        for sheet, day in (("Jan", "2025-01-01"), ("Feb", "2025-02-01")):
            pd.DataFrame([["日期", "餐饮"], [day, 5]]).to_excel(
                w, sheet_name=sheet, index=False, header=False)
    df = ingest.read_spending_table(p)
    assert sorted(df["日期"]) == ["2025-01-01", "2025-02-01"]


def test_long_table_not_treated_as_wide(tmp_path):
    """长表不能被误判成宽表。"""
    p = _txt(tmp_path, "l.txt", "日期,类别,金额,备注\n2025-03-01,餐饮,10,x\n")
    df = ingest.read_spending_table(p)
    assert len(df) == 1 and df.iloc[0].tolist() == ["2025-03-01", "餐饮", "10", "x"]


def test_ingest_wide_excel_end_to_end(con, tmp_path):
    p = _write_wide(tmp_path / "w.xlsx", "Jan", [
        ["日期", "餐饮", "交通"],
        ["2025-03-01", 10, 5],
        ["2025-03-02", None, 7],
    ])
    assert ingest.ingest_file(con, p)["inserted"] == 3
    etl.run_etl(con)
    assert metrics.monthly_total(con, "2025-03") == 22.0


# --------------------------------------------------------------------------
# 预览（多 Sheet）/ 解析（转规范四列）
# --------------------------------------------------------------------------
def test_preview_covers_all_sheets(tmp_path):
    p = tmp_path / "two.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        pd.DataFrame([["日期", "餐饮"], ["2025-01-01", 5]]).to_excel(
            w, sheet_name="Jan", index=False, header=False)
        pd.DataFrame([["日期", "餐饮"], ["2025-02-01", 7]]).to_excel(
            w, sheet_name="Feb", index=False, header=False)
    d = ingest.preview_source_file(p, limit=10)
    assert d["sheets"] == ["Jan", "Feb"]
    assert d["columns"][0] == "Sheet"
    assert [r[0] for r in d["rows"]] == ["Jan", "Feb"]      # 两个 Sheet 都出现


def test_parse_source_file_returns_canonical(tmp_path):
    p = _write_wide(tmp_path / "w.xlsx", "Jan", [
        ["日期", "餐饮", "交通"],
        ["2025-03-01", 10, 5],
        ["2025-03-02", None, 7],
    ])
    d = ingest.parse_source_file(p)
    assert d["columns"] == ["日期", "类别", "金额", "备注"]
    assert d["total"] == 3 and d["months"] == 1 and d["amount_total"] == 22.0
    assert len(d["rows"]) == 3


# --------------------------------------------------------------------------
# 年份维度 / 年份筛选
# --------------------------------------------------------------------------
def _seed_years(con):
    for day, amt in (("2024-03-01", 10), ("2025-03-01", 30), ("2025-04-01", 20)):
        ingest.append_via_sql(con, f"SELECT '{day}' AS date, '餐饮' AS category, {amt} AS amount")
    etl.run_etl(con)


def test_chart_by_year_dimension(con):
    _seed_years(con)
    d = query.chart_data(con, "year", "total_amount")
    assert d["dimension_label"] == "年份"
    assert d["rows"] == [{"dimension": "2024", "measure": 10.0},
                         {"dimension": "2025", "measure": 50.0}]


def test_years_filter(con):
    _seed_years(con)
    only25 = query.chart_data(con, "month", "total_amount", years=["2025"])
    assert [r["dimension"] for r in only25["rows"]] == ["2025-03", "2025-04"]

    none = query.chart_data(con, "month", "total_amount", years=["2023"])
    assert none["rows"] == [] and none["total"] == 0

    both = query.chart_data(con, "year", "total_amount", years=["2024", "2025"])
    assert len(both["rows"]) == 2            # 多选年份

    # 年份筛选同样作用于明细与交叉表
    assert len(query.detail(con, years=["2025"])) == 2
    assert len(query.crosstab(con, years=["2025"])["rows"]) == 2


def test_list_years(con):
    _seed_years(con)
    assert metrics.list_years(con) == ["2024", "2025"]


def test_every_dimension_and_measure_is_queryable(con):
    """遍历全部维度 × 度量，确保白名单里的表达式/聚合都能真的跑通。"""
    _seed_years(con)
    for dim in query.DIMENSIONS:
        assert query.chart_data(con, dim, "total_amount")["dimension"] == dim
    for meas in query.MEASURES:
        d = query.chart_data(con, "category", meas)
        assert d["measure"] == meas and d["unit"]
    # 每一列的维度标签/度量标签都要有
    m = query.meta()
    assert all(x["label"] for x in m["dimensions"] + m["measures"])
