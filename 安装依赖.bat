@echo off
chcp 65001 >nul
title 安装依赖 - RAG 知识库教学教具
cd /d "%~dp0"

echo.
echo  ============================================
echo    安装依赖
echo    会自动在 6 个国内镜像间依次尝试，
echo    某个源超时就换下一个，不用手动改。
echo  ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo  [X] 没有检测到 Python
    echo.
    echo      请先安装 Python 3.11 或更高版本：
    echo      https://www.python.org/downloads/
    echo.
    echo      安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
echo  若上面提示「依赖导入失败」，把窗口里的完整报错发出来即可定位。
pause
