@echo off
chcp 65001 >nul
title RAG 知识库教学教具
cd /d "%~dp0"

echo.
echo  ============================================
echo    RAG 知识库教学教具  ·  启动中
echo  ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo  [X] 没有检测到 Python
    echo.
    echo      请先安装 Python 3.12（3.11 也行）：
    echo      https://www.python.org/downloads/release/python-3129/
    echo.
    echo      安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo  [X] Python 版本过低：本项目依赖 onnxruntime，要求 3.11 或更高。
    echo.
    python --version
    echo.
    echo      请安装 3.12（3.11 也行）：
    echo      https://www.python.org/downloads/release/python-3129/
    echo.
    pause
    exit /b 1
)

echo  首次启动会自动安装依赖并下载本地向量模型（约 90MB），
echo  之后每次启动都是秒开。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
echo  服务已停止。
pause
