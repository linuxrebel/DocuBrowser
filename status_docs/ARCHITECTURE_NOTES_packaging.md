# DocuBrowse Packaging — Architecture Notes

**Status:** v0.9.0 RPM complete, DEB pending dpkg tools  
**Date:** 2026-07-03  

---

## Overview

Package DocuBrowse FOSS for Linux (RPM + DEB). Windows and macOS are deferred.

### Design principles

1. **Server only** — packages install DocuBrowse Python code. Ollama and
   Calibre are documented prerequisites (not bundled).
2. **System install, user data** — code installs to `/opt/docubrowser/`
   (read-only, root-owned). Runtime data (DB, config, blacklists) lives in
   `~/.docubrowser/` per user. Auto-detected: if the script's directory
   is writable (dev checkout), data stays there; if not (packaged install),
   data goes to `~/.docubrowser/`.
3. **No systemd for FOSS** — the FOSS version runs as a user app via
   `docubrowser start/stop`. Enterprise will integrate with systemd.
4. **Ollama prerequisite check** — on first launch, check for a running
   Ollama instance. If not found, display a message directing the user to
   https://ollama.com. Do not attempt to install Ollama automatically.
5. **CLI only on Linux** — no tray/menu bar app for FOSS.

---

## Naming consistency

DONE. All paths use `docubrowser` (not `docubrowse`). Install directory is
`/opt/docubrowser/` (packaged) or the repo checkout directory (dev mode).
User data directory is `~/.docubrowser/`.

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

**rpmbuild** (native) for RPM, **dpkg-deb** for DEB. Build script:
`packaging/build_packages.sh`. Spec file: `packaging/docubrowser-foss.spec`.

### Install layout

```
/opt/docubrowser/              # Application code (root-owned, read-only)
├── docubrowser.py             # CLI launcher
├── doc_search.py              # HTTP search server
├── scan_docs.py               # PDF/text extraction
├── embed_docs.py              # Ollama embedding
├── *.py                       # All other Python modules
├── index.html, settings.html  # Web UI
├── icons/                     # Application icons
├── EndUser_docs/              # User documentation
├── requirements.txt
├── venv/                      # Python virtualenv (created by %post)
├── backups/                   # Backup storage (created by %post)
└── LICENSE, README.md, INSTALL.md

~/.docubrowser/                # Per-user runtime data (auto-created)
├── du-docs.db                 # SQLite index (auto-created on first run)
├── docubrowse.config          # User configuration
├── scan_blacklist.txt         # Failed-extraction skip list
├── pii_blacklist.txt          # PII-purged files
├── scan_dirs.txt              # Scan directories
└── ignore_dirs.txt            # Ignore patterns

/usr/bin/docubrowser           # CLI wrapper → venv python3 docubrowser.py
/usr/bin/docuback              # Backup wrapper → venv python3 backup_restore.py
```

**APP_DIR / DATA_DIR split:** Code detects whether `/opt/docubrowser/` is
writable. In packaged installs (read-only), runtime data goes to
`~/.docubrowser/`. In dev mode (writable repo checkout), data stays in the
repo directory for backward compatibility.

### Package metadata

- Name: `docubrowser-foss`
- Version: `0.9.0` (from git tag)
- Architecture: `noarch` (pure Python)
- Dependencies: `python3 >= 3.9`
- Recommends: `calibre` (soft dep — only needed for e-books)
- No dependency on Ollama (not in distro repos)

### Post-install script (%post)

1. Create venv at `/opt/docubrowser/venv/`
2. `pip install -r requirements.txt` inside venv
3. Create `/opt/docubrowser/backups/`
4. Print usage summary (commands, web UI URL, prerequisites)

### Pre-uninstall (%preun)

Stops any running DocuBrowse processes (server, scan) via PID files.

### Post-uninstall (%postun)

On full removal (not upgrade): removes venv and `__pycache__`.
User data in `~/.docubrowser/` is preserved.

### No systemd for FOSS

FOSS runs as a user application, not a system service. Users start/stop
via `docubrowser start` / `docubrowser stop`. Enterprise uses systemd.

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

1. **Icons** — DONE. PNG icons in `icons/` directory.
2. **Rename .docubrowse → .docubrowser** — DONE.
3. **Cross-platform file/URL open** — Future (Linux-only for now).
4. **Config location** — DECIDED: `~/.docubrowser/docubrowse.config` (packaged),
   or `APP_DIR/docubrowse.config` (dev mode). Windows/macOS TBD.

---

## Build & release workflow

```
Source (git tag)
    │
    ├── Linux ──→ rpmbuild / dpkg-deb ──→ .rpm + .deb ──→ GitHub Release
    │
    ├── Windows ──→ PyInstaller ──→ Inno Setup ──→ .exe installer ──→ GitHub Release
    │
    └── macOS ──→ PyInstaller ──→ create-dmg ──→ .dmg ──→ GitHub Release
```

Linux builds via `packaging/build_packages.sh`. Never commit release
tarballs to git — they go on the GitHub Releases page only.

Windows and macOS builds are future work.

---

## Timeline estimate

| Phase | Work | Status |
|-------|------|--------|
| 0 | Icons, .docubrowser rename, config location | DONE |
| 1 | Linux RPM + DEB (rpmbuild / dpkg-deb) | RPM DONE, DEB pending dpkg tools |
| 2 | Tray app (`docubrowser_tray.py`) | Future |
| 3 | Windows installer (PyInstaller + Inno Setup) | Future |
| 4 | macOS bundle (PyInstaller + DMG) | Future |
| 5 | CI/CD for automated builds | Future |
