"""生成示例花销数据（含脏数据），用于演示与验收测试。

产出：
    data/input/月度花销_2025年1-6月.csv    1~6 月数据（内含脏数据、重复行）
    data/input/月度花销_2025年7-8月.xlsx   7~8 月数据（用于演示“追加新月份”）

脏数据覆盖：空金额、负数(退款)、0 金额、空日期、类别含空格/大小写混杂、
金额含货币符号与千分位、多种日期格式（含 Excel 序列号风格）。
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import pandas as pd

# 项目根目录
BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"

# 类别 -> (每笔金额区间, 每月大致笔数)
CATEGORY_PROFILE = {
    "餐饮": ((15, 180), 26),
    "交通": ((3, 120), 18),
    "购物": ((50, 1500), 8),
    "娱乐": ((20, 600), 6),
    "居住": ((800, 3500), 2),
    "医疗": ((30, 900), 2),
    "通讯": ((30, 200), 3),
    "教育": ((100, 2000), 2),
    "其他": ((10, 500), 5),
}
NOTES = {
    "餐饮": ["午餐", "外卖", "咖啡", "聚餐", "早餐"],
    "交通": ["地铁", "打车", "公交", "高铁", "加油"],
    "购物": ["日用品", "服饰", "数码", "超市", "家居"],
    "娱乐": ["电影", "演出", "游戏", "健身"],
    "居住": ["房租", "物业", "水电"],
    "医疗": ["药品", "门诊", "体检"],
    "通讯": ["话费", "宽带", "会员"],
    "教育": ["网课", "书籍", "培训"],
    "其他": ["礼品", "捐赠", "杂项"],
}


def _month_dates(year: int, mon: int, rng: random.Random, n: int):
    days = (dt.date(year + (mon == 12), (mon % 12) + 1, 1) - dt.date(year, mon, 1)).days
    return [dt.date(year, mon, rng.randint(1, days)) for _ in range(n)]


def generate(months: list[str], seed: int = 42) -> pd.DataFrame:
    """生成指定月份区间的干净数据行（不含脏数据）。"""
    rng = random.Random(seed)
    rows = []
    for ym in months:
        year, mon = int(ym[:4]), int(ym[5:7])
        for cat, ((lo, hi), base_n) in CATEGORY_PROFILE.items():
            n = max(1, base_n + rng.randint(-2, 2))
            for d in _month_dates(year, mon, rng, n):
                rows.append({
                    "日期": d.strftime("%Y-%m-%d"),
                    "类别": cat,
                    "金额": f"{round(rng.uniform(lo, hi), 2):.2f}",
                    "备注": rng.choice(NOTES[cat]),
                })
    df = pd.DataFrame(rows)
    return df.sort_values("日期").reset_index(drop=True)


def dirty_rows() -> pd.DataFrame:
    """构造各种脏数据行，用于验证 ETL 清洗规则。"""
    return pd.DataFrame([
        {"日期": "2025-03-05", "类别": " 餐饮 ", "金额": "88.00", "备注": "类别含空格"},
        {"日期": "2025/3/08", "类别": "food", "金额": "￥1,280.00", "备注": "货币符号+千分位"},
        {"日期": "2025.03.09", "类别": "SHOPPING", "金额": "260.50", "备注": "点分日期"},
        {"日期": "20250310", "类别": "交通", "金额": "12.00", "备注": "紧凑日期"},
        {"日期": "2025-03-11 00:00:00", "类别": "娱乐", "金额": "199.00", "备注": "Excel 时间戳"},
        # 应被过滤
        {"日期": "2025-03-12", "类别": "餐饮", "金额": "", "备注": "空金额"},
        {"日期": "2025-03-13", "类别": "购物", "金额": "-120.00", "备注": "退款(负数)"},
        {"日期": "2025-03-14", "类别": "交通", "金额": "0", "备注": "0 金额"},
        {"日期": "", "类别": "医疗", "金额": "300.00", "备注": "空日期"},
        {"日期": "not-a-date", "类别": "其他", "金额": "50.00", "备注": "非法日期"},
    ])


def build_dataset(months: list[str], with_dirty: bool = True, seed: int = 42) -> pd.DataFrame:
    """干净数据 + 脏数据（可选）+ 少量重复行（验证去重）。"""
    df = generate(months, seed=seed)
    if with_dirty:
        df = pd.concat([df, dirty_rows()], ignore_index=True)
        # 复制两行制造完全重复，验证追加去重
        df = pd.concat([df, df.iloc[[5, 6]]], ignore_index=True)
    return df.reset_index(drop=True)


def write_files() -> dict:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    m1 = [f"2025-{m:02d}" for m in range(1, 7)]
    m2 = ["2025-07", "2025-08"]

    df_a = build_dataset(m1)
    df_b = build_dataset(m2, with_dirty=False)

    path_a = INPUT_DIR / "月度花销_2025年1-6月.csv"
    path_b = INPUT_DIR / "月度花销_2025年7-8月.xlsx"
    df_a.to_csv(path_a, index=False, encoding="utf-8-sig")
    df_b.to_excel(path_b, index=False)

    return {"csv": str(path_a), "xlsx": str(path_b),
            "rows_a": len(df_a), "rows_b": len(df_b)}


if __name__ == "__main__":
    info = write_files()
    for k, v in info.items():
        print(f"{k}: {v}")
