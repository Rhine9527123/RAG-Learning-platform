# 一键安装：创建虚拟环境 + 装依赖（自动在 6 个镜像间回退）
# 注意：本文件必须保存为 UTF-8 with BOM（Windows PowerShell 5.1 无 BOM 时按 GBK 读取，中文会导致解析崩溃）
# 用法：双击 安装依赖.bat，或在 PowerShell 里执行
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 用 Continue 而不是 Stop：pip 失败要靠 $LASTEXITCODE 判断，Stop 会提前中断整个循环
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

# stderr 一律写文件：PS 5.1 会把原生命令的 stderr 渲染成红色报错，
# 而 pip 只是提示「有新版本」也会走 stderr，成功却看起来像失败。
$errLog = Join-Path $env:TEMP "rag_setup_err.log"

function Show-ErrTail([int]$n) {
    if (Test-Path $errLog) {
        Write-Host "    ---- 失败原因（最后 $n 行）----" -ForegroundColor DarkGray
        Get-Content $errLog -Tail $n -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "    $_" -ForegroundColor DarkGray
        }
    }
}

Write-Host "==> 当前目录：$PSScriptRoot"

if (Test-Path ".venv") {
    Write-Host "==> 已存在 .venv，跳过创建（想重建就先删掉 .venv 目录）"
} else {
    Write-Host "==> 创建虚拟环境 .venv"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败：python -m venv 返回 $LASTEXITCODE" }
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "虚拟环境创建失败，找不到 $py" }

# ---- 先确保 pip 可用 ----
# uv 创建的 venv 默认不带 pip；Python 安装时也可能没有。
# 没有 pip 时直接跑 pip install，会被误报成「所有镜像都失败」。
$null = & $py -m pip --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> 虚拟环境里没有 pip，用 ensurepip 补装（标准库自带，不需要联网）" -ForegroundColor Yellow
    & $py -m ensurepip --upgrade --default-pip 2>$errLog
    if ($LASTEXITCODE -ne 0) { Show-ErrTail 10 }
    $null = & $py -m pip --version 2>$null
}

$hasPip = ($LASTEXITCODE -eq 0)
$hasUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)

if ($hasPip) {
    Write-Host "==> pip 就绪"
} elseif ($hasUv) {
    Write-Host "==> 没有 pip，但有 uv，改用 uv 安装" -ForegroundColor Yellow
} else {
    Write-Host "==> 既没有 pip 也没有 uv，无法安装依赖" -ForegroundColor Red
    Write-Host "    请装好 Python 后删掉 .venv 目录重新运行本脚本" -ForegroundColor Red
    exit 1
}

# ---- 镜像列表：按顺序尝试，第一个装成功就停 ----
# 单一点源在国内网络下经常 ReadTimeout，必须有回退。
$mirrors = @(
    @{ name = "清华";   url = "https://pypi.tuna.tsinghua.edu.cn/simple" },
    @{ name = "阿里云"; url = "https://mirrors.aliyun.com/pypi/simple" },
    @{ name = "腾讯云"; url = "https://mirrors.cloud.tencent.com/pypi/simple" },
    @{ name = "华为云"; url = "https://repo.huaweicloud.com/repository/pypi/simple" },
    @{ name = "中科大"; url = "https://mirrors.ustc.edu.cn/pypi/simple" },
    @{ name = "官方";   url = "https://pypi.org/simple" }
)

$installed = $false
$usedMirror = ""
foreach ($m in $mirrors) {
    Write-Host ""
    Write-Host "==> 用 $($m.name) 镜像安装依赖：$($m.url)" -ForegroundColor Cyan

    if ($hasPip) {
        # timeout/retries 调小：某个源不通时要快速失败，好尽快换下一个
        & $py -m pip install -r requirements.txt -i $m.url --timeout 30 --retries 1 2>$errLog
    } else {
        & uv pip install --python $py -r requirements.txt --index-url $m.url 2>$errLog
    }

    if ($LASTEXITCODE -eq 0) {
        $installed = $true
        $usedMirror = $m.name
        break
    }
    Write-Host "==> $($m.name) 失败（退出码 $LASTEXITCODE），换下一个镜像" -ForegroundColor Yellow
    Show-ErrTail 8
}

if (-not $installed) {
    Write-Host ""
    Write-Host "==> 6 个镜像全部失败，请检查网络后重试" -ForegroundColor Red
    Write-Host "    也可以手动指定镜像：" -ForegroundColor Red
    Write-Host "    .\.venv\Scripts\python.exe -m pip install -r requirements.txt -i <镜像地址>" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==> 依赖安装完成（$usedMirror）" -ForegroundColor Green

# ---- 装完必须自检 ----
# pip 返回 0 也可能有包没装全（中途中断过），只有导入成功才算能用。
# 这一步直接对应报错「No module named streamlit」。
Write-Host "==> 自检：导入关键依赖"
& $py -c "import streamlit, llama_index.core, fastembed; print('deps ok')" 2>$errLog
if ($LASTEXITCODE -ne 0) {
    Show-ErrTail 20
    Write-Host "==> 依赖导入失败，请重跑本脚本；仍失败就删掉 .venv 目录再来一次" -ForegroundColor Red
    exit 1
}

# ---- 预下载本地向量模型 ----
Write-Host ""
Write-Host "==> 预下载本地向量模型（约 90MB，走 hf-mirror 镜像，只需一次）"
Write-Host "    首次下载可能要等一两分钟，期间没有输出是正常的。"
try {
    # 字面量 here-string（@'...'@）+ 纯 ASCII：PS 5.1 向原生程序传参不走 UTF-8
    & $py -c @'
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET'] = '1'
from fastembed import TextEmbedding
from pathlib import Path
cache = Path('data/models/fastembed'); cache.mkdir(parents=True, exist_ok=True)
TextEmbedding('BAAI/bge-small-zh-v1.5', cache_dir=str(cache))
print('model ready')
'@ 2>$errLog
    if ($LASTEXITCODE -ne 0) { throw "模型下载返回 $LASTEXITCODE" }
    Write-Host "==> 本地向量模型已就绪" -ForegroundColor Green
} catch {
    Write-Host "模型预下载失败（不影响使用，首次建库时会自动重试）" -ForegroundColor Yellow
    Show-ErrTail 10
}

Write-Host ""
Write-Host "==> 全部就绪。启动前端：" -ForegroundColor Green
Write-Host "    双击 启动.bat     或者执行 .\run.ps1" -ForegroundColor Green
