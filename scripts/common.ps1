# Shared helpers for the Windows PowerShell scripts.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$EnvFile = if ($env:AIWM_ENV_FILE) { $env:AIWM_ENV_FILE } else { Join-Path $ProjectRoot ".env" }
$env:AIWM_ENV_FILE = $EnvFile

function Write-Log($msg) { Write-Host "[aiwm] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[aiwm] $msg" -ForegroundColor Yellow }

function Get-EnvValue($key, $default) {
  $fromEnv = [Environment]::GetEnvironmentVariable($key)
  if ($fromEnv) { return $fromEnv }
  if (Test-Path $EnvFile) {
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^$key=" } | Select-Object -Last 1
    if ($line) { $value = $line.Substring($key.Length + 1).Trim('"'); if ($value) { return $value } }
  }
  return $default
}

function Get-DataDir {
  $configured = Get-EnvValue "AIWM_DATA_DIR" ""
  if ($configured) { return [Environment]::ExpandEnvironmentVariables($configured) }
  return Join-Path $env:LOCALAPPDATA "AIWorkManager"
}

function Get-AppPort { return (Get-EnvValue "APP_PORT" "8765") }

function Require-Uv {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $local = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $local) { $env:PATH = "$(Split-Path $local);$env:PATH" }
    else { throw "uv is not installed. Install it with: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`"" }
  }
}
