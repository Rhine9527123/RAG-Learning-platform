# 一键启动
# 用法：powershell -ExecutionPolicy Bypass -File .\run.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "还没安装依赖，正在自动执行 setup.ps1 ..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup.ps1")
}

Write-Host "==> 启动 RAG 教学教具，浏览器会自动打开 http://localhost:8501" -ForegroundColor Green
& $py -m streamlit run app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false
