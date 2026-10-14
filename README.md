# 个人花销分析平台

一个轻量的**个人月度花销分析平台**：把 Excel/CSV 花销表接入分析库，经过统一口径的 ETL 清洗与
聚合，最终通过**拖拽式自助分析界面**生成趋势、分类占比、环比对比等报表。

技术栈：**DuckDB + Python/pandas + FastAPI 自助分析界面**（另可选接入 Metabase）。

---

## 1. 需求对照

| 需求模块 | 功能 | 优先级 | 实现位置 |
| --- | --- | --- | --- |
| 数据接入 | 导入 Excel/CSV 花销表格 | P0 | `ingest.py` / Web「数据管理」 |
| 数据接入 | 支持追加新月份数据（按日期判重） | P0 | `ingest.ingest_file(mode="append")` |
| ETL | 日期格式统一、月份字段提取 | P0 | `etl.build_dwd` |
| ETL | 异常记录过滤（空值、负数、0） | P0 | `etl.run_etl` |
| ETL | 生成月度分类汇总表 | P0 | `etl.build_dws` |
| 指标管理 | 定义核心指标口径并文档化 | P0 | `docs/指标口径.md` / `metrics.py` |
| 自助分析 | 拖拽维度/度量生成报表 | P0 | Web 界面（`web/static/index.html`） |
| 自助分析 | 支持表格、折线图、饼图、柱状图 | P0 | Web 界面（ECharts） |
| 自助分析 | 支持按月份、类别筛选 | P1 | `query._build_filters` |
| 数据更新 | 手动触发重新同步 | P1 | `scripts/sync.py` / Web「重新同步」 |
| 查询加速 | 预聚合常用组合 | P2 | 汇总表 `dws_monthly_category` + mart 表 |

## 2. 数据模型

```
Excel/CSV
   │  数据接入（去重键：日期+类别+金额+备注）
   ▼
raw_spending        原始层：全 VARCHAR，保留脏数据痕迹
   │  ETL：日期标准化 / 金额清洗 / 类别规范化
   ▼
dwd_spending        明细层：spend_date, month, category, amount, note
   │  ETL：按 month + category 聚合
   ▼
dws_monthly_category 汇总层：month, category, total_amount, order_count
   │
   ▼
Web 自助分析 / Metabase
```

## 3. 目录结构

```
个人大数据分析平台/
├─ 需求.txt
├─ 初始化.bat / 启动.bat         # Windows 一键脚本
├─ requirements.txt / requirements-dev.txt
├─ pytest.ini / conftest.py / .gitignore
├─ README.md
├─ src/spend_analytics/          # 核心代码包
│  ├─ config.py / db.py          # 路径常量 / DuckDB 连接与建表
│  ├─ ingest.py                  # 数据接入 + 源文件列表/原样预览
│  ├─ etl.py                     # 清洗 + 聚合
│  ├─ metrics.py / query.py      # 指标口径 / 自助分析查询构造器
│  ├─ report.py                  # 场景化报表
│  ├─ sqlconsole.py              # SQL 工作台（查询/建表·保存为表 白名单 · CSV 导出 · 预览）
│  └─ cli.py                     # 命令行入口
├─ web/                          # Web 前端（三个页面）
│  ├─ app.py                     # FastAPI 后端
│  └─ static/
│     ├─ app.css  common.js      # 共用样式与工具函数
│     ├─ index.html  dashboard.js   # ① 数据大屏
│     ├─ source.html source.js      # ② 数据管理（文件接入 + SQL 工作台）
│     └─ charts.html charts.js      # ③ 图表工坊（内置指标 + 拖拽出图）
├─ scripts/
│  ├─ generate_sample_data.py    # 生成示例数据（含脏数据）
│  ├─ sync.py                    # 手动触发重新同步
│  ├─ export_sqlite.py           # 导出 SQLite（供 Metabase）
│  └─ setup_metabase.py          # 下载/启动 Metabase（可选）
├─ data/  input/ · exports/ · spend.duckdb · spend_mart.sqlite
├─ docs/指标口径.md
├─ metabase/README.md            # Metabase 接入说明（可选）
└─ tests/test_pipeline.py        # 验收测试（21 项）
```

## 4. 快速开始

### 方式一：Windows 一键脚本

1. 双击 **`初始化.bat`** —— 自动建虚拟环境、装依赖、生成示例数据、导入并跑 ETL。
2. 双击 **`启动.bat`** —— 启动 Web 界面，浏览器打开 <http://127.0.0.1:8000>。

### 方式二：命令行

```bash
# 1) 创建环境并安装依赖
uv venv --python 3.11 .venv
uv pip install --python .venv -r requirements.txt

# 2) 生成示例数据（可选，用于体验）
.venv/Scripts/python -m spend_analytics.cli gen-sample

# 3) 导入 + 跑 ETL（读取 data/input 下全部表格）
.venv/Scripts/python -m spend_analytics.cli sync

# 4) 启动自助分析界面
.venv/Scripts/python -m spend_analytics.cli serve
```

> 注：Windows 下用 `.venv\Scripts\python.exe`，Linux/macOS 用 `.venv/bin/python`。

## 5. 花销表格格式

把月度花销表放进 `data/input/`（`.xlsx` / `.xls` / `.csv` / `.txt`），至少包含以下列
（表头支持中英文别名：`日期/date`、`类别/category`、`金额/amount`、`备注/note`）：

| 日期 | 类别 | 金额 | 备注 |
| --- | --- | --- | --- |
| 2025-08-03 | 餐饮 | 45.50 | 午餐 |
| 2025/8/4 | 交通 | 12 | 地铁 |

导入规则：

- **追加模式（默认）**：按「日期+类别+金额+备注」判重，重复记录自动跳过，新月份直接累加；
- **替换模式**：先删除文件中出现月份的旧数据，再整月写入（用于修正已导入月份）；
- 表内重复行、空金额、负数（退款）、0 金额、非法日期都会在 ETL 阶段被过滤并分类计数。

## 6. 命令行速查

```bash
python -m spend_analytics.cli init                       # 初始化数据库
python -m spend_analytics.cli gen-sample                 # 生成示例数据
python -m spend_analytics.cli sync                       # 导入 + ETL（手动同步）
python -m spend_analytics.cli etl                        # 仅重跑 ETL
python -m spend_analytics.cli summary --month 2025-08    # 指标卡
python -m spend_analytics.cli query --dimension category --measure total_amount --month 2025-08
python -m spend_analytics.cli crosstab --month 2025-08   # 环比对比表
python -m spend_analytics.cli detail --min-amount 2000   # 明细追溯
python -m spend_analytics.cli export                     # 导出 SQLite（Metabase 用）
python -m spend_analytics.cli serve                      # 启动 Web 界面
```

`python scripts/sync.py --mode replace --file 某月.xlsx` 可用新文件覆盖指定月份。

## 7. Web 界面（三个页面）

顶部导航切换，三个页面各司其职：

### ① 数据大屏 `/`
- 指标卡：月总支出 / 有效笔数 / 笔均 / 环比 / 类别数（可切月份）
- 月度趋势折线、分类占比饼图、环比对比表、明细追溯
- **自助分析**：拖拽「维度 / 度量」到放置区 → 表格 / 折线 / 柱状 / 饼图，支持月份、类别、备注、金额筛选

### ② 数据管理 `/source`（文件接入 + SQL 工作台，子标签切换）
- **文件接入**：
  - 上传花销表格：选择文件或直接拖拽 `.xlsx / .xls / .csv / .txt`（txt/csv 自动识别编码与分隔符），追加（去重）或替换该月份
  - **SQL 追加**：直接用 SQL 语句追加数据（查询写法 / 写入写法，可勾选去重）
  - 已上传文件列表：文件名、行数、大小、修改时间，可**预览**（原样前 50 行）或**删除**
  - 数据分层概览（原始层 / 明细层 / 汇总层行数）+ **重新同步 (ETL)** 按钮
- **SQL 工作台**：库内表列表（点击预览前 100 行）、多语句编辑器（`Ctrl + Enter` 执行）、
  **支持 SELECT 查询与 CREATE 建表**（改数/删表会被拒绝），查询结果可**一键「保存为表」**落库
  或**导出 CSV**（带 BOM，Excel 直接打开不乱码）

> 旧的 `/sql` 链接会 307 重定向到 `/source`。

### ③ 图表工坊 `/charts`（拖拽生成图表）
- **内置指标**：10 个开箱即用的指标，**点一下或拖到画布**即出图
  （月度趋势 / 月度笔数 / 笔均趋势 / 分类占比 / 分类对比 / 分类笔数 / 星期分布 / 星期笔数 / 备注排行 / 分类×月份对比）
- **自定义图表**：拖「维度 / 度量」到放置区 + 选图形类型 → 添加到画布
- **全局筛选**：月份多选、类别多选、备注关键词、最小金额，对所有图表生效
- **画布**：可同时放多张图，每张可切换 柱状 / 折线 / 饼图 / 表格，可单独移除或清空
- 内置指标清单与后端维度/度量由测试校验一致，防止前后端漂移

> 维度：月份、类别、星期、备注关键词；度量：月总支出、笔数、笔均支出。

## 8. 指标口径

见 [`docs/指标口径.md`](docs/指标口径.md)。核心口径：

| 指标 | 计算逻辑 |
| --- | --- |
| 月总支出 | `SUM(amount) WHERE month = ?` |
| 分类支出 | `SUM(amount) GROUP BY category` |
| 分类占比 | 分类支出 / 月总支出 |
| 环比变化 | 本月月总支出 − 上月月总支出 |
| 笔均支出 | `SUM(amount) / COUNT(*)` |

约定：**有效记录 = 金额 > 0 且日期可解析**；退款（负数）当前不计入支出；月份按自然月。

## 9. 验收测试

```bash
.venv/Scripts/python -m pytest
```

覆盖需求第六章全部 8 项验收标准：数据导入记录数、ETL 清洗、汇总正确（与手工计算一致）、
口径一致、趋势序列、分类占比之和为 100%、环比对比表、常用查询 < 2 秒，共 76 个用例：

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `tests/test_pipeline.py` | 27 | 数据链路 / ETL / 指标口径 / 验收标准 / SQL 追加 |
| `tests/test_web_ui.py` | 35 | 三页面结构、导航互链、内置指标一致性、全部 API 契约、建表 / 保存为表 / 导出 |
| `tests/test_sqlconsole.py` | 14 | SQL 拆分、语句白名单（查询/建表放行，改数删表拒绝）、保存为表、CSV 导出、表预览 |

## 10. 可选：Metabase 自助分析

内置 Web 界面已覆盖自助分析需求。如仍希望使用 Metabase，先 `export` 导出 SQLite，
再运行 `python scripts/setup_metabase.py`。详见 [`metabase/README.md`](metabase/README.md)。

## 11. 已知限制

- 不做多人协作/权限、生产级调度告警、外部数据源、移动端（与需求「非目标」一致）。
- DuckDB 为单写者模式：**Web 服务运行时**命令行写操作会因文件锁冲突失败，请先停止服务再跑 CLI（读操作不受影响）。
- Metabase 为可选外部依赖，能否直连 SQLite 取决于其版本，详见 `metabase/README.md`。
