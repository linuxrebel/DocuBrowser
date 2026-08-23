#!/usr/bin/env bash
# Test du-convert.sh root discovery + override generation, without Docker.
# Builds a fake DATA_DIR, runs --dry-run against it, asserts the output.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPT="$HERE/du-convert.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Fake native install: a DB, a config with doc_dir, and two scan dirs (one dup).
touch "$TMP/du-docs.db"
mkdir -p "$TMP/DocsRoot" "$TMP/Extra1" "$TMP/Extra2"
printf 'port = 8643\ndoc_dir  = %s/DocsRoot\n' "$TMP" > "$TMP/docubrowse.config"
printf '# a comment\n%s/Extra1\n%s/Extra2\n%s/DocsRoot\n\n' "$TMP" "$TMP" "$TMP" > "$TMP/scan_dirs.txt"

out="$(DOCUBROWSE_DATA_DIR="$TMP" bash "$SCRIPT" --dry-run)"

fail=0
check() { if grep -qF -- "$1" <<<"$out"; then echo "PASS: $2"; else echo "FAIL: $2"; echo "--- output ---"; echo "$out"; fail=1; fi; }

# primary root (doc_dir) goes via DOCUBROWSE_DOC_DIR
check "DOCUBROWSE_DOC_DIR=$TMP/DocsRoot" "primary root -> DOCUBROWSE_DOC_DIR"
# extras become identity :ro mounts in the override
check "\"$TMP/Extra1:$TMP/Extra1:ro\"" "Extra1 identity mount"
check "\"$TMP/Extra2:$TMP/Extra2:ro\"" "Extra2 identity mount"
# the DocsRoot dup must NOT be re-mounted as an extra (it's the primary)
if grep -qF -- "\"$TMP/DocsRoot:$TMP/DocsRoot:ro\"" <<<"$out"; then
  echo "FAIL: dedupe — DocsRoot double-mounted"; fail=1
else
  echo "PASS: dedupe — primary not duplicated in override"
fi

# missing root is flagged
printf '%s/DoesNotExist\n' "$TMP" >> "$TMP/scan_dirs.txt"
out2="$(DOCUBROWSE_DATA_DIR="$TMP" bash "$SCRIPT" --dry-run)"
grep -qF "NOT found on host" <<<"$out2" && echo "PASS: missing root flagged" || { echo "FAIL: missing root not flagged"; fail=1; }

exit $fail
