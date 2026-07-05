#!/usr/bin/env bash
# packaging/build_windows_zip.sh — Build Windows distribution zip
#
# Run from the repository root:
#   bash packaging/build_windows_zip.sh
#
# Output: dist/docubrowser-foss-<version>-windows.zip
#
# The zip extracts to a folder containing:
#   Install.bat       <- double-click to install
#   Uninstall.bat     <- double-click to uninstall
#   install.ps1
#   uninstall.ps1
#   app/              <- all Python source + HTML + assets
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Extract version from docubrowser.py ──────────────────────────────────────
VERSION=$(python3 -c "
import re, sys
m = re.search(r'''VERSION\s*=\s*[\"']([\d.]+)''', open('docubrowser.py', encoding='utf-8').read())
if not m:
    sys.exit('ERROR: VERSION not found in docubrowser.py')
print(m.group(1))
")

DIST_NAME="docubrowser-foss-${VERSION}-windows"
DIST_DIR="dist/${DIST_NAME}"
ZIP_OUT="dist/${DIST_NAME}.zip"

echo "==> Building Windows package: $ZIP_OUT  (version $VERSION)"

# ── Clean previous build ──────────────────────────────────────────────────────
mkdir -p dist
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR/app"

# ── Application files (mirrors packaging/install.sh APP_FILES) ───────────────
APP_FILES=(
    docubrowser.py
    doc_search.py
    scan_docs.py
    embed_docs.py
    pdf_extractor.py
    docx_extractor.py
    pptx_extractor.py
    xlsx_extractor.py
    ebook_extractor.py
    hardware_utils.py
    docubrowse_db.py
    purge_pii.py
    backup_restore.py
    ensure_ollama.py
    dup_detect.py
    platform_paths.py
    index.html
    settings.html
    requirements.txt
    README.md
    LICENSE
    INSTALL.md
)

for f in "${APP_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        cp "$f" "$DIST_DIR/app/"
    else
        echo "  WARNING: $f not found — skipping"
    fi
done

# Optional: example database schema
[[ -f "du-docs.db.example" ]] && cp "du-docs.db.example" "$DIST_DIR/app/"

# ── Installer files ───────────────────────────────────────────────────────────
cp packaging/windows/Install.bat   "$DIST_DIR/"
cp packaging/windows/install.ps1   "$DIST_DIR/"
cp packaging/windows/Uninstall.bat "$DIST_DIR/"
cp packaging/windows/uninstall.ps1 "$DIST_DIR/"

# ── Convert line endings to CRLF for Windows ─────────────────────────────────
# .ps1 and .bat files must use CRLF or PowerShell/cmd.exe may behave oddly.
if command -v unix2dos &>/dev/null; then
    unix2dos -q "$DIST_DIR"/*.bat "$DIST_DIR"/*.ps1
else
    # Portable CRLF conversion: perl -pi works on both Linux and macOS.
    # (BSD sed requires -i '' which is incompatible with GNU sed.)
    for f in "$DIST_DIR"/*.bat "$DIST_DIR"/*.ps1; do
        perl -pi -e 's/\r\n|\n|\r/\r\n/g' "$f"
    done
fi

# ── Build zip ─────────────────────────────────────────────────────────────────
rm -f "$ZIP_OUT"
if command -v zip &>/dev/null; then
    (cd dist && zip -r "${DIST_NAME}.zip" "${DIST_NAME}/")
elif command -v 7z &>/dev/null; then
    (cd dist && 7z a -tzip "${DIST_NAME}.zip" "${DIST_NAME}/")
else
    # PowerShell fallback (Windows without zip/7z)
    ABS_DIST=$(cd dist && pwd -W 2>/dev/null || pwd)
    powershell.exe -NoProfile -Command \
        "Compress-Archive -Path '${ABS_DIST}/${DIST_NAME}' -DestinationPath '${ABS_DIST}/${DIST_NAME}.zip' -Force"
fi

echo ""
echo "==> Built: $ZIP_OUT"
echo ""
echo "    Zip contents:"
if command -v unzip &>/dev/null; then
    unzip -l "$ZIP_OUT" | awk 'NR>3 && !/^---/' | head -40
else
    powershell.exe -NoProfile -Command \
        "Add-Type -Assembly System.IO.Compression.FileSystem; \
         [IO.Compression.ZipFile]::OpenRead('$(pwd -W 2>/dev/null || pwd)/${ZIP_OUT}').Entries | \
         Select-Object -First 40 -ExpandProperty FullName"
fi
echo ""
echo "    Upload to GitHub Releases as an asset on the v${VERSION} release."
