@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 个人花销分析平台 - 一键初始化

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [1/4] 创建虚拟环境...
  uv venv --python 3.11 .venv || (echo 创建失败 & pause & exit /b 1)
  echo [2/4] 安装依赖...
  uv pip install --python .venv -r requirements.txt || (echo 安装失败 & pause & exit /b 1)
)

echo [3/4] 生成示例数据...
"%PY%" -m spend_analytics.cli gen-sample || (echo 生成失败 & pause & exit /b 1)

echo [4/4] 导入 + ETL 同步...
"%PY%" -m spend_analytics.cli sync || (echo 同步失败 & pause & exit /b 1)

echo.
echo 初始化完成！双击「启动.bat」打开自助分析界面。
pause
