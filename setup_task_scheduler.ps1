# コンテキスト収集＋GitHub Pagesデプロイ を毎朝8時に自動実行するタスクを登録する
# 管理者権限不要（現在のユーザーのタスクとして登録）
#
# ラズパイ→Windows移行時の注意点を踏まえ、以下もまとめて実施：
#   1. 依存パッケージの確認・インストール（Task Scheduler環境向けにシステムパスへ）
#   2. SSL証明書エラーの回避確認
#   3. git 認証確認

$TaskName = "ContextCollector_DailyRun"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatFile   = Join-Path $ScriptDir "run_collection.bat"
$Python    = "C:\Python314\python.exe"

Write-Host ""
Write-Host "========================================="
Write-Host "  コンテキスト収集 Windows セットアップ"
Write-Host "========================================="
Write-Host ""

# =========================================================
# Step 1: Python の存在確認
# =========================================================
Write-Host "[1/5] Python 確認..."
if (-not (Test-Path $Python)) {
    Write-Error "Python が見つかりません: $Python"
    Write-Host "  → Python 3.x をインストールして再実行してください"
    exit 1
}
$ver = & $Python --version 2>&1
Write-Host "  OK: $ver"

# =========================================================
# Step 2: 依存パッケージを system site-packages にインストール
#         （Task Scheduler は APPDATA を参照しないためユーザーパス不可）
# =========================================================
Write-Host ""
Write-Host "[2/5] 依存パッケージのインストール..."
$packages = @(
    "requests",
    "beautifulsoup4",
    "lxml",           # Google News RSS の XML パースに必須
    "pillow",
    "pystray",
    "pywin32",        # winshell の依存
    "winshell",
    "markdown",
    "flask"
)

foreach ($pkg in $packages) {
    $result = & $Python -m pip install $pkg 2>&1 | Select-String "Successfully installed|already satisfied"
    if ($result) {
        Write-Host "  $pkg : $($result.Line.Trim())"
    } else {
        Write-Host "  $pkg : 確認済み"
    }
}

# pywin32 の post-install スクリプトを実行（win32com 等の初期化）
Write-Host "  pywin32 post-install を実行中..."
& $Python -m pywin32_postinstall -install 2>&1 | Out-Null
Write-Host "  OK"

# =========================================================
# Step 3: SSL接続テスト（Windows では certifi だけでは不足する場合あり）
#         Context.py では session.verify=False で回避済み
# =========================================================
Write-Host ""
Write-Host "[3/5] ネットワーク・SSL 確認..."
$sslTest = & $Python -c @"
import urllib3; urllib3.disable_warnings()
import requests
s = requests.Session(); s.verify = False
try:
    r = s.get('https://news.google.com/rss/search?q=test&hl=ja&gl=JP&ceid=JP:ja', timeout=10)
    print('OK:', r.status_code)
except Exception as e:
    print('NG:', e)
"@ 2>&1
Write-Host "  Google News RSS: $sslTest"

# =========================================================
# Step 4: git 認証確認
# =========================================================
Write-Host ""
Write-Host "[4/5] git 接続確認..."
Push-Location $ScriptDir
$gitRemote = git remote get-url origin 2>&1
Write-Host "  remote: $gitRemote"
$gitFetch = git fetch origin 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  fetch: OK"
} else {
    Write-Host "  fetch: NG（git 認証を確認してください）"
    Write-Host "  → git remote set-url origin https://<TOKEN>@github.com/<user>/context-reports.git"
}
Pop-Location

# =========================================================
# Step 5: Task Scheduler タスク登録
# =========================================================
Write-Host ""
Write-Host "[5/5] Task Scheduler タスク登録..."

if (-not (Test-Path $BatFile)) {
    Write-Error "run_collection.bat が見つかりません: $BatFile"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  既存タスクを削除"
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatFile`"" `
    -WorkingDirectory $ScriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "コンテキスト収集＋GitHub Pagesデプロイ（毎朝8時）" `
    -RunLevel Limited | Out-Null

Write-Host ""
Write-Host "========================================="
Write-Host "  セットアップ完了！"
Write-Host "========================================="
Write-Host ""
Write-Host "タスク名  : $TaskName"
Write-Host "実行時刻  : 毎日 08:00"
Write-Host ""
Write-Host "動作確認:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-Content '$ScriptDir\run_collection.log' -Tail 20 -Encoding UTF8"
Write-Host ""
