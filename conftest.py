"""pytest 配置：把项目根目录与 src 加入模块搜索路径。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)
