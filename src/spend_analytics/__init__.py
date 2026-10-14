"""个人大数据分析平台 —— 花销分析核心包。

模块划分：
    config   全局路径与常量
    db       DuckDB 连接与建表（原始层/明细层/汇总层）
    ingest   数据接入：Excel/CSV -> raw_spending
    etl      ETL：raw_spending -> dwd_spending -> dws_monthly_category
    metrics  指标口径定义与查询（月总支出/分类占比/环比/笔均）
    query    自助分析查询构造器（维度 × 度量 × 筛选）
    report   面向终端场景的固定报表（趋势、占比、环比交叉表、明细）
"""

__version__ = "1.0.0"
__all__ = ["config", "db", "ingest", "etl", "metrics", "query", "report"]
