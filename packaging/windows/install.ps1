#Requires -Version 5.1
<#
.SYNOPSIS
    DocuBrowse FOSS Windows Installer

.DESCRIPTION
    Installs DocuBrowse to %LOCALAPPDATA%\DocuBrowse\ (no admin required).
    Requires Python 3.9+ and Ollama to be installed before running.

    Prerequisites:
      Python  - https://www.python.org/downloads/
      Ollama  - https://ollama.com

    After installing both, run Install.bat (or this script directly).

.NOTES
    Double-click Install.bat to run with correct execution policy.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Version    = "0.9.0"
$InstallDir = Join-Path $env:USERPROFILE "DocuBrowse"
$AppDir     = Join-Path $InstallDir "app"
$VenvDir    = Join-Path $InstallDir "venv"
$BinDir     = Join-Path $InstallDir "bin"

# Packaged mode: app\ sits next to this script (inside the extracted zip).
# Dev/test mode: running directly from packaging\windows\ in a repo checkout —
# the source files are two levels up at the repo root.
$SrcAppDir = Join-Path $PSScriptRoot "app"
$DevMode   = $false
if (-not (Test-Path $SrcAppDir)) {
    $repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    if (Test-Path (Join-Path $repoRoot "docubrowser.py")) {
        $SrcAppDir = $repoRoot
        $DevMode   = $true
    }
}

# App files copied in dev mode (repo root has many extra files we don't want).
$DevAppFiles = @(
    "docubrowser.py","doc_search.py","scan_docs.py","embed_docs.py",
    "pdf_extractor.py","docx_extractor.py","pptx_extractor.py","xlsx_extractor.py",
    "ebook_extractor.py","hardware_utils.py","docubrowse_db.py","purge_pii.py",
    "backup_restore.py","ensure_ollama.py","dup_detect.py","platform_paths.py",
    "index.html","settings.html","requirements.txt","README.md","LICENSE","INSTALL.md"
)

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ── Header ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  DocuBrowse FOSS $Version -- Windows Installer" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Install dir : $InstallDir"
Write-Host "  Commands    : docubrowser, docuback"
Write-Host ""

# ── Preflight: Python 3.9+ ────────────────────────────────────────────────────
Write-Host "Checking Python..." -NoNewline

$python = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    try {
        $src    = (Get-Command $candidate -ErrorAction Stop).Source
        $output = & $src --version 2>&1
        if ($output -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                $python = $src; break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host " NOT FOUND" -ForegroundColor Red
    Fail ("Python 3.9 or newer is required but was not found.`n" +
          "`n" +
          "  Download from: https://www.python.org/downloads/`n" +
          "  Check 'Add Python to PATH' during install.`n" +
          "`n" +
          "  Re-run Install.bat after installing Python.")
}


$pyver = ((& $python --version 2>&1) -replace 'Python ','').Trim()
Write-Host " OK ($pyver)" -ForegroundColor Green

# ── Preflight: Ollama ─────────────────────────────────────────────────────────
Write-Host "Checking Ollama..." -NoNewline

$ollama = $null
try { $ollama = (Get-Command ollama -ErrorAction Stop).Source } catch {}

if (-not $ollama) {
    Write-Host " NOT FOUND" -ForegroundColor Red
    Fail ("Ollama is required but was not found.`n" +
          "`n" +
          "  Download : https://ollama.com`n" +
          "`n" +
          "  Re-run Install.bat after installing Ollama.")
}
Write-Host " OK" -ForegroundColor Green

# ── Check source files present ────────────────────────────────────────────────
if (-not (Test-Path $SrcAppDir)) {
    Fail ("app\ folder not found next to this installer.`n" +
          "  Make sure you extracted the complete zip archive.")
}
if ($DevMode) {
    Write-Host "  (dev mode: sourcing files from repo root)" -ForegroundColor DarkGray
}

# ── Existing install ──────────────────────────────────────────────────────────
Write-Host ""
if (Test-Path $InstallDir) {
    $ans = Read-Host "WARNING: $InstallDir already exists. Overwrite? [y/N]"
    if ($ans -notmatch '^[yY]') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
    Write-Host ""
}

# ── Deploy files ──────────────────────────────────────────────────────────────
Write-Host "Deploying files..." -NoNewline
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
if ($DevMode) {
    foreach ($f in $DevAppFiles) {
        $src = Join-Path $SrcAppDir $f
        if (Test-Path $src) { Copy-Item $src $AppDir -Force }
    }
} else {
    Copy-Item -Path (Join-Path $SrcAppDir "*") -Destination $AppDir -Recurse -Force
}
Copy-Item -Path (Join-Path $PSScriptRoot "uninstall.ps1") -Destination $InstallDir -Force
Write-Host " done" -ForegroundColor Green

# ── Create Python virtualenv ──────────────────────────────────────────────────
# Remove any existing venv first — reinstalling over a live venv can leave
# locked files that cause venv creation to fail silently.
Write-Host "Creating virtual environment..." -NoNewline
if (Test-Path $VenvDir) {
    Remove-Item -Path $VenvDir -Recurse -Force
}
# Drop ErrorActionPreference to Continue: Python 3.13 on Windows emits a
# junction-point warning to stderr that Stop would treat as fatal.
# Capture output; show it only on failure so errors are diagnosable.
$prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
$venvOut = & $python -m venv $VenvDir 2>&1
$ErrorActionPreference = $prev
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    Write-Host ""
    Write-Host $venvOut
    Fail "Failed to create Python virtual environment."
}
Write-Host " done" -ForegroundColor Green

# ── Install Python dependencies ───────────────────────────────────────────────
Write-Host "Installing dependencies (may take a minute)..."
$pip  = Join-Path $VenvDir "Scripts\pip.exe"
$reqs = Join-Path $AppDir  "requirements.txt"
& $pip install --upgrade pip -q
& $pip install -r $reqs
if ($LASTEXITCODE -ne 0) { Fail "pip install failed -- check your internet connection and try again." }
Write-Host "  Dependencies installed." -ForegroundColor Green

# ── CLI wrapper scripts ───────────────────────────────────────────────────────
# Use %USERPROFILE% so the wrappers work for the current user regardless of
# whether Python's AppData virtualisation is active.
Write-Host "Creating CLI wrappers..." -NoNewline

@"
@echo off
"%USERPROFILE%\DocuBrowse\venv\Scripts\python.exe" "%USERPROFILE%\DocuBrowse\app\docubrowser.py" %*
"@ | Set-Content -Path (Join-Path $BinDir "docubrowser.cmd") -Encoding Ascii

@"
@echo off
"%USERPROFILE%\DocuBrowse\venv\Scripts\python.exe" "%USERPROFILE%\DocuBrowse\app\backup_restore.py" %*
"@ | Set-Content -Path (Join-Path $BinDir "docuback.cmd") -Encoding Ascii

Write-Host " done" -ForegroundColor Green

# ── Add bin\ to user PATH ─────────────────────────────────────────────────────
Write-Host "Updating PATH..." -NoNewline
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$BinDir", "User")
    Write-Host " added $BinDir" -ForegroundColor Green
} else {
    Write-Host " already present" -ForegroundColor Green
}

# ── Start Menu shortcuts ──────────────────────────────────────────────────────
Write-Host "Creating Start Menu entries..." -NoNewline
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Docubrowser"

# Remove stale files from previous installs before writing fresh ones.
if (Test-Path $startMenu) { Remove-Item -Path $startMenu -Recurse -Force }
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

$wsh = New-Object -ComObject WScript.Shell

# Web UI shortcut
$lnk            = $wsh.CreateShortcut((Join-Path $startMenu "DocuBrowse Web UI.url"))
$lnk.TargetPath = "http://localhost:8643"
$lnk.Save()

# Terminal launcher — write a .bat to bin\ then point a .lnk at it.
# .bat files are invisible in Start Menu All Apps; .lnk files are shown.
$termBat = Join-Path $BinDir "docubrowser-terminal.bat"
@"
@echo off
title DocuBrowse
call "%USERPROFILE%\DocuBrowse\bin\docubrowser.cmd" --help
cmd /k
"@ | Set-Content -Path $termBat -Encoding Ascii

$lnk3                  = $wsh.CreateShortcut((Join-Path $startMenu "Docubrowser Terminal.lnk"))
$lnk3.TargetPath       = $termBat
$lnk3.WorkingDirectory = $env:USERPROFILE
$lnk3.Description      = "DocuBrowse command-line interface"
$iconIco = Join-Path $AppDir "icons\icon-48.ico"
if (Test-Path $iconIco) { $lnk3.IconLocation = "$iconIco,0" }
$lnk3.Save()

# Notify the shell so Start Menu picks up the new entries immediately.
$code = @'
[DllImport("shell32.dll")] public static extern void SHChangeNotify(uint e, uint f, IntPtr a, IntPtr b);
'@
$shell = Add-Type -MemberDefinition $code -Name ShellNotify -Namespace WinAPI -PassThru -ErrorAction SilentlyContinue
if ($shell) { $shell::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero) }

Write-Host " done" -ForegroundColor Green
Write-Host "  $startMenu" -ForegroundColor DarkGray

# ── Register in Add/Remove Programs ──────────────────────────────────────────
Write-Host "Registering uninstaller..." -NoNewline
$reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DocuBrowseFOSS"
New-Item -Path $reg -Force | Out-Null
Set-ItemProperty $reg "DisplayName"     "DocuBrowse FOSS"
Set-ItemProperty $reg "DisplayVersion"  $Version
Set-ItemProperty $reg "Publisher"       "James Sparenberg"
Set-ItemProperty $reg "InstallLocation" $InstallDir
Set-ItemProperty $reg "UninstallString" ("powershell.exe -NoProfile -ExecutionPolicy Bypass " +
                                         "-File `"$InstallDir\uninstall.ps1`"")
Set-ItemProperty $reg "NoModify" 1 -Type DWord
Set-ItemProperty $reg "NoRepair" 1 -Type DWord
Write-Host " done" -ForegroundColor Green

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  DocuBrowse installed successfully!" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  IMPORTANT: Open a NEW terminal for the PATH change to take effect." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Quick start:"
Write-Host "    1. Open a new Command Prompt or PowerShell"
Write-Host "    2. docubrowser rescan C:\path\to\your\documents"
Write-Host "    3. docubrowser start"
Write-Host "    4. Browse to http://localhost:8643"
Write-Host ""
Write-Host "  Ollama models (pull once, then they stay locally):"
Write-Host "    ollama pull nomic-embed-text    (semantic search, ~274 MB)"
Write-Host "    ollama pull dolphin3            (synopsis generation, ~4.9 GB)"
Write-Host ""
Write-Host "  Other commands:"
Write-Host "    docubrowser stop           Stop the server"
Write-Host "    docubrowser status         Show running status and stats"
Write-Host "    docuback --backup          Back up your document database"
Write-Host ""
Write-Host "  Optional: Calibre for e-book support  https://calibre-ebook.com"
Write-Host ""
Write-Host "  To uninstall: Settings > Apps > DocuBrowse FOSS"
Write-Host "                or run Uninstall.bat from the original zip"
Write-Host ""
