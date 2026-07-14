#!/usr/bin/env python3
"""
Duplicate File Cleanup Tool
Safely removes duplicate files based on dedup_detector.py output.
"""

import os
import sys
import json
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

class DuplicateCleanup:
    def __init__(self, dry_run=True, verbose=False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.audit_log = []
        self.stats = {
            'total_files_evaluated': 0,
            'files_to_delete': 0,
            'bytes_to_free': 0,
            'skipped_files': 0,
            'errors': 0
        }

    def log_action(self, action, filepath, reason=""):
        """Log an action for audit trail."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'filepath': filepath,
            'reason': reason
        }
        self.audit_log.append(entry)
        if self.verbose:
            print(f"[{action}] {filepath}")

    def hash_file(self, filepath, sample_size=5000):
        """Compute SHA256 hash of first N bytes."""
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, 'rb') as f:
                chunk = f.read(sample_size)
                sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            self.log_action('ERROR', filepath, str(e))
            self.stats['errors'] += 1
            return None

    def find_exact_duplicates(self, directory):
        """Scan directory and group files by hash."""
        file_hashes = defaultdict(list)
        print(f"Scanning {directory} for duplicates...", file=sys.stderr)

        _skipped = 0
        for filepath in Path(directory).rglob('*'):
            try:
                if not filepath.is_file():
                    continue
            except OSError:
                _skipped += 1
                continue
            self.stats['total_files_evaluated'] += 1
            if self.stats['total_files_evaluated'] % 1000 == 0:
                print(f"  Scanned {self.stats['total_files_evaluated']} files...", file=sys.stderr)

            file_hash = self.hash_file(filepath)
            if file_hash:
                try:
                    size = filepath.stat().st_size
                    mtime = filepath.stat().st_mtime
                except OSError:
                    continue
                file_hashes[file_hash].append({
                    'path': str(filepath),
                    'size': size,
                    'mtime': mtime
                })
        if _skipped:
            print(f"  ⚠ Skipped {_skipped} inaccessible file(s)", file=sys.stderr)

        # Filter to only hashes with duplicates
        duplicates = {k: v for k, v in file_hashes.items() if len(v) > 1}
        return duplicates

    def select_keeper(self, files):
        """Select which file to keep (deepest path, newest mtime)."""
        files_sorted = sorted(files, key=lambda x: (x['path'].count(os.sep), x['mtime']), reverse=True)
        return files_sorted[0]

    def is_backup_or_archive(self, filepath):
        """Check if file is in a backup/archive directory."""
        path_lower = filepath.lower()
        backup_patterns = [
            'backup', 'archive', 'old', 'bak', 'tmp', 'temp',
            'trash', 'delete', 'duplicate', '_old', '-old',
            '_backup', '.bak', 'copy of'
        ]
        return any(pattern in path_lower for pattern in backup_patterns)

    def safe_delete(self, filepath):
        """Safely delete a file with error handling."""
        try:
            if self.dry_run:
                self.log_action('DELETE [DRY-RUN]', filepath)
                return True
            else:
                Path(filepath).unlink()
                self.log_action('DELETE', filepath)
                return True
        except Exception as e:
            self.log_action('ERROR', filepath, f"Delete failed: {e}")
            self.stats['errors'] += 1
            return False

    def process_duplicates(self, duplicates):
        """Process duplicate groups and decide what to delete."""
        for file_hash, files in duplicates.items():
            if len(files) < 2:
                continue

            keeper = self.select_keeper(files)
            self.log_action('KEEP', keeper['path'], f"Hash: {file_hash[:16]}...")

            for file_info in files:
                if file_info != keeper:
                    reason = "Exact duplicate"
                    if self.is_backup_or_archive(file_info['path']):
                        reason += " (in archive/backup directory)"

                    self.stats['files_to_delete'] += 1
                    self.stats['bytes_to_free'] += file_info['size']
                    self.safe_delete(file_info['path'])

    def write_audit_log(self, output_file):
        """Write detailed audit log."""
        with open(output_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("DUPLICATE FILE CLEANUP AUDIT LOG\n")
            f.write("=" * 80 + "\n")
            f.write(f"Mode: {'DRY-RUN' if self.dry_run else 'LIVE'}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")

            f.write("STATISTICS\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total files evaluated: {self.stats['total_files_evaluated']}\n")
            f.write(f"Files to delete: {self.stats['files_to_delete']}\n")
            f.write(f"Bytes to free: {self.stats['bytes_to_free']:,} ({self.stats['bytes_to_free'] / 1024 / 1024:.2f} MB)\n")
            f.write(f"Errors: {self.stats['errors']}\n\n")

            f.write("DETAILED LOG\n")
            f.write("-" * 80 + "\n")
            for entry in self.audit_log:
                f.write(f"[{entry['timestamp']}] {entry['action']}\n")
                f.write(f"  Path: {entry['filepath']}\n")
                if entry['reason']:
                    f.write(f"  Reason: {entry['reason']}\n")

            f.write("\n" + "=" * 80 + "\n")
            if self.dry_run:
                f.write("NOTE: This was a DRY-RUN. No files were actually deleted.\n")
                f.write("Review this log carefully before running with --execute.\n")

    def run(self, directory, output_log):
        """Execute cleanup process."""
        if not os.path.isdir(directory):
            print(f"Error: {directory} is not a directory", file=sys.stderr)
            return False

        duplicates = self.find_exact_duplicates(directory)
        print(f"Found {len(duplicates)} duplicate groups", file=sys.stderr)

        self.process_duplicates(duplicates)
        self.write_audit_log(output_log)

        print("\n" + "=" * 80, file=sys.stderr)
        print(f"Files to delete: {self.stats['files_to_delete']}", file=sys.stderr)
        print(f"Storage to free: {self.stats['bytes_to_free'] / 1024 / 1024:.2f} MB", file=sys.stderr)
        print(f"Errors: {self.stats['errors']}", file=sys.stderr)
        if self.dry_run:
            print("Mode: DRY-RUN (no files deleted)", file=sys.stderr)
            print(f"Log: {output_log}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)

        return True

def main():
    parser = argparse.ArgumentParser(
        description='Remove duplicate files based on content hash'
    )
    parser.add_argument('--source', required=True, help='Directory to scan')
    parser.add_argument('--report', required=True, help='Output audit log file')
    parser.add_argument('--execute', action='store_true', help='Actually delete files (dangerous!)')
    parser.add_argument('--dry-run', dest='execute', action='store_false', help='Dry-run mode (default)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.set_defaults(execute=False)

    args = parser.parse_args()

    if args.execute:
        response = input("WARNING: This will DELETE files. Are you sure? (type 'yes' to confirm): ")
        if response.lower() != 'yes':
            print("Aborted.", file=sys.stderr)
            sys.exit(1)

    cleanup = DuplicateCleanup(dry_run=not args.execute, verbose=args.verbose)
    success = cleanup.run(args.source, args.report)

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
