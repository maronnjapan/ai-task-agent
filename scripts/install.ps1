# Install Autonomous AI Work Manager on Windows 11.
#   scripts\install.ps1               full install
#   scripts\install.ps1 -Autostart    also register a Task Scheduler logon task
param([switch]$Autostart)
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "common.ps1")

Write-Log "Project: $ProjectRoot"

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Log "Installing uv..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}
Require-Uv

# 2. Python dependencies
Write-Log "Installing Python dependencies with uv..."
Push-Location $BackendDir
try { uv sync --frozen } catch { uv sync }
Pop-Location

# 3. Frontend
if (Get-Command npm -ErrorAction SilentlyContinue) {
  Write-Log "Building the frontend..."
  Push-Location $FrontendDir
  try { npm ci --no-audit --no-fund } catch { npm install --no-audit --no-fund }
  npm run build
  Pop-Location
} else {
  Write-Warn "npm not found: install Node.js 20+ and run 'npm install; npm run build' in frontend\"
}

# 4. .env (Windows uses the dotenv secret backend)
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $ProjectRoot ".env.example") $EnvFile
  (Get-Content $EnvFile) -replace '^SECRET_BACKEND=auto', 'SECRET_BACKEND=dotenv' | Set-Content $EnvFile
  Write-Log "Created $EnvFile - put your API keys there (OPENAI_API_KEY=...)."
}

# 5. Database
New-Item -ItemType Directory -Force -Path (Get-DataDir) | Out-Null
Push-Location $BackendDir
uv run aiwm migrate
uv run aiwm setup
if ($Autostart) { uv run aiwm autostart install }
Pop-Location

Write-Log "Install complete. Start with: scripts\start.ps1"
