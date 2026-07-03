# DocuBrowse Packaging — Architecture Notes

**Status:** Planning  
**Date:** 2026-07-02  

---

## Overview

Package DocuBrowse for four targets: Linux RPM, Linux DEB, Windows (MSI), and
macOS (PKG/DMG). All packages install in user mode — system-mode installs
(systemd, /opt) move to Enterprise.

### Design principles

1. **Server only** — packages install DocuBrowse Python code and its Python
   dependencies. Ollama and Calibre are documented prerequisites.
2. **User-mode install** — `~/.docubrowser/` on Linux/macOS,
   `%LOCALAPPDATA%\DocuBrowser\` on Windows. No root/admin required for
   basic operation.
3. **Ollama prerequisite check** — on first launch (all platforms), check for
   a running Ollama instance. If not found, display a message directing the
   user to https://ollama.com with platform-appropriate install instructions.
   Do not attempt to install Ollama automatically.
4. **Tray/menu bar app** — Windows and macOS get a system tray icon for
   start/stop/open-browser. Linux packages provide CLI only (matching
   current behavior).

---

## Naming consistency

The install directory is being renamed from `.docubrowse` to `.docubrowser`
across all platforms for consistency with the CLI command name `docubrowser`.

### Files to update (pre-packaging)

| File | Change |
|------|--------|
| `install.sh` | `INSTALL_DIR="$HOME/.docubrowser"` (was `.docubrowse`) |
| `uninstall.sh` | Match new path |
| `README.md` | All `~/.docubrowse` references → `~/.docubrowser` |
| `INSTALL.md` | Same |
| `EndUser_docs/Admin_Guide.md` | Same |
| `docubrowser.py` | Config search path if any reference `.docubrowse` |

System-mode paths (`/opt/docubrowse`) also rename to `/opt/docubrowser`, but
system-mode is moving to Enterprise so this is low priority.

---

## Prerequisites (not bundled)

All platforms require:

| Prerequisite | Purpose | Install source |
|-------------|---------|---------------|
| Ollama | Embeddings + synopsis generation | https://ollama.com |
| Calibre | MOBI/AZW3/AZW e-book extraction | Distro package or https://calibre-ebook.com |

Ollama check at startup: `ensure_ollama.py` already handles this on Linux.
Needs extension for Windows/macOS (check if `ollama` is in PATH or running
as a service, else show install URL).

---

## Platform: Linux (RPM + DEB)

### Build tool

**fpm** (Effing Package Management) — single definition builds both .rpm and
.deb. Avoids maintaining separate spec files and debian/ directories.

### Install layout

```
~/.docubrowser/
├── venv/                  # Python virtual environment
│   └── ...
├── app/                   # DocuBrowse source files (copied from repo)
│   ├── docubrowser.py
│   ├── doc_search.py
│   ├── scan_docs.py
│   ├── ...
│   └── requirements.txt
└── data/                  # Runtime data (db, blacklists, config)
    ├── du-docs.db
    ├── docubrowse.config
    ├── scan_blacklist.txt
    └── ...

~/.local/bin/docubrowser   # CLI wrapper (shell script)
```

### Package metadata

- Name: `docubrowser`
- Version: from git tag
- Architecture: `noarch` (pure Python)
- Dependencies: `python3 >= 3.10` (RPM: `python3`, DEB: `python3`)
- Recommends: `calibre` (soft dep — only needed for e-books)
- No dependency on Ollama (not in distro repos)

### Post-install script

1. Create venv at `~/.docubrowser/venv/`
2. `pip install -r requirements.txt` inside venv
3. Install CLI wrapper at `~/.local/bin/docubrowser`
4. Print message: check Ollama is installed, point to ollama.com if not

### Open questions — Linux

- **fpm vs native packaging:** fpm is simpler but some distros/users prefer
  native rpmbuild/debuild. Decision: start with fpm, add native later if
  demand exists.
- **User-mode RPM/DEB:** RPMs and DEBs traditionally install system-wide.
  A user-mode package that installs to `$HOME` is unconventional. Alternative:
  package installs to `/opt/docubrowser` but runs as the invoking user (no
  dedicated system user). Or: ship a `.tar.gz` + `install.sh` for user mode
  and reserve RPM/DEB for system mode (Enterprise).
- **Config file location:** DECIDED — `~/.config/docubrowser.config` (Linux),
  OS-conventional paths on Windows/macOS. See prereqs section.

---

## Platform: Windows

### Build tool chain

- **PyInstaller** — freeze Python + deps into a standalone directory or single exe
- **Inno Setup** — build the .exe installer (or WiX for .msi)

### Install layout

```
%LOCALAPPDATA%\DocuBrowser\
├── app\                   # PyInstaller output (frozen Python + deps)
│   ├── docubrowser.exe    # CLI entry point
│   └── ...
├── tray\                  # Tray app (separate PyInstaller target)
│   └── docubrowser-tray.exe
├── data\                  # Runtime data
│   ├── du-docs.db
│   ├── config
│   └── ...
└── logs\
    └── docubrowser.log
```

### Tray app

Small Python script using `pystray` + `Pillow`:

- **Icon:** DocuBrowse logo (needs icon file — .ico for Windows)
- **Menu items:**
  - Start Server
  - Stop Server
  - Open DocuBrowse (launches browser to localhost:8643)
  - Status (shows doc count, server state)
  - Quit
- Manages the `doc_search.py` server process (subprocess)
- Optional: auto-start on login (Start Menu → Startup shortcut)

### Ollama check — Windows

On startup, check:
1. `ollama.exe` in PATH
2. Ollama service running (`sc query OllamaService` or process check)

If neither: show a Windows notification / dialog:
> "DocuBrowse requires Ollama for AI features. Download it from
> https://ollama.com/download/windows"

### Open questions — Windows

- **Python bundling size:** PyInstaller output is typically 50-100MB for a
  project this size. Acceptable?
- **pdfplumber on Windows:** works, but test needed — some PDF extraction
  edge cases may differ.
- **xdg-open equivalent:** `os.startfile()` on Windows for "Open" button.
  Already handled? Need to check `doc_search.py`.

---

## Platform: macOS

### Build tool chain

- **PyInstaller** — freeze into a .app bundle
- **create-dmg** or **pkgbuild** — package as .dmg or .pkg

### Install layout

```
~/Applications/DocuBrowser.app/     # .app bundle (tray app)
    Contents/
    ├── MacOS/
    │   └── docubrowser-tray        # main executable (PyInstaller)
    ├── Resources/
    │   ├── app/                    # DocuBrowse source or frozen CLI
    │   └── icon.icns               # macOS icon
    └── Info.plist

~/.docubrowser/                     # Runtime data (same as Linux)
    ├── du-docs.db
    ├── config
    └── ...
```

### Menu bar app

Same `pystray` codebase as Windows, but renders as a macOS menu bar icon.
Same menu items: Start/Stop/Open/Status/Quit.

### Ollama check — macOS

Check `which ollama` or if Ollama.app is installed. If missing:
> "DocuBrowse requires Ollama. Download it from https://ollama.com/download/mac"

### Open questions — macOS

- **No test environment:** James cannot test macOS builds. Options: CI with
  macOS runners (GitHub Actions has them), or find a tester.
- **Gatekeeper / code signing:** unsigned .app bundles trigger macOS warnings.
  Signing requires an Apple Developer account ($99/yr). Decision: defer
  signing, document the right-click → Open workaround for now.
- **Homebrew formula:** alternative to .dmg/.pkg. Lower friction for
  macOS developers. Consider as future option.

---

## Shared components

### Tray app (`docubrowser_tray.py`)

Single Python module, cross-platform via `pystray`:

```
Dependencies: pystray, Pillow
Platforms:    Windows (system tray), macOS (menu bar)
Not used on:  Linux (CLI only for FOSS)
```

Core logic:
1. On launch: start server (`doc_search.py`) as subprocess
2. Show tray icon with menu
3. "Open" → `webbrowser.open("http://localhost:8643")`
4. "Stop" → send SIGTERM/terminate to server subprocess
5. "Quit" → stop server, exit tray app
6. Ollama check runs once at startup; result cached

### Icon assets needed

| Format | Platform | Size |
|--------|----------|------|
| `.ico` | Windows | 16/32/48/256px multi-resolution |
| `.icns` | macOS | 16–1024px |
| `.png` | Linux (optional, for .desktop file) | 128px or 256px |
| `.svg` | Source / scalable | vector |

**Status:** Blocked — icons not yet designed.

### Ollama check module (`ensure_ollama.py` update)

Current `ensure_ollama.py` tries to install Ollama on Linux. For packaging:

- **Remove auto-install logic** — packages should not curl-pipe-bash
- **Check only:** is Ollama reachable at `http://localhost:11434/api/tags`?
- **If not:** print/display platform-appropriate message with download URL
- **If yes:** check for required models, offer to pull if missing

---

## Prereqs before packaging work begins

1. **Icons** — design logo, export to .ico / .icns / .png / .svg
2. **Rename .docubrowse → .docubrowser** — update install.sh, uninstall.sh,
   README, INSTALL.md, Admin Guide (small patch, do first)
3. **Test xdg-open / os.startfile on Windows** — verify the "Open" button
   in doc_search.py works cross-platform, or add platform dispatch
4. **Config location** — DECIDED: follow OS conventions per platform:
   - Linux: `~/.config/docubrowser.config`
   - macOS: `~/Library/Application Support/DocuBrowser/docubrowser.config`
   - Windows: `%APPDATA%\DocuBrowser\docubrowser.config`

---

## Build & release workflow

```
Source (git tag)
    │
    ├── Linux ──→ fpm ──→ .rpm + .deb ──→ GitHub Release
    │
    ├── Windows ──→ PyInstaller ──→ Inno Setup ──→ .exe installer ──→ GitHub Release
    │
    └── macOS ──→ PyInstaller ──→ create-dmg ──→ .dmg ──→ GitHub Release
```

All builds triggered from the same git tag. CI (GitHub Actions) can build
Linux and macOS. Windows may need a self-hosted runner or manual build
until CI is set up.

---

## Timeline estimate

| Phase | Work | Depends on |
|-------|------|-----------|
| 0 | Icons, .docubrowser rename, config location decision | Nothing |
| 1 | Linux RPM + DEB via fpm | Phase 0 |
| 2 | Tray app (`docubrowser_tray.py`) | Phase 0 (icons) |
| 3 | Windows installer (PyInstaller + Inno Setup) | Phase 2 |
| 4 | macOS bundle (PyInstaller + DMG) | Phase 2 |
| 5 | CI/CD for automated builds | Phases 1-4 |
