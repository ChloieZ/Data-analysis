"""全局配置：目录、数据库路径、常量。

所有路径都基于项目根目录（src/spend_analytics/ 的上两级）计算，
也可通过环境变量 SPEND_DB / SPEND_SQLITE 覆盖数据库位置。
"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根目录：.../个人大数据分析平台
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"          # 存放待导入的花销表格
EXPORT_DIR = DATA_DIR / "exports"       # 导出的报表
WEB_DIR = BASE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"

DB_PATH = Path(os.environ.get("SPEND_DB", DATA_DIR / "spend.duckdb"))
SQLITE_PATH = Path(os.environ.get("SPEND_SQLITE", DATA_DIR / "spend_mart.sqlite"))

# 三大数据层表名
RAW_TABLE = "raw_spending"              # 原始层
DWD_TABLE = "dwd_spending"              # 明细层
DWS_TABLE = "dws_monthly_category"      # 汇总层（月 × 类别）

# 源表格列名（中文，与需求一致）与可能的英文/别名
COL_DATE = "日期"
COL_CATEGORY = "类别"
COL_AMOUNT = "金额"
COL_NOTE = "备注"

for _d in (DATA_DIR, INPUT_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
