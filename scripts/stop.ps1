# Stop a running backend on Windows.
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "common.ps1")
$DataDir = Get-DataDir
$PidFile = Join-Path $DataDir "aiwm.pid"
if (-not (Test-Path $PidFile)) { Write-Log "Not running (no pid file)."; exit 0 }
$ProcId = Get-Content $PidFile
$proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
if ($proc) { Stop-Process -Id $ProcId -Force; Write-Log "Stopped (pid $ProcId)." } else { Write-Log "Stale pid file; removing." }
Remove-Item -Force -ErrorAction SilentlyContinue $PidFile, (Join-Path $DataDir "aiwm.lock")
