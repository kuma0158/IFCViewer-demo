# フロントエンド（:5173）とバックエンド（FastAPI :8001）を常駐起動する。
# 既に待ち受け中のサーバーには触らないので、何度実行してもよい（タスクスケジューラから定期実行）。
# ※ 8000 は別プロジェクト（CoreDesk）が使用しているため、バックエンドは 8001 で起動する。
#
# フロントエンドは既定で本番モード（npm run build でビルドし、dist/ を vite preview で配信）。
# 開発サーバー（ソース変更が即時反映される）で動かすときは -Dev を付ける:
#   powershell -File scripts\start-servers.ps1 -Dev
# ※ どちらのモードでも 5173 番を使う（Cloudflare Tunnel の転送先を変えずに済むように）。
#    モードを切り替えるときは、先に 5173 番のプロセスを止めてから実行する。
param([switch]$Dev)

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
    $vite = 'node_modules\vite\bin\vite.js'

    if ($Dev) {
        $viteArgs = @($vite)
    } else {
        # 型チェック → ビルド。失敗したら（型エラー等）前回の dist/ があればそれで起動し、無ければ起動しない
        Push-Location $frontend
        try {
            & npm.cmd run build *> (Join-Path $logDir 'frontend.build.log')
            $built = ($LASTEXITCODE -eq 0)
        } finally {
            Pop-Location
        }
        if (-not $built) {
            if (-not (Test-Path (Join-Path $frontend 'dist\index.html'))) {
                Write-Error "フロントエンドのビルドに失敗しました。logs\frontend.build.log を確認してください。"
                exit 1
            }
            Write-Warning "ビルドに失敗したため、前回の dist/ で起動します。logs\frontend.build.log を確認してください。"
        }
        $viteArgs = @($vite, 'preview')
    }

    Start-Process -FilePath 'node' `
        -ArgumentList $viteArgs `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') `
        -RedirectStandardError  (Join-Path $logDir 'frontend.err.log')
}
