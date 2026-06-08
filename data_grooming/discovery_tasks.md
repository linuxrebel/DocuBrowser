# DocuBrowse Data Grooming — Discovery Tasks

**Purpose:** Understand data quality, format distribution, and gotchas before building extractors.  
**Output:** Classification reports, quality metrics, handling recommendations.

---

## Task 1: Classify No-Extension Files (591 files)

**Question:** What are the 591 files with no extension? Text? Binary? Corrupted?

**Approach:**
1. Sample 50 random no-ext files
2. For each, determine:
   - **Is it text?** (read first 512 bytes, check for UTF-8 validity + printable chars)
   - **File size:** Empty? Huge? Normal?
   - **Purpose:** README, log, config, data, unknown?
   - **Keep?** Yes / No / Needs renaming?
3. Categorize findings

**Output:** `data_grooming/reports/no_ext_classification.txt`
```
Total sampled: 50
Text (indexable): X
Binary (skip): Y
Empty/corrupted: Z
Needs renaming: W

Recommendations:
- Skip binary files
- Index text files as-is (tag: "no_ext")
- Delete corrupted files
- Suggest rename for: [list]
```

**Parallel execution:** ✓ Can run independently

---

## Task 2: Analyze HTML Files & URL-Encoded Variants (6,004 files)

**Question:** What are HTML files? What does `htmlc=m;o=a` mean? How much real content?

**Approach:**
1. Sample 50 random HTML files (including variants with encoding patterns)
2. For each:
   - **Structure:** Is it `.html`, `.mhtml`, or other? Any archive markers?
   - **Metadata:** `<title>`, `<meta name="description">`, source URL?
   - **Content:** Real text or mostly boilerplate/ads/nav?
   - **Size:** How much text vs HTML bloat?
3. Inspect filename patterns (htmlc=m;o=a, htmlc=n;o=d, etc.)
4. Estimate extraction ROI (% real vs noise)

**Output:** `data_grooming/reports/html_analysis.txt`
```
Total sampled: 50
.html files: X
.mhtml files: Y
URL-encoded variants: Z (pattern: htmlc=m;o=a means... ?)

Content quality:
- Good (>70% real text): A%
- Moderate (40-70%): B%
- Poor (<40% boilerplate): C%

Recommendations:
- Extract title + first 2000 chars
- Skip script/style tags
- Handling for .mhtml: [decision]
- URL-encoded variants: [decision - skip? rename?]
```

**Parallel execution:** ✓ Can run independently

---

## Task 3: Detect Duplicates & Near-Duplicates

**Question:** How many files are duplicates? Copies across folders? Renamed copies?

**Approach:**
1. Compute SHA256 hash of first 5000 bytes for all files
2. Find collisions (identical files)
3. Sample similar filenames (fuzzy matching on name)
4. For each duplicate group:
   - **Locations:** Which folders?
   - **Sizes:** Identical or slightly different?
   - **Dates:** Modified times?
   - **Keep canonical:** Which version?

**Output:** `data_grooming/reports/dedup_inventory.txt`
```
Total files: 9998
Exact duplicates: X groups (Y total duplicates)
Likely renamed copies: Z groups

By folder:
  Companies/: A duplicates
  ClickCharts/: B duplicates
  [etc.]

Recommendations:
- Delete exact duplicates (keep deepest path)
- Flag renamed copies for review
- Dedup tool strategy: [delete vs consolidate vs ignore]
```

**Parallel execution:** ✓ Can run independently (intensive, consider parallel processing)

---

## Task 4: File Quality & Encoding Assessment

**Question:** Are there corrupted, oversized, or encoding-broken files?

**Approach:**
1. Scan all files for:
   - **Empty files** (0 bytes)
   - **Huge files** (>100MB, extraction overhead?)
   - **Encoding issues** (read as UTF-8, catch decode errors)
   - **Unreadable:** Binary files in text-only folders
2. Categorize by issue type

**Output:** `data_grooming/reports/file_quality.txt`
```
Total files: 9998
Empty files: X
Oversized (>100MB): Y
Encoding errors: Z
Corrupted: W

By severity:
- Skip (empty/corrupted): [count]
- Warn (oversized): [list + sizes]
- Encode as latin-1 fallback: [count]

Recommendations:
- Delete empty files
- Truncate oversized content to 10K chars
- Use latin-1 fallback for encoding errors
```

**Parallel execution:** ✓ Can run independently

---

## Task 5: Sensitive Files Inventory

**Question:** Should we index .key, .pem, .p12, .ppk files? Or redact?

**Approach:**
1. Find all sensitive file types: `.key`, `.pem`, `.p12`, `.ppk`, `.ppk`, `.crt`, `.cer`
2. For each:
   - **Location:** In what folder?
   - **Purpose:** SSH key? TLS cert? AWS key? Unknown?
   - **Content preview:** First line (without exposing secrets)
3. Decide: index as-is, redact, or skip?

**Output:** `data_grooming/reports/sensitive_files.txt`
```
Total sensitive files: X
By type:
  .key: A
  .pem: B
  .p12: C
  [etc.]

By location:
  Companies/: count
  [etc.]

Recommendations:
- Skip indexing (security risk)
- If indexed, redact key material
- Alert on suspicious files (in unusual folders)
```

**Parallel execution:** ✓ Can run independently

---

## Task 6: Format Distribution & Extraction Priority

**Question:** Which formats are worth building extractors for? Priority order?

**Approach:**
1. Group files by extractable vs skippable formats
2. Estimate extraction effort vs ROI:
   - **High ROI:** PDF (12%), DOCX (0.9%), TXT (1%), HTML (60%)
   - **Medium ROI:** XLSX (0.2%), PPTX (0.2%), MD (0.2%)
   - **Low ROI:** Code files (1.5%), config (1%), ebooks (3%)
   - **Skip:** Fonts, images, binaries, archives
3. Calculate: if we skip low-ROI, what % of corpus do we lose?

**Output:** `data_grooming/reports/format_priority.txt`
```
Extraction priority:

Tier 1 (MVP):
  - HTML (60%): high ROI, messy extraction, needs investigation
  - PDF (12%): medium effort, good ROI
  - TXT/plain (1%): trivial
  - DOCX (0.9%): medium effort

Tier 2 (Phase 2):
  - XLSX (0.2%): effort for structured data
  - PPTX (0.2%): effort, lower content
  - MD (0.2%): easy, small corpus

Tier 3 (Skip/Later):
  - Ebooks (3%): need external libs, DRM issues
  - Code (1.5%): large, low signal for doc search
  - Configs (1%): sensitive, low value
  - Binaries/assets (5%): skip

Coverage if we skip Tier 3: [X]% of corpus
```

**Parallel execution:** ✓ Can run independently (depends on Tasks 1-2 outputs)

---

## Task 7: Folder Structure & Organization

**Question:** Is Documents folder organized by content type? Any reorganization recommended?

**Approach:**
1. Analyze top-level folders and their contents
2. Identify: what's in Companies/, ClickCharts/, root, etc.?
3. Are there natural groupings (by doc type, project, category)?
4. Recommendations: reorganize or accept as-is?

**Output:** `data_grooming/reports/folder_structure.txt`
```
Current structure:
- Companies/: [sub-folders], [file types], [count]
- ClickCharts/: [...]
- Root: [file types], [count]

Analysis:
- Self-organized? Yes/No
- Recommendation: keep / flatten / reorganize

Tagging strategy:
- Folder name → tag: [decision]
- Example: Companies/Areotek/ → tags: Companies, Areotek
```

**Parallel execution:** ✓ Can run independently

---

## Task 8: Binary Relationships & Integrity (DEFERRED)

**Status:** Address after Tasks 1-7 complete.

**Question:** Which binaries (images, attachments) are embedded/referenced by documents? Which are orphans?

**Approach (using embeddings, like repo-browser):**
1. Extract all document content + text snippets
2. Extract all binary metadata (filename, alt-text, size, type)
3. Generate embeddings for documents AND binaries via Ollama
4. Use cosine similarity to find likely parent-child relationships:
   - Image embedding vs document embedding (high similarity = likely reference)
   - Filename matching (e.g., "logo.png" appears in doc → reference)
   - Embedded metadata (e.g., image src in HTML, OLE object in DOCX)
5. Mark binaries as: **attached** (has parent), **orphan** (no parent), **ambiguous** (multiple possible parents)

**Output:** `data_grooming/reports/binary_integrity.txt`
```
Total binaries: X
Attached (has parent): Y
Orphans (no parent): Z
Ambiguous (multiple parents): W

By type:
  Images (.png, .jpg): [attached/orphan counts]
  Fonts (.woff2, .ttf): [...]
  Archives (.zip, .gz): [...]
  Other binaries: [...]

Orphan handling:
- Delete? Mark for review? Keep?
- Relationships to preserve in DB schema

Recommendations:
- Preserve parent-child edges in doc schema
- Tag orphans for later dedup (like repo-browser dupe_clean.py)
- Embed integrity check in scanner
```

**Dependencies & Open Questions (to address after 1-7):**
- Should we install extraction libraries on-demand during Phase 2?
- Create a document extraction skill now or defer?
- Are extraction libs needed for Tasks 1-7 discovery?
- Which formats (PDF, DOCX, EPUB) are worth supporting for binary detection?

**Parallel execution:** ✓ Can run after Tasks 1-7 + decision on extraction approach

---

## Execution Plan (MVP: Tasks 1-7)

| Task | Priority | Est. Time | Parallel? | Dependencies |
|------|----------|-----------|-----------|--------------|
| 7. Folder Structure | High | 15 min | ✓ | None |
| 1. No-ext files | High | 20 min | ✓ | None |
| 2. HTML analysis | High | 30 min | ✓ | None |
| 4. File quality | Medium | 30 min | ✓ | None |
| 5. Sensitive files | Medium | 15 min | ✓ | None |
| 3. Duplicates | Medium | 60 min | ✓ | None (intensive) |
| 6. Format priority | Medium | 20 min | ✓ | Tasks 1, 2 |

**Total serial:** ~3.5 hours  
**With 6 parallel agents:** ~1 hour

**Task 8 (Binary Relationships):** Deferred. Address after Tasks 1-7 complete and decisions made on extraction library strategy.

---

## Success Criteria (MVP: Tasks 1-7)

- [ ] All 7 discovery reports generated
- [ ] Data quality baseline established
- [ ] File type priorities clarified
- [ ] Orphan/sensitive file handling decisions made
- [ ] Duplicate detection strategy validated
- [ ] Folder organization approach decided
- [ ] No-ext file classification complete
- [ ] HTML extraction feasibility confirmed

**Post-MVP (Task 8):**
- [ ] Extraction library strategy defined (on-demand vs skill vs Phase 2)
- [ ] Binary integrity & relationships mapping approach approved
- [ ] Cleanup/reorganization plan finalized
- [ ] Ready to start Phase 2 (building extractors)
