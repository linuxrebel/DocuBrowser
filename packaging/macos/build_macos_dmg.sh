#!/usr/bin/env bash
# packaging/macos/build_macos_dmg.sh — Build macOS .dmg installer
#
# Run from the repository root:
#   bash packaging/macos/build_macos_dmg.sh [RELEASE]
#
#   RELEASE  Build number (default: auto-detect from dist/).  Increment for
#            each rebuild of the same version.  Dash before the release
#            number, matching the Linux packages (e.g. 0.9.0-7.noarch.rpm):
#              docubrowser-foss-0.9.0-1-macos.dmg
#              docubrowser-foss-0.9.0-2-macos.dmg
#
# Output: dist/docubrowser-foss-<version>-<release>-macos.dmg
#
# The mounted .dmg contains:
#   Install.command     <- double-click to install (no sudo for the app itself)
#   Uninstall.command   <- double-click to uninstall
#   app/                <- all Python source + HTML + assets
#
# Uses only tools built into macOS (hdiutil).  The Install.command script
# likewise uses only built-ins (sips, iconutil) at install time.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v hdiutil >/dev/null 2>&1; then
    echo "ERROR: hdiutil not found — this script must be run on macOS." >&2
    exit 1
fi

# ── Extract version from docubrowser.py ──────────────────────────────────────
VERSION=$(python3 -c "
import re, sys
m = re.search(r'''VERSION\s*=\s*[\"']([\d.]+)''', open('docubrowser.py', encoding='utf-8').read())
if not m:
    sys.exit('ERROR: VERSION not found in docubrowser.py')
print(m.group(1))
")

# ── Determine release number ──────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    RELEASE="$1"
else
    # Auto-detect: highest existing release for this version + 1.
    # sed -E (not grep -P) so this works with BSD tools on macOS.
    # || true prevents set -e from aborting when no prior dmgs exist.
    LATEST=$(ls dist/docubrowser-foss-"${VERSION}"-*-macos.dmg 2>/dev/null \
             | sed -E "s/.*${VERSION//./\\.}-([0-9]+)-macos\.dmg/\1/" \
             | sort -n | tail -1 || true)
    RELEASE=$(( ${LATEST:-0} + 1 ))
fi

DIST_NAME="docubrowser-foss-${VERSION}-${RELEASE}-macos"
DMG_OUT="dist/${DIST_NAME}.dmg"

echo "==> Building macOS package: $DMG_OUT  (version $VERSION, release $RELEASE)"

# ── Stage files ───────────────────────────────────────────────────────────────
mkdir -p dist
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
STAGE_DIR="$STAGING/DocuBrowse"
mkdir -p "$STAGE_DIR/app"

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
    odf_extractor.py
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
    du-docs.db.example
    README.md
    LICENSE
    INSTALL.md
)

for f in "${APP_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        cp "$f" "$STAGE_DIR/app/"
    else
        echo "  WARNING: $f not found — skipping"
    fi
done

# Directories
cp -R icons "$STAGE_DIR/app/" 2>/dev/null || echo "  WARNING: icons/ not found."
cp -R EndUser_docs "$STAGE_DIR/app/" 2>/dev/null || echo "  WARNING: EndUser_docs/ not found."

# ── Installer files ───────────────────────────────────────────────────────────
install -m 755 packaging/macos/Install.command   "$STAGE_DIR/"
install -m 755 packaging/macos/Uninstall.command "$STAGE_DIR/"

# ── Build dmg ─────────────────────────────────────────────────────────────────
rm -f "$DMG_OUT"
hdiutil create \
    -volname "DocuBrowse FOSS ${VERSION}" \
    -srcfolder "$STAGE_DIR" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    "$DMG_OUT"

# ── Prune dist/ to keep only the latest 2 macOS dmgs ─────────────────────────
echo "==> Pruning dist/ (keeping latest 2 macOS releases)"
dmgs=( $(ls -t dist/docubrowser-foss-*-macos.dmg 2>/dev/null) )
if [[ "${#dmgs[@]}" -gt 2 ]]; then
    for old in "${dmgs[@]:2}"; do
        echo "    Removing old: $(basename "$old")"
        rm -f "$old"
    done
fi

echo ""
echo "==> Built: $DMG_OUT"
echo ""
echo "    Dmg contents:"
hdiutil imageinfo "$DMG_OUT" >/dev/null   # sanity check the image
MOUNT_POINT=$(hdiutil attach -readonly -nobrowse "$DMG_OUT" | awk -F'\t' '/\/Volumes\// {print $NF}' | tail -1)
if [[ -n "$MOUNT_POINT" ]]; then
    (cd "$MOUNT_POINT" && find . -maxdepth 2 | sort | head -40)
    hdiutil detach "$MOUNT_POINT" -quiet || true
fi
echo ""
echo "    Note: the .command scripts are unsigned — users who downloaded the"
echo "    dmg may need to right-click > Open the first time (Gatekeeper)."
echo ""
echo "    Upload to GitHub Releases as an asset on the v${VERSION} release."
