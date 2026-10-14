"""一键获取并启动 Metabase（可选的自助分析后端）。

Metabase 是一个开源的拖拽式 BI 工具。本项目内置的 Web 界面已覆盖自助分析需求，
如仍希望使用 Metabase，可用本脚本：

    1. 先把数据导出为 SQLite：python -m spend_analytics.cli export
    2. 下载 metabase.jar 并启动：python scripts/setup_metabase.py
    3. 浏览器打开 http://localhost:3000，添加数据库时选择对应驱动：
         - 若 Metabase 版本内置 SQLite 驱动：选择 SQLite，文件指向 data/spend_mart.sqlite
         - 否则安装 DuckDB 社区驱动（见 metabase/plugins/README），指向 data/spend.duckdb 只读副本

注意：不同 Metabase 版本对 SQLite 的支持不同，请以官方文档为准。
本脚本仅负责下载与启动，不修改数据库。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
MB_DIR = BASE_DIR / "metabase"
JAR = MB_DIR / "metabase.jar"
DEFAULT_URL = "https://downloads.metabase.com/latest/metabase.jar"


def download(url: str = DEFAULT_URL, force: bool = False) -> Path:
    MB_DIR.mkdir(parents=True, exist_ok=True)
    (MB_DIR / "plugins").mkdir(exist_ok=True)
    if JAR.exists() and not force:
        print(f"已存在: {JAR}（如需重新下载请加 --force）")
        return JAR
    print(f"正在下载 Metabase：{url}")
    print("（约 400MB，请耐心等待；如网络受限可手动下载后放到 metabase/ 目录）")
    with urllib.request.urlopen(url, timeout=60) as resp, open(JAR, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    print(f"下载完成: {JAR}")
    return JAR


def run(jar: Path, port: int = 3000) -> None:
    import subprocess

    java = shutil.which("java")
    if not java:
        print("未找到 java，请先安装 JDK/JRE 17+ 并加入 PATH。", file=sys.stderr)
        sys.exit(1)
    print(f"启动 Metabase：http://localhost:{port}")
    subprocess.run([java, "-jar", str(jar), "--port", str(port)], check=False,
                   cwd=str(MB_DIR))


def main():
    ap = argparse.ArgumentParser(description="下载并启动 Metabase")
    ap.add_argument("--url", default=DEFAULT_URL, help="metabase.jar 下载地址")
    ap.add_argument("--port", type=int, default=3000)
    ap.add_argument("--force", action="store_true", help="强制重新下载")
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()

    jar = download(args.url, force=args.force)
    if not args.download_only:
        run(jar, args.port)


if __name__ == "__main__":
    main()
