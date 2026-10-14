@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 个人花销分析平台

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [错误] 未找到虚拟环境 .venv
  echo 请先执行：
  echo     uv venv --python 3.11 .venv
  echo     uv pip install --python .venv -r requirements.txt
  pause
  exit /b 1
)

echo ============================================
echo   个人花销分析平台 - Web 自助分析界面
echo   启动后浏览器访问 http://127.0.0.1:8000
echo ============================================
"%PY%" -m spend_analytics.cli serve --port 8000
pause
