# フロントエンド（Vite :5173）とバックエンド（FastAPI :8001）を常駐起動する。
# 既に待ち受け中のサーバーには触らないので、何度実行してもよい（タスクスケジューラから定期実行）。
# ※ 8000 は別プロジェクト（CoreDesk）が使用しているため、バックエンドは 8001 で起動する。

$root    = Split-Path -Parent $PSScriptRoot
$logDir  = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

function Test-Listening([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Listening 8001)) {
    $backend = Join-Path $root 'backend'
    Start-Process -FilePath (Join-Path $backend 'venv\Scripts\python.exe') `
        -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8001' `
        -WorkingDirectory $backend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'backend.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'backend.err.log')
}

if (-not (Test-Listening 5173)) {
    $frontend = Join-Path $root 'frontend'
    Start-Process -FilePath 'node' `
        -ArgumentList 'node_modules\vite\bin\vite.js' `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'frontend.err.log')
}
