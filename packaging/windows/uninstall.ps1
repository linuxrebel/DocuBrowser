#Requires -Version 5.1
<#
.SYNOPSIS
    DocuBrowse FOSS Windows Uninstaller

.DESCRIPTION
    Removes DocuBrowse from %USERPROFILE%\DocuBrowse\.
    Your document database (du-docs.db) is NOT removed.

.NOTES
    Double-click Uninstall.bat to run, or go to Settings > Apps > DocuBrowse FOSS.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$InstallDir = Join-Path $env:USERPROFILE "DocuBrowse"
$BinDir     = Join-Path $InstallDir "bin"

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  DocuBrowse FOSS -- Uninstaller" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $InstallDir)) {
    Write-Host "DocuBrowse does not appear to be installed at $InstallDir" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

$ans = Read-Host "Remove DocuBrowse from $InstallDir ? [y/N]"
if ($ans -notmatch '^[yY]') {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

Write-Host ""

# ── Remove from user PATH ─────────────────────────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -like "*$BinDir*") {
    $newPath = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $BinDir }) -join ';'
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "  Removed from PATH" -ForegroundColor Green
}

# ── Remove Start Menu entries ─────────────────────────────────────────────────
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Docubrowser"
if (Test-Path $startMenu) {
    Remove-Item -Path $startMenu -Recurse -Force
    Write-Host "  Removed Start Menu entries" -ForegroundColor Green
}

# ── Remove Add/Remove Programs entry ─────────────────────────────────────────
$reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DocuBrowseFOSS"
if (Test-Path $reg) {
    Remove-Item -Path $reg -Force
    Write-Host "  Removed from Add/Remove Programs" -ForegroundColor Green
}

# ── Remove install directory ──────────────────────────────────────────────────
# This file lives inside $InstallDir; PowerShell reads scripts into memory
# before executing, so deleting the directory while the script runs is safe.
# If the server is running it will hold the database open — catch that and
# tell the user to stop it first rather than silently leaving files behind.
try {
    $ErrorActionPreference = 'Stop'
    Remove-Item -Path $InstallDir -Recurse -Force
    Write-Host "  Removed $InstallDir" -ForegroundColor Green
} catch {
    $ErrorActionPreference = 'Continue'
    Write-Host ""
    Write-Host "ERROR: Could not fully remove $InstallDir" -ForegroundColor Red
    Write-Host "  Some files may be locked by a running DocuBrowse server."
    Write-Host "  Run 'docubrowser stop', then run Uninstall.bat again."
    Write-Host ""
    exit 1
} finally {
    $ErrorActionPreference = 'Continue'
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "DocuBrowse has been uninstalled." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Your document database (du-docs.db) was not removed."
Write-Host "  It is in whichever folder you ran 'docubrowser rescan' from."
Write-Host ""
