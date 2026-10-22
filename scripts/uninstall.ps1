# Remove autostart, the virtual environment and optionally all data on Windows.
#   scripts\uninstall.ps1          keep data
#   scripts\uninstall.ps1 -Purge   delete %LOCALAPPDATA%\AIWorkManager as well
param([switch]$Purge)
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "common.ps1")
& (Join-Path $ScriptDir "stop.ps1")
if (Get-Command uv -ErrorAction SilentlyContinue) {
  Push-Location $BackendDir
  try { uv run aiwm autostart remove } catch { Write-Warn "autostart removal failed: $_" }
  Pop-Location
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $BackendDir ".venv"), (Join-Path $FrontendDir "node_modules"), (Join-Path $FrontendDir "dist")
if ($Purge) {
  $DataDir = Get-DataDir
  $answer = Read-Host "Delete ALL data in $DataDir? [y/N]"
  if ($answer -eq "y") { Remove-Item -Recurse -Force $DataDir; Write-Log "Removed $DataDir" }
}
Write-Log "Uninstalled. The .env file was kept; delete it manually if desired."
