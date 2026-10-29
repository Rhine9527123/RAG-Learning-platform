# 一键安装：创建虚拟环境 + 用国内镜像装依赖
# 注意：本文件必须保存为 UTF-8 with BOM（Windows PowerShell 5.1 无 BOM 时按 GBK 读取，中文会导致解析崩溃）
# 用法：右键「使用 PowerShell 运行」，或在终端执行
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
$mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"

Write-Host "==> 当前目录：$PSScriptRoot"
Set-Location $PSScriptRoot

if (Test-Path ".venv") {
    Write-Host "==> 已存在 .venv，跳过创建"
} else {
    Write-Host "==> 创建虚拟环境 .venv"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv .venv --python 3.11
    } else {
        python -m venv .venv
    }
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "虚拟环境创建失败，找不到 $py" }

Write-Host "==> 使用清华镜像安装依赖：$mirror"
$env:UV_DEFAULT_INDEX = $mirror
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv pip install --python $py -r requirements.txt --index-url $mirror
} else {
    & $py -m pip install --upgrade pip -i $mirror
    & $py -m pip install -r requirements.txt -i $mirror
}

# 预下载本地向量模型，避免第一次建库时干等
Write-Host ""
Write-Host "==> 预下载本地向量模型（约 90MB，走 hf-mirror 镜像，只需一次）" -ForegroundColor Cyan
try {
    # 用字面量 here-string（@'...'@）包 Python 代码：PowerShell 不做变量展开，
    # 且整体保持纯 ASCII —— PS 5.1 向原生程序传参不走 UTF-8，中文会变乱码
    & $py -c @'
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'
from fastembed import TextEmbedding
from pathlib import Path
cache = Path('data/models/fastembed'); cache.mkdir(parents=True, exist_ok=True)
TextEmbedding('BAAI/bge-small-zh-v1.5', cache_dir=str(cache))
print('model ready')
'@
    Write-Host "==> 本地向量模型已就绪" -ForegroundColor Green
} catch {
    Write-Host "模型预下载失败（不影响使用，首次建库时会自动重试）：$_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==> 安装完成。启动命令：" -ForegroundColor Green
Write-Host "    .\run.ps1" -ForegroundColor Green
