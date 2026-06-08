#!/usr/bin/env python3
"""
Duplicate File Detection Tool
Scans a directory tree to identify exact and near-duplicate files.
"""

import os
import sys
import hashlib
from collections import defaultdict
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime

class DuplicateDetector:
    def __init__(self, root_path, sample_size=5000):
        self.root_path = Path(root_path)
        self.sample_size = sample_size  # bytes to read for initial hash
        self.file_hashes = defaultdict(list)  # hash -> [(path, size, mtime), ...]
        self.exact_duplicates = []
        self.near_duplicates = []
        self.scanned_count = 0
        self.error_count = 0

    def hash_file(self, filepath):
        """Compute SHA256 hash of first N bytes of file."""
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, 'rb') as f:
                chunk = f.read(self.sample_size)
                sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            self.error_count += 1
            return None

    def scan_directory(self):
        """Scan all files and compute hashes."""
        print(f"Scanning {self.root_path}...", file=sys.stderr)

        for filepath in self.root_path.rglob('*'):
            if filepath.is_file():
                self.scanned_count += 1
                if self.scanned_count % 1000 == 0:
                    print(f"  Scanned {self.scanned_count} files...", file=sys.stderr)

                file_hash = self.hash_file(filepath)
                if file_hash:
                    size = filepath.stat().st_size
                    mtime = filepath.stat().st_mtime
                    self.file_hashes[file_hash].append({
                        'path': str(filepath),
                        'size': size,
                        'mtime': mtime
                    })

    def find_exact_duplicates(self):
        """Find files with identical hashes."""
        for file_hash, files in self.file_hashes.items():
            if len(files) > 1:
                self.exact_duplicates.append({
                    'hash': file_hash,
                    'count': len(files),
                    'files': sorted(files, key=lambda x: x['path'])
                })

        self.exact_duplicates.sort(key=lambda x: x['count'], reverse=True)

    def similar_filename(self, name1, name2, threshold=0.8):
        """Check if two filenames are similar using sequence matching."""
        # Remove extensions for comparison
        n1 = Path(name1).stem.lower()
        n2 = Path(name2).stem.lower()

        matcher = SequenceMatcher(None, n1, n2)
        ratio = matcher.ratio()
        return ratio >= threshold

    def find_near_duplicates(self):
        """Find likely renamed copies based on filename similarity."""
        filenames = []
        for files_list in self.file_hashes.values():
            for file_info in files_list:
                filenames.append(file_info['path'])

        # Only check similar-sized files with similar names
        near_dup_groups = {}
        for i, f1 in enumerate(filenames):
            for f2 in filenames[i+1:]:
                if self.similar_filename(f1, f2):
                    # Group by normalized filename
                    key = Path(f1).stem.lower()
                    if key not in near_dup_groups:
                        near_dup_groups[key] = []
                    if f1 not in near_dup_groups[key]:
                        near_dup_groups[key].append(f1)
                    if f2 not in near_dup_groups[key]:
                        near_dup_groups[key].append(f2)

        self.near_duplicates = [
            {'name_stem': k, 'files': v}
            for k, v in near_dup_groups.items() if len(v) > 1
        ]

    def categorize_by_location(self):
        """Categorize duplicate files by directory."""
        location_counts = defaultdict(int)

        for dup_group in self.exact_duplicates:
            for file_info in dup_group['files']:
                dir_path = Path(file_info['path']).parent
                location_counts[str(dir_path)] += 1

        return sorted(location_counts.items(), key=lambda x: x[1], reverse=True)

    def recommend_keeper(self, files):
        """Recommend which file to keep (prefer deepest path, newest mtime)."""
        # Prefer deepest path (more specific location)
        files_sorted = sorted(files, key=lambda x: (x['path'].count(os.sep), x['mtime']), reverse=True)
        return files_sorted[0]

    def generate_report(self, output_file):
        """Generate dedup inventory report."""
        self.find_exact_duplicates()
        self.find_near_duplicates()
        location_counts = self.categorize_by_location()

        total_duplicate_files = sum(d['count'] for d in self.exact_duplicates)

        with open(output_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("DUPLICATE FILE DETECTION REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"Source: {self.root_path}\n\n")

            f.write("SUMMARY STATISTICS\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total files scanned: {self.scanned_count}\n")
            f.write(f"Scan errors: {self.error_count}\n")
            f.write(f"Exact duplicate groups: {len(self.exact_duplicates)}\n")
            f.write(f"Total duplicate copies: {total_duplicate_files}\n")
            f.write(f"Likely renamed copies: {len(self.near_duplicates)}\n\n")

            if location_counts:
                f.write("TOP DUPLICATE LOCATIONS\n")
                f.write("-" * 80 + "\n")
                for location, count in location_counts[:10]:
                    f.write(f"  {location}: {count} duplicates\n")
                f.write("\n")

            if self.exact_duplicates:
                f.write("EXACT DUPLICATE GROUPS\n")
                f.write("-" * 80 + "\n")
                for i, dup_group in enumerate(self.exact_duplicates[:20], 1):
                    f.write(f"\nGroup {i} (Hash: {dup_group['hash'][:16]}...)\n")
                    f.write(f"  Copies: {dup_group['count']}\n")

                    keeper = self.recommend_keeper(dup_group['files'])
                    f.write(f"  RECOMMENDED TO KEEP: {keeper['path']}\n")

                    for file_info in dup_group['files']:
                        is_keeper = " [KEEPER]" if file_info == keeper else ""
                        mtime_str = datetime.fromtimestamp(file_info['mtime']).isoformat()
                        f.write(f"    - {file_info['path']}{is_keeper}\n")
                        f.write(f"      Size: {file_info['size']} bytes, Modified: {mtime_str}\n")

            if len(self.exact_duplicates) > 20:
                f.write(f"\n... and {len(self.exact_duplicates) - 20} more duplicate groups\n")

            if self.near_duplicates:
                f.write("\n" + "=" * 80 + "\n")
                f.write("LIKELY RENAMED COPIES (Fuzzy Filename Match)\n")
                f.write("-" * 80 + "\n")
                for i, group in enumerate(self.near_duplicates[:15], 1):
                    f.write(f"\nGroup {i}: {group['name_stem']}\n")
                    for filepath in group['files']:
                        f.write(f"  - {filepath}\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("DEDUPLICATION STRATEGY\n")
            f.write("-" * 80 + "\n")
            f.write("""
EXACT DUPLICATES:
  Action: Delete copies, keep canonical version
  Selection Criteria:
    1. Prefer deepest directory path (more specific location)
    2. If equal depth, prefer most recent modification time
    3. Flag any dated/backup/archive versions for removal

LIKELY RENAMED COPIES:
  Action: Review and manually confirm before deletion
  - May represent intentional copies with different purposes
  - Fuzzy match can have false positives
  - Recommend manual review before bulk deletion

ORPHANED/REDUNDANT COPIES:
  - Identify files in temporary/cache directories
  - Flag old versions in date-stamped folders
  - Mark for review and removal

IMPLEMENTATION:
  dupe_clean.py --source <path> --keep-canonical --report <output> --dry-run
""")

            f.write("\n" + "=" * 80 + "\n")
            f.write("RECOMMENDATIONS\n")
            f.write("-" * 80 + "\n")
            f.write("""
1. DATABASE INTEGRATION:
   - Add content_hash field to file metadata table
   - Index by hash for quick duplicate lookup
   - Track canonical vs. copy status

2. AUTOMATED CLEANUP:
   - Create dupe_clean.py tool (modeled on repo-browser dupe_clean.py)
   - Implement dry-run mode for safety
   - Log all deletion actions for audit trail

3. ONGOING PREVENTION:
   - Add dedup check to document ingestion pipeline
   - Warn before accepting files with existing hash
   - Consider content-addressable storage (CAP) for new uploads

4. PERIODIC REVIEW:
   - Schedule monthly dedup scan
   - Review near-duplicates manually (fuzzy matches)
   - Update canonical versions as needed

5. STORAGE OPTIMIZATION:
   - Implement hard links or copy-on-write for exact duplicates
   - Move orphaned copies to archive directory
   - Track storage savings metrics
""")

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"Report generated: {datetime.now().isoformat()}\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: dedup_detector.py <root_path> [output_file]")
        sys.exit(1)

    root_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "dedup_report.txt"

    if not os.path.isdir(root_path):
        print(f"Error: {root_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    detector = DuplicateDetector(root_path, sample_size=5000)
    detector.scan_directory()
    detector.generate_report(output_file)

    print(f"Report written to {output_file}", file=sys.stderr)

if __name__ == '__main__':
    main()
