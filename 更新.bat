@echo off
chcp 65001 >nul
title 更新代码 - RAG 知识库教学教具
cd /d "%~dp0"

echo.
echo  ============================================
echo    更新代码（从 GitHub 拉最新版）
echo  ============================================
echo.

if not exist ".git" (
    echo  [X] 当前目录不是 git 仓库，没法自动更新。
    echo.
    echo      请到上一级目录，把 RAG-Learning-platform 文件夹删掉，
    echo      重新执行：
    echo      git clone https://github.com/Rhine9527123/RAG-Learning-platform.git
    echo.
    pause
    exit /b 1
)

git pull --ff-only
if errorlevel 1 (
    echo.
    echo  [X] 更新失败（本地有改动，或者网络不通）。
    echo      想直接用线上版本覆盖本地，执行下面两行：
    echo      git fetch origin
    echo      git reset --hard origin/main
    echo.
    pause
    exit /b 1
)

echo.
echo  [1/2] 代码已更新，接着检查依赖...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo  依赖没装好，把上面的红字发出来即可定位。
    pause
    exit /b 1
)

echo.
echo  [2/2] 全部就绪，现在双击 启动.bat 即可。
pause
