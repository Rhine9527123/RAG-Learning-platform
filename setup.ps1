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

# ---------------------------------------------------------------
# 前置检查：确认手上不是旧版代码
# ---------------------------------------------------------------
# 旧版 requirements.txt 依赖 llama-index-embeddings-fastembed，
# 而这个包只发布到 Python <3.13。用户忘记更新代码就直接重装时，
# 会看到一堆「找不到包」的报错，却以为是环境问题 —— 这里直接说清原因。
$reqFile = Join-Path $PSScriptRoot "requirements.txt"
if ((Test-Path -LiteralPath $reqFile) -and
    (Select-String -LiteralPath $reqFile -Pattern "llama-index-embeddings-fastembed" -Quiet)) {
    Write-Host ""
    Write-Host "  [X] 这是旧版代码：requirements.txt 里还写着 llama-index-embeddings-fastembed。" -ForegroundColor Red
    Write-Host "      该包最高只发布到 Python 3.12，在 3.13 / 3.14 上必然装不上，继续装没有意义。" -ForegroundColor Red
    Write-Host ""
    Write-Host "      先更新代码，再装依赖：" -ForegroundColor Yellow
    Write-Host "      双击 更新.bat（或在仓库目录执行 git pull），然后重新双击 安装依赖.bat。" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------
# 挑一个能用的 Python 解释器
# ---------------------------------------------------------------
# 为什么必须挑：onnxruntime 和 streamlit 都要求 >= 3.11；
# 3.14 还没有对应的预编译轮子，pip 会报 No matching distribution。
# 所以只在 3.11 / 3.12 / 3.13 里挑，优先 3.12（依赖轮子最全）。
# 双系统上都装了 Python 时，PATH 里那个未必可用，用 py 启动器把所有版本列出来再挑。
$MIN_VER = [version]"3.11"
$MAX_VER = [version]"3.14"

function Get-PyVersion([string]$exe) {
    if (-not $exe) { return $null }
    if (-not (Test-Path -LiteralPath $exe)) { return $null }
    $out = & $exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $line = ($out | Select-Object -Last 1)
    if (-not $line) { return $null }
    try { return [version]$line.Trim() } catch { return $null }
}

function Get-Rank([version]$v) {
    if ($v.Major -ne 3) { return 9 }
    switch ($v.Minor) {
        12 { return 0 }
        11 { return 1 }
        13 { return 2 }
        default { return 9 }
    }
}

$cands = New-Object System.Collections.ArrayList
$pathPy = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pathPy) { [void]$cands.Add($pathPy.Source) }
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    foreach ($line in (& py -0p 2>$null)) {
        if ("$line" -match '([A-Za-z]:\\.*?python\.exe)') { [void]$cands.Add($matches[1]) }
    }
}

$seen = @{}
$found = @()
foreach ($c in $cands) {
    if (-not $c) { continue }
    $key = "$c".ToLower()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    $v = Get-PyVersion $c
    if ($v) { $found += [pscustomobject]@{ Exe = $c; Ver = $v } }
}

if ($found.Count -gt 0) {
    Write-Host "==> 本机检测到的 Python：" -ForegroundColor DarkGray
    foreach ($f in ($found | Sort-Object Ver -Descending)) {
        Write-Host ("    {0,-9} {1}" -f $f.Ver, $f.Exe) -ForegroundColor DarkGray
    }
}

$usable = $found | Where-Object { $_.Ver -ge $MIN_VER -and $_.Ver -lt $MAX_VER }
$pick = $usable | Sort-Object @{ Expression = { Get-Rank $_.Ver } }, @{ Expression = { $_.Ver }; Descending = $true } | Select-Object -First 1

if (-not $pick) {
    Write-Host ""
    Write-Host "  [X] 没有找到可用的 Python 解释器（需要 3.11 / 3.12 / 3.13）" -ForegroundColor Red
    $tooNew = $found | Where-Object { $_.Ver -ge $MAX_VER } | Sort-Object Ver -Descending | Select-Object -First 1
    if ($tooNew) {
        Write-Host ("      检测到的是 Python {0}，太新了：llama-index 那套依赖在 {1} 上还凑不齐" -f $tooNew.Ver, $tooNew.Ver) -ForegroundColor Red
        Write-Host "      （3.13 已经可以，3.14 目前装不全）。" -ForegroundColor Red
    } elseif ($found.Count -eq 0) {
        Write-Host "      本机没装 Python，或者装了但没有加进 PATH。" -ForegroundColor Red
    } else {
        Write-Host "      检测到的 Python 都不在 3.11 ~ 3.13 之间，装不上依赖。" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "      请装 3.12（3.11 也行），装完重跑本脚本：" -ForegroundColor Yellow
    Write-Host "      https://www.python.org/downloads/release/python-3129/" -ForegroundColor Yellow
    Write-Host "      安装时务必勾选 Add python.exe to PATH。" -ForegroundColor Yellow
    Write-Host "      如果项目里已有 .venv 目录，先删掉它（旧环境版本不对，留着也不会成功）。" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host ("==> 本次使用 Python {0}" -f $pick.Ver) -ForegroundColor Green
Write-Host ("    {0}" -f $pick.Exe) -ForegroundColor DarkGray

$venvDir = Join-Path $PSScriptRoot ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"

# 已有的 .venv 版本不对就删掉重建，否则后面装依赖必然失败
if (Test-Path -LiteralPath $venvPy) {
    $venvVer = Get-PyVersion $venvPy
    $badVenv = (-not $venvVer) -or ($venvVer -lt $MIN_VER) -or ($venvVer -ge $MAX_VER)
    if ($badVenv) {
        Write-Host ("==> 现有 .venv 是 Python {0}，不在支持范围，删掉重建" -f $venvVer) -ForegroundColor Yellow
        Remove-Item -LiteralPath $venvDir -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $venvPy) {
    Write-Host "==> 复用已有 .venv（想重建就先删掉 .venv 目录）"
} else {
    Write-Host "==> 创建虚拟环境 .venv"
    & $pick.Exe -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
        throw "创建虚拟环境失败：python -m venv 返回 $LASTEXITCODE"
    }
}

$py = $venvPy
if (-not (Test-Path -LiteralPath $py)) { throw "虚拟环境创建失败，找不到 $py" }

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
& $py -c "import streamlit, llama_index.core, fastembed, jieba; from core.local_embed import FastEmbedLocalEmbedding; print('deps ok')" 2>$errLog
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
Write-Host "==> 全部就绪（Python $($pick.Ver)）。启动前端：" -ForegroundColor Green
Write-Host "    双击 启动.bat     或者执行 .\run.ps1" -ForegroundColor Green
