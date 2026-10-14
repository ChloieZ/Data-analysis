"""Web 服务（FastAPI）——三个页面：

    /        数据大屏     指标卡 · 趋势 · 分类占比 · 环比 · 明细 · 自助分析
    /source  源数据处理   上传表格 · 已上传文件列表 · 原样预览 · 重新同步(ETL)
    /sql     SQL 工作台   写 SQL 建表 / 查询 / 预览、查看库内所有表

启动：
    python -m spend_analytics.cli serve
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 将 src/ 加入模块搜索路径，保证直接以 web.app 启动时也能 import spend_analytics
BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from spend_analytics import (  # noqa: E402
    config, db, etl, ingest, metrics, query, report, sqlconsole,
)

app = FastAPI(title="个人花销分析平台", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

_con = None
_lock = threading.Lock()


def get_con():
    global _con
    if _con is None:
        _con = db.connect()
        db.init_schema(_con)
    return _con


def _source_path(name: str) -> Path:
    """把文件名安全地解析到 data/input 下，防止路径穿越。"""
    base = config.INPUT_DIR.resolve()
    p = (base / Path(name).name).resolve()
    if p.parent != base:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在：{name}")
    return p


# ------------------------------- 请求模型 -------------------------------
class ChartReq(BaseModel):
    dimension: str = "category"
    measure: str = "total_amount"
    years: list[str] | None = None
    months: list[str] | None = None
    categories: list[str] | None = None
    note: str | None = None
    min_amount: float | None = None
    limit: int = 100


class CrossReq(BaseModel):
    years: list[str] | None = None
    months: list[str] | None = None
    categories: list[str] | None = None
    note: str | None = None
    measure: str = "total_amount"


class DetailReq(BaseModel):
    years: list[str] | None = None
    months: list[str] | None = None
    categories: list[str] | None = None
    note: str | None = None
    min_amount: float | None = None
    limit: int = 200


class NameReq(BaseModel):
    name: str
    limit: int = 100


class SqlReq(BaseModel):
    sql: str
    limit: int = sqlconsole.DEFAULT_LIMIT


class SqlExportReq(BaseModel):
    sql: str
    limit: int = 10000


class SqlSaveReq(BaseModel):
    sql: str
    name: str
    replace: bool = True


class SqlAppendReq(BaseModel):
    sql: str
    dedup: bool = True


# ------------------------------- 页面 -------------------------------
def _page(filename: str):
    return FileResponse(str(config.STATIC_DIR / filename))


@app.get("/", include_in_schema=False)
def page_dashboard():
    return _page("index.html")


@app.get("/source", include_in_schema=False)
def page_source():
    """数据管理：文件接入 + SQL 工作台（子标签切换）。"""
    return _page("source.html")


@app.get("/charts", include_in_schema=False)
def page_charts():
    """图表工坊：内置指标 + 拖拽生成图表。"""
    return _page("charts.html")


@app.get("/sql", include_in_schema=False)
def page_sql():
    """SQL 工作台已并入「数据管理」页，旧链接重定向。"""
    return RedirectResponse("/source", status_code=307)


@app.get("/api/health")
def health():
    with _lock:
        return {"ok": True, "tables": db.table_counts(get_con())}


@app.get("/api/meta")
def meta():
    with _lock:
        con = get_con()
        months = metrics.list_months(con)
        years = metrics.list_years(con)
        categories = metrics.list_categories(con)
    return {
        **query.meta(),
        "months": months,
        "years": years,
        "categories": categories,
        "metrics": metrics.METRIC_CATALOG,
    }


# --------------------------- 大屏：数据接口 ---------------------------
@app.get("/api/dashboard")
def dashboard(month: str | None = None):
    with _lock:
        return report.dashboard(get_con(), month)


@app.post("/api/chart")
def chart(req: ChartReq):
    try:
        with _lock:
            return query.chart_data(
                get_con(), req.dimension, req.measure,
                years=req.years, months=req.months, categories=req.categories,
                note_kw=req.note, min_amount=req.min_amount, limit=req.limit,
            )
    except query.QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/crosstab")
def crosstab(req: CrossReq):
    with _lock:
        return query.crosstab(get_con(), years=req.years, months=req.months,
                              categories=req.categories, note_kw=req.note, measure=req.measure)


@app.post("/api/detail")
def detail(req: DetailReq):
    with _lock:
        rows = query.detail(
            get_con(), years=req.years, months=req.months, categories=req.categories,
            note_kw=req.note, min_amount=req.min_amount, limit=req.limit,
        )
    return {"count": len(rows), "rows": rows}


# --------------------------- 源数据处理 ---------------------------
@app.get("/api/sources")
def list_sources():
    return {"files": ingest.list_source_files()}


@app.post("/api/sources/preview")
def preview_source(req: NameReq):
    try:
        return ingest.preview_source_file(_source_path(req.name), limit=req.limit)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/sources/parse")
def parse_source(req: NameReq):
    """把源文件按平台口径解析成规范四列（宽表自动 melt），返回预览 + 总量。"""
    try:
        return ingest.parse_source_file(_source_path(req.name), limit=req.limit)
    except HTTPException:                       # 交给 FastAPI（如 404 文件名非法/不存在）
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@app.post("/api/sources/parse/export")
def export_parsed(req: NameReq):
    """把「解析后的规范四列」导出为 CSV 数据文件。"""
    try:
        df = ingest.read_spending_table(_source_path(req.name))
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")

    csv_text = sqlconsole.result_to_csv(list(df.columns), df.values.tolist())
    stem = quote(f"{Path(req.name).stem}.parsed.csv")
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"parsed.csv\"; filename*=UTF-8''{stem}"},
    )


@app.delete("/api/sources")
def delete_source(name: str):
    _source_path(name).unlink()
    return {"deleted": name}


@app.post("/api/etl")
def run_etl_endpoint():
    """手动触发重新同步（ETL）。"""
    with _lock:
        return etl.run_etl(get_con())


@app.post("/api/ingest")
async def upload_ingest(file: UploadFile = File(...), mode: str = Form("append")):
    """上传 Excel/CSV/TXT 并导入 + 重跑 ETL。"""
    name = Path(file.filename or "upload.csv").name
    if Path(name).suffix.lower() not in ingest.SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="仅支持 " + " / ".join(ingest.SUPPORTED_SUFFIXES) + " 文件")
    if mode not in ("append", "replace"):
        raise HTTPException(status_code=400, detail="mode 只能是 append / replace")
    dest = config.INPUT_DIR / name
    dest.write_bytes(await file.read())
    with _lock:
        ing = ingest.ingest_file(get_con(), dest, mode=mode)
        stats = etl.run_etl(get_con())
    return {"ingest": ing, "etl": stats}


@app.post("/api/append/sql")
def append_sql(req: SqlAppendReq):
    """用 SQL 语句追加数据到原始层，然后重跑 ETL。"""
    try:
        with _lock:
            result = ingest.append_via_sql(get_con(), req.sql, dedup=req.dedup)
            stats = etl.run_etl(get_con())
        return {"append": result, "etl": stats}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


# --------------------------- SQL 工作台 ---------------------------
@app.get("/api/tables")
def api_tables():
    with _lock:
        return {"tables": sqlconsole.list_tables(get_con())}


@app.post("/api/table/preview")
def api_table_preview(req: NameReq):
    try:
        with _lock:
            return sqlconsole.preview_table(get_con(), req.name, limit=req.limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/sql")
def api_sql(req: SqlReq):
    """SQL 工作台：允许 SELECT 查询与 CREATE 建表；改数/删表被拒绝。"""
    try:
        with _lock:
            return sqlconsole.run_checked(get_con(), req.sql, limit=req.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                      # DuckDB 语法/执行错误
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@app.post("/api/sql/export")
def api_sql_export(req: SqlExportReq):
    """把查询结果导出为 CSV（仅 SELECT；带 BOM，Excel 直接打开不乱码）。"""
    try:
        with _lock:
            data = sqlconsole.run_checked(get_con(), req.sql, limit=req.limit,
                                          allowed=sqlconsole.READONLY_HEADS)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")

    queries = [r for r in data["results"] if r["type"] == "query"]
    if not queries:
        raise HTTPException(status_code=400, detail="没有可导出的查询结果")
    last = queries[-1]
    csv_text = sqlconsole.result_to_csv(last["columns"], last["rows"])
    filename = f"query_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/sql/save")
def api_sql_save(req: SqlSaveReq):
    """把查询结果保存为库内表（CREATE TABLE AS SELECT）。"""
    try:
        with _lock:
            return {"ok": True, **sqlconsole.save_as_table(
                get_con(), req.name, req.sql, replace=req.replace)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@app.exception_handler(Exception)
async def on_error(request, exc):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": str(exc)})
