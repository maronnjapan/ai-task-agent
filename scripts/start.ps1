# Start the backend on Windows (background by default).
#   scripts\start.ps1             background
#   scripts\start.ps1 -Foreground run in this console
#   scripts\start.ps1 -Open       open the browser
param([switch]$Foreground, [switch]$Open)
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "common.ps1")
Require-Uv

$DataDir = Get-DataDir
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null
$PidFile = Join-Path $DataDir "aiwm.pid"
if (Test-Path $PidFile) {
  $existing = Get-Content $PidFile
  if (Get-Process -Id $existing -ErrorAction SilentlyContinue) {
    Write-Log "Already running (pid $existing) at http://127.0.0.1:$(Get-AppPort)"
    exit 0
  }
}

$args = @("run", "aiwm", "start", "--no-prompt")
if ($Open) { $args += "--open" }
if ($Foreground) {
  Push-Location $BackendDir
  & uv @args
  Pop-Location
  exit $LASTEXITCODE
}
$log = Join-Path $DataDir "logs\start.log"
Start-Process -FilePath "uv" -ArgumentList $args -WorkingDirectory $BackendDir -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError (Join-Path $DataDir "logs\start.err.log")
Start-Sleep -Seconds 2
if (Test-Path $PidFile) {
  Write-Log "Started (pid $(Get-Content $PidFile))."
  Push-Location $BackendDir
  $url = (& uv run --quiet aiwm url 2>$null)
  Pop-Location
  if (-not $url) { $url = "http://127.0.0.1:$(Get-AppPort)" }
  Write-Log "UI (open this URL once; it carries the session token): $url"
}
else { Write-Warn "Backend did not report a pid yet; check $log" }
