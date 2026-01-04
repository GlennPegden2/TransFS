# TransFS Backlog

Items to revisit and future feature ideas.

## 🎨 Polish & UX Improvements

### Download Log Window ANSI/Character Control Support
**Status**: Issue Identified  
**Priority**: Medium  
**Description**: The download log window in the web UI doesn't support ANSI escape sequences or carriage return (`\r`) for in-place progress updates. This causes progress indicators to display poorly - each percentage update creates a new line instead of updating the same line.  
**Current Behavior**: 
- DDL downloads show: `0% 0% 10% 10% 20% 20% ...` (many repeated lines)
- Torrent downloads show: `0% (0.0 kB/s) 10% (4501.2 kB/s) ...` (verbose line spam)
**Impact**: Download logs become very long and hard to read with multiple downloads.  
**Possible Solutions**:
- Add ANSI escape sequence support to the log viewer (e.g., using ansi-to-html library)
- Support `\r` (carriage return) to overwrite current line
- Change progress format to only show significant updates (10%, 25%, 50%, 75%, 100%)
- Add a separate "Progress" section that updates in-place, separate from the log
- Use a real-time progress bar component instead of text-based indicators

### File Browser Navigation with Browser Back Button
**Status**: ✅ Implemented  
**Priority**: Medium  
**Description**: The file browsers (Browse Native/Browse Virtual tabs) now integrate with browser history, making the browser's back/forward buttons functional for directory navigation.  
**Implementation**:
- URL routing implemented for each directory path (e.g., `/browse/native/Acorn/Atom/Software/`)
- HTML5 History API (`pushState`/`replaceState`) updates URL without page reload
- Each directory navigation creates a browser history entry
- On page load, URL is parsed and navigates to that directory
- popstate event handler restores directory state on back/forward
**Benefits**:
- Browser back/forward buttons work naturally for directory navigation
- Directory paths are bookmarkable and shareable
- Better user experience matching OS file browsers

### MEGA Download Progress Indicator
**Status**: Deferred  
**Priority**: Low  
**Description**: Add progress reporting for MEGA downloads similar to DDL/torrent downloads. Currently shows only "Starting..." → "Complete" feedback.  
**Technical Notes**: 
- mega.py library's `download_url()` doesn't expose progress callbacks
- Could implement file-size monitoring during download
- Mega downloads are typically fast enough that simple feedback may be sufficient

### Archive Extraction Skip Logic
**Status**: Issue Identified  
**Priority**: Medium  
**Description**: When `skip_existing: true` is enabled and a previous download exists but extraction failed, the file is skipped without re-attempting extraction.  
**Example**: ICEBIRD.7z was downloaded but not extracted, subsequent pack installations skip it entirely.  
**Possible Solutions**:
- Check if extraction artifacts exist (e.g., expected extracted files)
- Add a `.extracted` marker file after successful extraction
- Force re-extraction if archive exists but destination files don't

## 🔄 Download Management

### Torrent Download Architecture Review
**Status**: Issue Identified  
**Priority**: High  
**Description**: Current torrent implementation has significant issues that need addressing:
- Progress reporting doesn't update during download (shows "0% (0.0 kB/s)" until completion)
- Incomplete/stalled torrents can hang the entire pack installation process
- Synchronous torrent downloads don't fit well with async download architecture
- No timeout mechanism for slow/dead torrents
**Current Behavior**: Downloads 20GB of 43GB but UI shows 0% throughout
**Needed**:
- Fix progress reporting to update in real-time
- Add timeout/stall detection for incomplete torrents
- Consider moving torrents to background queue/separate process
- Allow cancellation of stuck torrent downloads
- Better async integration (currently uses `await asyncio.sleep()` polling)

### Reprocessing Already Downloaded Files
**Status**: Design Discussion Needed  
**Priority**: Medium  
**Description**: Determine strategy for handling files that have already been downloaded.  
**Questions**:
- When should we re-download? (Force flag, version checking, checksum validation?)
- How to handle partial/incomplete downloads?
- Should extraction be re-attempted if archive exists but files are missing?
- UI options: "Force Redownload", "Skip Existing", "Smart Update"?

### Download Resume Support
**Status**: Idea  
**Priority**: Low  
**Description**: Support resuming interrupted downloads for large archives.  
**Technical Notes**:
- HTTP Range requests for DDL
- Torrent already supports resume naturally
- MEGA may have built-in resume

### Checksum Verification
**Status**: Idea  
**Priority**: Low  
**Description**: Verify downloaded files against checksums when available (MD5, SHA256).  
**Benefits**:
- Detect corrupted downloads
- Avoid re-downloading identical files
- Could be used for "smart update" logic

## 🚀 New Features

### Automatic File Organization by Extension
**Status**: ✅ Implemented  
**Priority**: High  
**Description**: Add source-level option to automatically organize downloaded/extracted files into subdirectories by file extension.  
**Use Case**: Large mixed-content archives like arcarc.nl torrent contain multiple file types (ADF, HDF, ISO, etc.) that should be organized into per-extension folders.  
**Syntax**:
```yaml
- name: arcarc.nl
  type: tor
  url: https://arcarc.nl/torrents/arcarc%20archive%2020250414%20v0029.torrent
  folder: Software/Collections/arcarc.nl
  organize_by_extension: true  # or list of extensions
  organize_on_conflict: increment  # or 'skip', 'overwrite'
```
**Behavior**:
- Scans downloaded/extracted content recursively
- **Flattens** directory structure - moves all files to `{folder}/{EXTENSION}/` regardless of source subdirectory
- Example: `folder: Software` results in:
  - `*.adf` → `Software/ADF/`
  - `*.hdf` → `Software/HDF/`
  - `*.iso` → `Software/ISO/`
- Options:
  - `organize_by_extension: true` - organize all files
  - `organize_by_extension: [adf, hdf, iso]` - only specified extensions
  - Extensions should be case-insensitive
- **Duplicate Handling** (configurable):
  - `increment` (default): `FILE.HDF` → `FILE.HDF`, `FILE_1.HDF`, `FILE_2.HDF`
  - `skip`: Keep first file, skip duplicates
  - `overwrite`: Last file wins
**Technical Notes**:
- Run after extraction completes
- Run before rename operations
- Should clean up empty source directories after moving files
- Needs to handle nested archives (see separate backlog item)

### Nested Archive Extraction
**Status**: Feature Request  
**Priority**: Medium  
**Description**: Handle archives that contain other archives (e.g., ZIP files inside TAR files, or multiple levels of compression).  
**Use Case**: Some collections have nested archives (e.g., `.tar.gz` files containing `.zip` files containing ROMs).  
**Possible Approaches**:
- Recursive extraction with depth limit
- Specific pattern matching (e.g., `extract_nested: [zip, rar]`)
- Integration with organize_by_extension feature
**Technical Notes**:
- Need to avoid infinite loops with circular archives
- Consider memory/disk space implications
- Should preserve original archives or clean up after extraction?

### ZIP Navigation Performance for Large Archives
**Status**: Identified (2026-01-02)  
**Priority**: Medium  
**Description**: Current ZIP navigation in hierarchical mode works correctly but may have performance issues with very large archives (10K+ files).  
**Context**: Successfully implemented ZIP subdirectory navigation for Amstrad CPC Collections (e.g., AmstradCPC-CDT_Collection.zip with 3537 entries). Navigation and file access work correctly.  
**Performance Concerns**:
- ZipIndex builds file/directory sets on first access (lazy initialization)
- For massive archives, initial indexing may cause delays
- Repeated access patterns could benefit from better caching
- Directory listings with thousands of files may be slow
**Possible Optimizations**:
- Profile actual performance with real-world large archives (50K+ files)
- Consider partial/streaming index building for massive archives
- Add index warming during mount/startup for known large ZIPs
- Implement pagination/lazy loading for directory listings in UI
- Add performance metrics logging for slow operations
**Related**: Current implementation already has thread-local caching and index persistence support

### Nested ZIP Files (ZIPs inside ZIPs)
**Status**: Feature Request (2026-01-02)  
**Priority**: Low  
**Description**: Support navigating ZIP archives that are stored inside other ZIP archives.  
**Current Behavior**: ZIP files can be browsed in hierarchical mode, but ZIP files inside ZIPs are treated as regular files.  
**Use Case**: Some collections have nested ZIP organization (e.g., `collection.zip/games.zip/game.rom`).  
**Technical Challenges**:
- zippath currently uses filesystem paths - would need virtual path support
- Memory implications of mounting nested archives
- Performance concerns with deep nesting
**Possible Approaches**:
- Transparent extraction to temp directory for nested ZIPs
- Virtual filesystem path support in zippath (complex)
- Limit nesting depth to prevent abuse
- Consider if this is actually needed vs recommending archive reorganization

### Storage Optimization Strategy Configuration
**Status**: Feature Request (2026-01-02)  
**Priority**: Medium  
**Description**: Allow users to choose storage strategy to optimize for speed, space, or balance.  
**Use Case**: Users have different priorities - some want fastest access (unzip everything), others want minimal disk usage (keep everything zipped), most want a middle ground.  
**Proposed Configuration**:
```yaml
storage_strategy: balanced  # Options: speed, space, balanced, custom
```
**Strategy Behaviors**:
- **speed**: Auto-extract all archives after download, delete originals, optimize for read performance
  - Pros: Fastest file access, no decompression overhead
  - Cons: Large disk usage, longer initial setup
  - Best for: Users with plenty of disk space who want instant access
- **space**: Keep everything compressed, rely on transparent ZIP access
  - Pros: Minimal disk usage, faster downloads/syncs
  - Cons: Slight overhead on file access, indexing time for large ZIPs
  - Best for: Users with limited disk space or slow storage
- **balanced** (default): Extract frequently-accessed content, keep collections zipped
  - Smart extraction based on: file count, archive size, access patterns
  - Example: Extract BIOS/system files, keep ROM collections zipped
  - Configurable thresholds (e.g., extract if <100 files or <50MB)
- **custom**: Per-system or per-source configuration
  - Allow override at system/source level
  - Mix strategies based on content type
**Implementation Considerations**:
- Add `extract_after_download: auto/always/never` to sources
- Global setting with per-system overrides
- Consider access pattern monitoring to adapt strategy
- Need disk space checking before auto-extraction
- Ability to change strategy and reprocess existing content
**Related Features**:
- Could integrate with organize_by_extension feature
- Metrics to help users choose strategy (disk usage, access times)
- Migration tools to convert between strategies

### Torrent DHT/Tracker Configuration
**Status**: Idea  
**Priority**: Low  
**Description**: Allow configuration of torrent DHT nodes and tracker lists for better torrent performance.

### Internet Archive Collection Filtering
**Status**: Idea  
**Priority**: Low  
**Description**: Enhanced filtering options for IA collections beyond just file extensions.  
**Possible Filters**:
- Date ranges
- File size limits
- Regex patterns on filenames

### Source Dependency Management
**Status**: Idea  
**Priority**: Low  
**Description**: Allow sources to declare dependencies on other sources (e.g., BIOS must download before ROM pack).

### Pack Installation Scheduler
**Status**: Idea  
**Priority**: Low  
**Description**: Queue pack installations and download during off-peak hours or rate-limit bandwidth usage.

## 🐛 Known Issues

### unrar-free Limitations
**Status**: Documented  
**Priority**: Low  
**Description**: Using `unrar-free` (0.3.1) instead of proprietary `unrar`. May have compatibility issues with some RAR archives.  
**Note**: Works for basic RAR extraction but may not support all RAR5 features.

## 📝 Documentation

### Architecture Decision Records
**Status**: Future  
**Priority**: Low  
**Description**: Document key architectural decisions made during development.  
**Topics**:
- Pack-based distribution system
- Configuration split rationale
- Virtual directory mapping design
- Source-level extraction vs post_process

### User Guide Expansion
**Status**: Future  
**Priority**: Medium  
**Description**: Expand documentation with more examples and common workflows.  
**Topics**:
- Creating custom packs
- Adding new systems
- Troubleshooting guide
- Performance tuning

---

## How to Use This File

- Add new items as they come up during development
- Update status as work progresses
- Priority levels: Low, Medium, High, Critical
- Move completed items to a "Recently Completed" section or remove them
