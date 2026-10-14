# Metabase 接入说明（可选）

本项目**内置的 Web 自助分析界面**（`python -m spend_analytics.cli serve`）已经覆盖了
需求中的自助分析场景：拖拽维度/度量、表格/折线/柱状/饼图、月份与类别筛选。

如果仍希望使用 Metabase 做拖拽分析，可通过下列任一方式接入：

## 方式 A：SQLite（最简单）

1. 导出数据：
   ```bash
   python -m spend_analytics.cli export
   # 生成 data/spend_mart.sqlite，含三层数据 + 三张 mart 表
   ```
2. 启动 Metabase：
   ```bash
   python scripts/setup_metabase.py
   ```
   浏览器打开 <http://localhost:3000> 完成初始化。
3. 添加数据库 → 选择 **SQLite**（若当前 Metabase 版本提供该驱动），
   文件路径填 `data/spend_mart.sqlite`。

> 不同 Metabase 版本对 SQLite 的内置支持不同，若列表中没有 SQLite，请用方式 B。

## 方式 B：DuckDB 社区驱动

1. 先复制一份只读数据库，避免 Metabase 与本地脚本争抢写锁：
   ```bash
   copy data\spend.duckdb data\spend_readonly.duckdb
   ```
2. 下载 DuckDB 驱动插件放到 `metabase/plugins/`，例如
   [metabase-duckdb-driver](https://github.com/motherduckdb/metabase_duckdb_driver)
   的 release jar。
3. 重启 Metabase，添加数据库时选择 **DuckDB**，路径填 `data/spend_readonly.duckdb`。

## 推荐用于分析的表

| 表 | 用途 |
| --- | --- |
| `dws_monthly_category` | 月 × 类别汇总（趋势、分类占比的基础） |
| `mart_monthly_total` | 月度总支出、笔数、笔均 |
| `mart_category_share` | 月度分类占比（饼图） |
| `mart_category_mom` | 月 × 类别环比（对比表） |
| `dwd_spending` | 逐笔明细（明细追溯） |

## 建图提示

- **月度趋势折线图**：`mart_monthly_total`，维度 `month`，指标 `total_amount`。
- **分类占比饼图**：`mart_category_share`，按 `month` 过滤，维度 `category`，指标 `total_amount`。
- **本月 vs 上月分类对比**：`mart_category_mom`，指标 `prev_amount` / `current_amount` / `delta`。
