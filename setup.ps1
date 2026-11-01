# Family Dashboard - Dev Environment Setup
# Run this once in an elevated (Administrator) PowerShell terminal
# Usage: .\setup.ps1

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "" ; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK($msg) { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    SKIP: $msg (already installed)" -ForegroundColor Yellow }

# 1. Git
Write-Step "Checking Git"
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Skip "$(git --version)"
} else {
    $gitInstaller = "$env:TEMP\git-installer.exe"
    Write-Host "    Downloading Git..."
    Invoke-WebRequest "https://github.com/git-for-windows/git/releases/download/v2.47.0.windows.1/Git-2.47.0-64-bit.exe" -OutFile $gitInstaller
    Start-Process $gitInstaller -ArgumentList "/VERYSILENT /NORESTART" -Wait
    Write-OK "Git installed"
}

# 2. Node.js LTS
Write-Step "Checking Node.js"
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Skip "$(node --version)"
} else {
    $nodeInstaller = "$env:TEMP\node-installer.msi"
    Write-Host "    Downloading Node.js LTS..."
    Invoke-WebRequest "https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi" -OutFile $nodeInstaller
    Start-Process msiexec.exe -ArgumentList "/i `"$nodeInstaller`" /qn" -Wait
    Write-OK "Node.js installed"
}

# 3. Python 3.12
Write-Step "Checking Python"
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd) {
    Write-Skip "$(python --version)"
} else {
    $pythonInstaller = "$env:TEMP\python-installer.exe"
    Write-Host "    Downloading Python 3.12..."
    Invoke-WebRequest "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $pythonInstaller
    Start-Process $pythonInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    Write-OK "Python installed"
}

# 4. Refresh PATH
Write-Step "Refreshing PATH"
$machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
$env:PATH = $machinePath + ";" + $userPath
Write-OK "PATH refreshed"

# 5. Verify
Write-Step "Verifying installs"
foreach ($tool in @("git", "node", "npm", "python", "pip")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) {
        Write-OK "$tool found at $($found.Source)"
    } else {
        Write-Host "    WARN: $tool not found - restart terminal and check" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Done! Close this terminal, open a fresh one, then come back to Kiro." -ForegroundColor Green
