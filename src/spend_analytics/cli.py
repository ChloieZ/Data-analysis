"""命令行入口：数据接入 / ETL / 指标查询 / 自助分析 / 导出 / 启动 Web。

用法示例：
    python -m spend_analytics.cli init
    python -m spend_analytics.cli gen-sample
    python -m spend_analytics.cli sync                 # 导入 data/input 全部文件并跑 ETL
    python -m spend_analytics.cli etl                   # 仅重跑 ETL
    python -m spend_analytics.cli summary --month 2025-03
    python -m spend_analytics.cli query --dimension category --measure total_amount --month 2025-03
    python -m spend_analytics.cli detail --month 2025-03 --min-amount 500
    python -m spend_analytics.cli serve
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config, db, etl, ingest, metrics, query, report


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _open():
    con = db.connect()
    db.init_schema(con)
    return con


def cmd_init(args):
    con = _open()
    _print_json({"db": str(config.DB_PATH), **db.table_counts(con)})


def cmd_gen_sample(args):
    sys.path.insert(0, str(config.BASE_DIR))
    from scripts.generate_sample_data import write_files
    _print_json(write_files())


def cmd_ingest(args):
    con = _open()
    _print_json(ingest.ingest_file(con, args.file, mode=args.mode))


def cmd_ingest_dir(args):
    con = _open()
    _print_json(ingest.ingest_directory(con, args.dir, mode=args.mode))


def cmd_etl(args):
    con = _open()
    _print_json(etl.run_etl(con))


def cmd_sync(args):
    """手动触发重新同步：导入 + ETL。"""
    con = _open()
    if args.file:
        ing = [ingest.ingest_file(con, args.file, mode=args.mode)]
    else:
        ing = ingest.ingest_directory(con, args.dir, mode=args.mode)
    stats = etl.run_etl(con)
    _print_json({"ingest": ing, "etl": stats})


def cmd_summary(args):
    con = _open()
    _print_json(metrics.summary(con, args.month))


def cmd_months(args):
    con = _open()
    _print_json({"months": metrics.list_months(con), "categories": metrics.list_categories(con)})


def cmd_query(args):
    con = _open()
    months = args.month or (list(metrics.list_months(con)[-1:]) if not args.all else None)
    result = query.chart_data(
        con, args.dimension, args.measure,
        months=months, categories=args.category,
        note_kw=args.note, min_amount=args.min_amount,
    )
    _print_json(result)


def cmd_crosstab(args):
    con = _open()
    months = args.month or None
    _print_json(query.crosstab(con, months=months, measure=args.measure))


def cmd_detail(args):
    con = _open()
    rows = query.detail(con, months=args.month, categories=args.category,
                        note_kw=args.note, min_amount=args.min_amount, limit=args.limit)
    _print_json({"count": len(rows), "rows": rows})


def cmd_dashboard(args):
    con = _open()
    _print_json(report.dashboard(con, args.month))


def cmd_export(args):
    from scripts.export_sqlite import export_all
    con = _open()
    _print_json(export_all(con, args.path))


def cmd_serve(args):
    import uvicorn
    uvicorn.run("web.app:app", host=args.host, port=args.port, reload=args.reload,
                app_dir=str(config.BASE_DIR))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spend-analytics", description="个人花销分析平台 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化数据库与表结构").set_defaults(func=cmd_init)
    sub.add_parser("gen-sample", help="生成示例数据到 data/input").set_defaults(func=cmd_gen_sample)

    pi = sub.add_parser("ingest", help="导入单个文件到原始层")
    pi.add_argument("file")
    pi.add_argument("--mode", choices=["append", "replace"], default="append")
    pi.set_defaults(func=cmd_ingest)

    pid = sub.add_parser("ingest-dir", help="导入目录下全部文件")
    pid.add_argument("--dir", default=None)
    pid.add_argument("--mode", choices=["append", "replace"], default="append")
    pid.set_defaults(func=cmd_ingest_dir)

    sub.add_parser("etl", help="重跑 ETL（清洗 + 聚合）").set_defaults(func=cmd_etl)

    ps = sub.add_parser("sync", help="手动同步：导入 + ETL")
    ps.add_argument("--file", default=None, help="只同步单个文件（默认同步 data/input 全部）")
    ps.add_argument("--dir", default=None)
    ps.add_argument("--mode", choices=["append", "replace"], default="append")
    ps.set_defaults(func=cmd_sync)

    pm = sub.add_parser("summary", help="查看某月指标卡")
    pm.add_argument("--month", default=None)
    pm.set_defaults(func=cmd_summary)

    sub.add_parser("months", help="列出所有月份与类别").set_defaults(func=cmd_months)

    pq = sub.add_parser("query", help="自助查询：维度 × 度量")
    pq.add_argument("--dimension", required=True, choices=list(query.DIMENSIONS))
    pq.add_argument("--measure", required=True, choices=list(query.MEASURES))
    pq.add_argument("--month", action="append", default=None)
    pq.add_argument("--category", action="append", default=None)
    pq.add_argument("--note", default=None)
    pq.add_argument("--min-amount", type=float, default=None)
    pq.add_argument("--all", action="store_true", help="不限制月份")
    pq.set_defaults(func=cmd_query)

    pc = sub.add_parser("crosstab", help="月份 × 类别 交叉表")
    pc.add_argument("--month", action="append", default=None)
    pc.add_argument("--measure", default="total_amount", choices=list(query.MEASURES))
    pc.set_defaults(func=cmd_crosstab)

    pd_ = sub.add_parser("detail", help="明细查询")
    pd_.add_argument("--month", action="append", default=None)
    pd_.add_argument("--category", action="append", default=None)
    pd_.add_argument("--note", default=None)
    pd_.add_argument("--min-amount", type=float, default=None)
    pd_.add_argument("--limit", type=int, default=200)
    pd_.set_defaults(func=cmd_detail)

    pdb = sub.add_parser("dashboard", help="输出看板数据")
    pdb.add_argument("--month", default=None)
    pdb.set_defaults(func=cmd_dashboard)

    pe = sub.add_parser("export", help="导出为 SQLite（供 Metabase 使用）")
    pe.add_argument("--path", default=None)
    pe.set_defaults(func=cmd_export)

    pv = sub.add_parser("serve", help="启动 Web 自助分析界面")
    pv.add_argument("--host", default="127.0.0.1")
    pv.add_argument("--port", type=int, default=8000)
    pv.add_argument("--reload", action="store_true")
    pv.set_defaults(func=cmd_serve)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
