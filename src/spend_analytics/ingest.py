"""数据接入：读取 Excel/CSV 花销表格，写入原始层 raw_spending。

- 支持 .xlsx / .xls / .csv
- 表头支持中英文别名（日期/date、类别/category、金额/amount、备注/note …）
- 追加模式（默认）：按「日期+类别+金额+备注」判重，避免重复计入
- 替换模式：先删除表格中出现的月份对应的原始行，再整月写入（修正数据用）
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pandas as pd

from . import config, etl, sqlconsole

# 表头别名 -> 规范列名
HEADER_ALIASES = {
    # 日期
    "日期": config.COL_DATE, "date": config.COL_DATE, "交易日期": config.COL_DATE,
    "消费日期": config.COL_DATE, "时间": config.COL_DATE, "账单日期": config.COL_DATE,
    # 类别
    "类别": config.COL_CATEGORY, "category": config.COL_CATEGORY, "分类": config.COL_CATEGORY,
    "类型": config.COL_CATEGORY, "消费类别": config.COL_CATEGORY, "消费类型": config.COL_CATEGORY,
    # 金额
    "金额": config.COL_AMOUNT, "amount": config.COL_AMOUNT, "金额(元)": config.COL_AMOUNT,
    "消费金额": config.COL_AMOUNT, "money": config.COL_AMOUNT, "price": config.COL_AMOUNT,
    # 备注
    "备注": config.COL_NOTE, "note": config.COL_NOTE, "remark": config.COL_NOTE,
    "说明": config.COL_NOTE, "摘要": config.COL_NOTE, "商户": config.COL_NOTE,
}

CANONICAL = [config.COL_DATE, config.COL_CATEGORY, config.COL_AMOUNT, config.COL_NOTE]

_EXCEL_EPOCH = _dt.date(1899, 12, 30)


def _normalize_header(name: str) -> str:
    key = str(name).strip().lower().replace(" ", "").replace("　", "")
    return HEADER_ALIASES.get(key, str(name).strip())


def _coerce_date_string(value) -> str:
    """把各种日期表现统一成字符串（Excel 序列号 -> ISO，datetime -> ISO）。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (_dt.date, _dt.datetime, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    text = str(value).strip()
    # Excel 日期序列号（20000~60000 大致覆盖 1954~2064 年）
    if text.replace(".", "", 1).isdigit():
        num = float(text)
        if 20000 <= num <= 60000:
            return (_EXCEL_EPOCH + _dt.timedelta(days=int(num))).strftime("%Y-%m-%d")
    return text


def read_spending_table(path: str | Path) -> pd.DataFrame:
    """读取花销表格，返回含规范四列的 DataFrame（值均为字符串/空）。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")

    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        raw = pd.read_excel(path, dtype=str)
    elif suffix == ".csv":
        # 兼容 UTF-8 / UTF-8-SIG / GBK
        try:
            raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = pd.read_csv(path, dtype=str, encoding="gbk")
    else:
        raise ValueError(f"不支持的文件类型：{suffix}（仅支持 .csv / .xlsx / .xls）")

    raw.columns = [_normalize_header(c) for c in raw.columns]

    # 补齐缺失列
    for col in CANONICAL:
        if col not in raw.columns:
            raw[col] = ""

    df = raw[CANONICAL].copy()
    df[config.COL_DATE] = df[config.COL_DATE].map(_coerce_date_string)
    for col in (config.COL_CATEGORY, config.COL_AMOUNT, config.COL_NOTE):
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def _row_key(df: pd.DataFrame) -> pd.Series:
    s = df[config.COL_DATE].fillna("").astype(str).str.strip()
    for col in (config.COL_CATEGORY, config.COL_AMOUNT, config.COL_NOTE):
        s = s + "|" + df[col].fillna("").astype(str).str.strip()
    return s


def _file_months(df: pd.DataFrame) -> list[str]:
    """从「日期」列提取月份（YYYY-MM），兼容 - / . 年月 及紧凑格式。"""
    months = set()
    for text in df[config.COL_DATE].astype(str):
        t = text.strip()
        m = re.match(r"^(\d{4})[-/.](\d{1,2})", t)
        if m:
            months.add(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}")
            continue
        m = re.match(r"^(\d{4})年(\d{1,2})月", t)
        if m:
            months.add(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}")
            continue
        m = re.match(r"^(\d{4})(\d{2})\d{2}$", t)
        if m:
            months.add(f"{m.group(1)}-{m.group(2)}")
    return sorted(months)


def _append_rows(con, df, source: str, *, dedup_intra: bool = True,
                 dedup_existing: bool = True) -> dict:
    """把规范四列的 DataFrame 写入原始层，返回去重统计。

    dedup_intra    文件/结果集内部去重
    dedup_existing 与库中已有记录去重
    """
    skipped_intra = 0
    if dedup_intra:
        dup = _row_key(df).duplicated(keep="first")
        skipped_intra = int(dup.sum())
        if skipped_intra:
            df = df[~dup].reset_index(drop=True)

    skipped_existing = 0
    if dedup_existing:
        existing = con.execute(
            f'SELECT "日期","类别","金额","备注" FROM {config.RAW_TABLE}'
        ).df()
        if len(existing):
            mask = ~_row_key(df).isin(set(_row_key(existing)))
            skipped_existing = int((~mask).sum())
            df = df[mask].reset_index(drop=True)

    inserted = int(len(df))
    if inserted:
        to_insert = df.copy()
        to_insert["_源文件"] = source
        to_insert["_导入时间"] = pd.Timestamp.now()
        con.register("_stage_spend", to_insert)
        con.execute(
            f"""INSERT INTO {config.RAW_TABLE}
                ("日期","类别","金额","备注","_源文件","_导入时间")
                SELECT "日期","类别","金额","备注","_源文件","_导入时间" FROM _stage_spend"""
        )
        con.unregister("_stage_spend")

    return {
        "inserted": inserted,
        "skipped_duplicate_in_file": skipped_intra,
        "skipped_already_exists": skipped_existing,
        "skipped": skipped_intra + skipped_existing,
    }


def ingest_file(con, path: str | Path, mode: str = "append") -> dict:
    """导入一个花销文件到 raw_spending。

    mode="append"  追加：跳过已存在的相同记录（日期+类别+金额+备注）
    mode="replace" 替换：删除文件中出现的月份后整月写入

    返回统计信息 dict。
    """
    if mode not in ("append", "replace"):
        raise ValueError("mode 只能是 'append' 或 'replace'")

    df = read_spending_table(path)
    total_read = int(len(df))
    file_months = _file_months(df)

    # 替换模式：先清掉这些月份的旧原始数据
    removed = 0
    if mode == "replace" and file_months:
        placeholders = ", ".join(["?"] * len(file_months))
        where = f"strftime({etl.DATE_EXPR}, '%Y-%m') IN ({placeholders})"
        removed = con.execute(
            f"SELECT count(*) FROM {config.RAW_TABLE} WHERE {where}", file_months
        ).fetchone()[0]
        con.execute(f"DELETE FROM {config.RAW_TABLE} WHERE {where}", file_months)

    stats = _append_rows(con, df, Path(path).name,
                         dedup_intra=True, dedup_existing=(mode == "append"))

    return {
        "file": Path(path).name,
        "mode": mode,
        "total_read": total_read,
        **stats,
        "removed": int(removed),
        "months": file_months,
    }


def _query_result_to_raw(columns, rows) -> pd.DataFrame:
    """把 SQL 查询结果转成规范四列（日期/类别/金额/备注）的 DataFrame。"""
    df = pd.DataFrame(rows, columns=[_normalize_header(c) for c in columns])
    df = df.loc[:, ~df.columns.duplicated()]        # 防 category 与 类别 撞名

    required = (config.COL_DATE, config.COL_CATEGORY, config.COL_AMOUNT)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            "SQL 结果需包含列：" + "、".join(required) + "（备注可选），"
            f"当前缺少：{'、'.join(missing)}。可用别名，例如 "
            "SELECT date, category, amount, note FROM ..."
        )

    for col in CANONICAL:
        if col not in df.columns:
            df[col] = ""
    df = df[CANONICAL].copy()
    df[config.COL_DATE] = df[config.COL_DATE].map(_coerce_date_string)
    for col in (config.COL_CATEGORY, config.COL_AMOUNT, config.COL_NOTE):
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def append_via_sql(con, sql: str, dedup: bool = True, source: str = "SQL 追加") -> dict:
    """用 SQL 向原始层追加数据（随后由 ETL 落到明细层/汇总层）。

    支持两种写法：
      1) 查询语句（SELECT / WITH）：结果集含 日期·类别·金额（备注可选）→ 按去重规则追加
      2) 写入语句（INSERT / UPDATE / …）：直接在库上执行，去重由语句自身负责

    建议写入 raw_spending —— ETL 会基于它重建明细层与汇总层。
    """
    statements = sqlconsole.split_statements(sql)
    if not statements:
        raise ValueError("SQL 为空")
    if len(statements) > 1:
        raise ValueError("追加只支持单条语句，请用分号之外的方式合并或分批执行")

    stmt = statements[0]
    cur = con.execute(stmt)

    if sqlconsole.is_query(stmt):
        cols = [d[0] for d in (cur.description or [])]
        df = _query_result_to_raw(cols, cur.fetchall())
        stats = _append_rows(con, df, source, dedup_intra=dedup, dedup_existing=dedup)
        return {"form": "select", "statement": stmt, "total_read": len(df),
                **stats, "affected": None, "months": _file_months(df)}

    return {"form": "statement", "statement": stmt, "total_read": None,
            "inserted": None, "skipped_duplicate_in_file": 0,
            "skipped_already_exists": 0, "skipped": 0,
            "affected": sqlconsole.affected(cur), "months": []}


def ingest_directory(con, directory: str | Path | None = None, mode: str = "append") -> list[dict]:
    """批量导入目录下所有 csv/xlsx 文件（按文件名排序）。"""
    directory = Path(directory) if directory else config.INPUT_DIR
    files = sorted(
        [p for p in Path(directory).iterdir()
         if p.suffix.lower() in (".csv", ".xlsx", ".xls") and not p.name.startswith("~$")]
    )
    return [ingest_file(con, f, mode=mode) for f in files]


def list_source_files(directory: str | Path | None = None) -> list[dict]:
    """列出 data/input 下的花销表格（文件名、大小、修改时间、行数）。"""
    directory = Path(directory) if directory else config.INPUT_DIR
    out = []
    for p in sorted(Path(directory).iterdir()):
        if p.suffix.lower() not in (".csv", ".xlsx", ".xls") or p.name.startswith("~$"):
            continue
        st = p.stat()
        try:
            rows = int(len(read_spending_table(p)))
            error = None
        except Exception as e:                       # 坏文件不阻塞列表
            rows, error = None, str(e)
        out.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "rows": rows,
            "error": error,
        })
    return out


def preview_source_file(path: str | Path, limit: int = 50) -> dict:
    """原样预览文件前若干行（保留用户原始表头）。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str, nrows=int(limit))
    else:
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", nrows=int(limit))
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype=str, encoding="gbk", nrows=int(limit))
    return {
        "name": path.name,
        "columns": [str(c) for c in df.columns],
        "rows": df.fillna("").astype(str).values.tolist(),
    }
