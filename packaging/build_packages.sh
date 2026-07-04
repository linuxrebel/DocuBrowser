#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_packages.sh — Build RPM (and DEB when tools are available) for
#                     DocuBrowse FOSS.
#
# Usage:
#   ./packaging/build_packages.sh [RELEASE]
#
#   RELEASE  Build number (default: 1).  Increment for each rebuild of
#            the same version.  The resulting RPM is named:
#              docubrowser-foss-0.9.0-RELEASE.noarch.rpm
#
# Run from the repo root:
#   ./packaging/build_packages.sh
#   ./packaging/build_packages.sh 2     # second build
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

NAME="docubrowser-foss"
VERSION="0.9.0"
RELEASE="${1:-1}"
SPEC="packaging/docubrowser-foss.spec"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Pre-flight ───────────────────────────────────────────────────────────────
if [[ ! -f "$SPEC" ]]; then
    echo "ERROR: $SPEC not found.  Run from the repo root." >&2
    exit 1
fi

# Verify git is clean (warn, don't block)
if ! git diff --quiet HEAD 2>/dev/null; then
    echo "WARNING: uncommitted changes in working tree."
    echo "         The tarball will contain the committed state, not local edits."
    echo "         Consider committing first."
    echo ""
fi

# ── Files to include in the source tarball ───────────────────────────────────
# We stage only the files that belong in the package, then tar them up.

STAGING="$(mktemp -d)"
STAGE_DIR="$STAGING/$NAME-$VERSION"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$STAGE_DIR"

# Application files
APP_FILES=(
    docubrowser.py doc_search.py scan_docs.py embed_docs.py
    pdf_extractor.py docx_extractor.py pptx_extractor.py xlsx_extractor.py
    ebook_extractor.py hardware_utils.py docubrowse_db.py purge_pii.py
    backup_restore.py ensure_ollama.py dup_detect.py
    index.html settings.html
    requirements.txt du-docs.db.example
    README.md LICENSE INSTALL.md
)

for f in "${APP_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        cp "$f" "$STAGE_DIR/"
    else
        echo "WARNING: $f not found, skipping."
    fi
done

# Directories
cp -a icons "$STAGE_DIR/" 2>/dev/null || echo "WARNING: icons/ not found."
cp -a EndUser_docs "$STAGE_DIR/" 2>/dev/null || echo "WARNING: EndUser_docs/ not found."

# ── Build source tarball ─────────────────────────────────────────────────────
TARBALL="$NAME-$VERSION.tar.gz"
(cd "$STAGING" && tar czf "$REPO_ROOT/$TARBALL" "$NAME-$VERSION")
echo "Created source tarball: $TARBALL"

# ── RPM ──────────────────────────────────────────────────────────────────────
if command -v rpmbuild >/dev/null 2>&1; then
    echo ""
    echo "==> Building RPM (release $RELEASE) ..."

    # Set up rpmbuild tree in a temp dir (don't pollute ~/rpmbuild)
    RPM_TOPDIR="$(mktemp -d)"
    for d in BUILD RPMS SOURCES SPECS SRPMS; do
        mkdir -p "$RPM_TOPDIR/$d"
    done

    cp "$TARBALL" "$RPM_TOPDIR/SOURCES/"
    cp "$SPEC" "$RPM_TOPDIR/SPECS/"

    rpmbuild -bb \
        --define "_topdir $RPM_TOPDIR" \
        --define "release $RELEASE" \
        "$RPM_TOPDIR/SPECS/$(basename "$SPEC")"

    # Copy resulting RPM to dist/
    mkdir -p "$REPO_ROOT/dist"
    find "$RPM_TOPDIR/RPMS" -name '*.rpm' -exec cp {} "$REPO_ROOT/dist/" \;
    rm -rf "$RPM_TOPDIR"

    echo ""
    echo "RPM(s) in dist/:"
    ls -1 "$REPO_ROOT/dist/"*.rpm 2>/dev/null
else
    echo ""
    echo "SKIPPED: rpmbuild not found.  Install rpm-build to build RPMs."
fi

# ── DEB ──────────────────────────────────────────────────────────────────────
if command -v dpkg-deb >/dev/null 2>&1; then
    echo ""
    echo "==> Building DEB (release $RELEASE) ..."

    DEB_ROOT="$(mktemp -d)"
    DEB_PKG="$DEB_ROOT/$NAME-$VERSION"

    # Application files
    mkdir -p "$DEB_PKG/opt/docubrowser"
    cp -a "$STAGE_DIR"/* "$DEB_PKG/opt/docubrowser/"

    # Wrapper scripts
    mkdir -p "$DEB_PKG/usr/bin"
    cat > "$DEB_PKG/usr/bin/docubrowser" <<'WRAPPER'
#!/usr/bin/env bash
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/docubrowser.py "$@"
WRAPPER
    chmod 755 "$DEB_PKG/usr/bin/docubrowser"

    cat > "$DEB_PKG/usr/bin/docuback" <<'WRAPPER'
#!/usr/bin/env bash
exec /opt/docubrowser/venv/bin/python3 /opt/docubrowser/backup_restore.py "$@"
WRAPPER
    chmod 755 "$DEB_PKG/usr/bin/docuback"

    # DEBIAN control
    mkdir -p "$DEB_PKG/DEBIAN"
    cat > "$DEB_PKG/DEBIAN/control" <<EOF
Package: docubrowser-foss
Version: ${VERSION}-${RELEASE}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9)
Recommends: calibre
Maintainer: James Sparenberg <james@sparenbergs.us>
Description: Self-hosted document search and indexing server
 DocuBrowse scans PDF, DOCX, PPTX, XLSX, and EPUB files,
 extracts text, generates AI-powered synopses and semantic
 embeddings via Ollama, and provides a web UI for search.
EOF

    cat > "$DEB_PKG/DEBIAN/postinst" <<'SCRIPT'
#!/bin/bash
set -e
if command -v python3 >/dev/null 2>&1; then
    echo "Creating Python virtualenv at /opt/docubrowser/venv/ ..."
    python3 -m venv /opt/docubrowser/venv 2>/dev/null || true
    if [ -f /opt/docubrowser/venv/bin/pip ]; then
        /opt/docubrowser/venv/bin/pip install --upgrade pip -q 2>/dev/null || true
        /opt/docubrowser/venv/bin/pip install -r /opt/docubrowser/requirements.txt -q 2>/dev/null || true
    fi
fi
mkdir -p /opt/docubrowser/backups
echo ""
echo "DocuBrowse FOSS installed.  Run: docubrowser start"
echo "Web UI: http://localhost:8643"
SCRIPT
    chmod 755 "$DEB_PKG/DEBIAN/postinst"

    cat > "$DEB_PKG/DEBIAN/prerm" <<'SCRIPT'
#!/bin/bash
set -e
for pidfile in /var/run/docubrowser/docubrowse_scan.pid \
               /var/run/docubrowser/docubrowser.pid; do
    [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null || true
done
SCRIPT
    chmod 755 "$DEB_PKG/DEBIAN/prerm"

    cat > "$DEB_PKG/DEBIAN/postrm" <<'SCRIPT'
#!/bin/bash
set -e
if [ "$1" = "purge" ] || [ "$1" = "remove" ]; then
    rm -rf /opt/docubrowser/venv /opt/docubrowser/__pycache__
fi
SCRIPT
    chmod 755 "$DEB_PKG/DEBIAN/postrm"

    dpkg-deb --build "$DEB_PKG" "$REPO_ROOT/dist/${NAME}_${VERSION}-${RELEASE}_all.deb"
    rm -rf "$DEB_ROOT"

    echo ""
    echo "DEB(s) in dist/:"
    ls -1 "$REPO_ROOT/dist/"*.deb 2>/dev/null
else
    echo ""
    echo "SKIPPED: dpkg-deb not found.  Install dpkg on Fedora (sudo dnf install dpkg)"
    echo "         or build on a Debian/Ubuntu system to create .deb packages."
fi

# ── Installable tarball ─────────────────────────────────────────────────────
echo ""
echo "==> Building installable tarball ..."

TGZ_NAME="docubrowser-foss-${VERSION}-${RELEASE}"
TGZ_DIR="$(mktemp -d)"
TGZ_STAGE="$TGZ_DIR/$TGZ_NAME"
mkdir -p "$TGZ_STAGE"

# App files (same as RPM/DEB)
cp -a "$STAGE_DIR"/* "$TGZ_STAGE/"

# Install/uninstall scripts
install -m 755 packaging/install.sh   "$TGZ_STAGE/"
install -m 755 packaging/uninstall.sh "$TGZ_STAGE/"

# Build the tarball
(cd "$TGZ_DIR" && tar czf "$REPO_ROOT/dist/${TGZ_NAME}.tar.gz" "$TGZ_NAME")
rm -rf "$TGZ_DIR"

echo ""
echo "Tarball in dist/:"
ls -1 "$REPO_ROOT/dist/"*.tar.gz 2>/dev/null

# ── Cleanup ──────────────────────────────────────────────────────────────────
rm -f "$REPO_ROOT/$TARBALL"

echo ""
echo "Done.  Packages are in dist/"
