# TransFS Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- Renamed the Debug tab to Logs in the web UI for future log expansions.
- System support icons now reflect pack-level `supported_by` metadata when available, ensuring system badges match pack client coverage.
- **Cache Naming & UI Cleanup**: Renamed file attribute caching to **Stat Cache** in UI and API
  - Updated cache configuration endpoints to use `stat_cache_*` keys
  - Dashboard now surfaces Stat Cache and ZIP Index cache stats
  - Removed directory cache indicators and hit-rate cards tied to deprecated pickle caches
  - Removed Cache tab in favor of Config-tab cache controls and inline virtual browser status

### Removed
- **Deprecated Directory Pickle Cache Controls**: Removed config toggles and UI controls for directory listing pickle caches
  - Directory cache has been disabled in code for stability and staleness reasons
  - Cache UI now reflects only active caches (Stat Cache, ZIP Index, Transform caches)

### Fixed
- Restored Test Results tab rendering, including per-test output parsing, run tabs, and progress updates.
- Restored download log carriage return handling so progress updates overwrite the current line instead of spamming new lines.
- Restored Debug tab log loading by fetching FUSE logs from the correct endpoint on tab activation.
- Fixed Debug tab log fetch path to use `/api/logs` (API is mounted under `/api`).
- Restored test progress status rendering to keep the progress bar updated during test runs.
- Pack installation now selects a valid configured client when pack `supported_by` includes clients not present in the current config set.
- Restored Browse Native/Virtual functionality in the web UI (rich file rendering, Zaparoo launch controls, metadata panel, cache status, and deep-link initialization).
- **Metadata Rulesets Docker Accessibility**: Moved `/config/metadata/rulesets/` to `/app/config/metadata/rulesets/`
  - Ensures ruleset YAML files are accessible inside Docker container
  - Previous location was outside `/app` directory mount point
  - Affects GoodTools, TOSEC, Atarimania, and other metadata parsing rulesets
- **File-Based Map Database Sync**: Extended database sync to properly handle file-based maps (e.g., `boot.vhd`)
  - Fixed `_sync_system()` to process both file-based maps and query maps
  - Added `_sync_file_based_map()` handler for single-file map entries
  - Flush file-based map entries before query map scanning to prevent overwrites
- **File-Based Map Path Resolution**: Fixed sourcepath.py to resolve file-based maps
  - Added support for `file:` configuration format in get_source_path()
  - Handles both regular files and ZIP archives with unzip/zip_internal_file options
  - Ensures file-based maps appear in FUSE directory listings
- **Pack Default Extension for Nested Folders**: Fixed `metadata.defaults.extension` feature for deeply nested folder structures
  - Added per-file pack context lookup in _scan_system_directory() to apply default extensions
  - Fixes RetroBat Acorn Atom: 3,197 extensionless files (in Software/Sources/hoglet67/*/...) now indexed with ATM extension
  - Default extensions applied before query map matching, allowing files to match appropriate maps
  - Source folder path corrected in Atom.yaml from Science Collections to Software/Sources/hoglet67
- **File-Based Map Metadata Enrichment**: Fixed metadata enrichment for file-based maps
  - Modified sync_database.py to commit files before enriching metadata
  - Changed enrichment.py to use commit=True for file_metadata INSERT
  - Resolves foreign key constraint violations during sync
  - Ensures file-based maps have complete metadata available in database and API
  - Added deduplication logic to preserve file-based map assignment when same file appears in multiple maps
  - Updated upsert query to use COALESCE to preserve existing map_name on conflict
  - Ensures files from file-based maps are synced with correct `client`, `system`, and `map_name` columns
- **File-Based Map Path Resolution**: Added support for 'file' config format in get_source_path()
  - Handles file-based maps alongside legacy 'default_source' format
  - Supports ZIP files with unzip and zip_internal_file options
  - Enables boot.vhd and other file-based maps to resolve correctly in FUSE filesystem
  - Fixes missing file-based map entries appearing in system-level directory listings
- **File-Based Map Metadata Enrichment**: Added metadata enrichment during file sync
  - Modified _flush_file_batch() to enrich metadata for synced files
  - Captures file_ids from UPSERT RETURNING clause
  - Calls enrich_file_metadata() for each file after insertion
  - Fixes "no metadata available" message for boot.vhd and other file-based maps in UI

### Added
- **Multi-Config-Set Support**: Switch between different configuration libraries for clients and sources
  - New directory structure: `config/clients/<set_name>/` and `config/sources/<set_name>/`
  - Moved default configs to `config/clients/default/` and `config/sources/default/`
  - Active config sets tracked in app.yaml: `config_sets.active_client_config`, `config_sets.active_source_config`
  - UI in Config tab with dropdowns to switch between config sets (triggers page reload)
  - ZIP import functionality to upload and extract new config sets
  - Backend API endpoints:
    - GET `/api/config/sets` - List available config sets
    - GET `/api/config/sets/active` - Get currently active config sets
    - POST `/api/config/sets/switch` - Switch active config set
    - POST `/api/config/sets/import` - Import ZIP containing new config set
  - Maintains backward compatibility with legacy flat structure
  - Useful for testing configurations, production vs development, or different source collections

- **API Namespace Organization**: All API endpoints now consistently accessible under `/api/` prefix
  - FastAPI app mounted at `/api` in main.py for clean namespace
  - Swagger documentation available at `/api/docs` and `/api/redoc`
  - OpenAPI spec at `/api/openapi.json`
  - All endpoints properly tagged for Swagger organization (Clients & Systems, Downloads, Database, Cache, File Browsing, System)
  - Frontend HTML already calling `/api/*` endpoints for compatibility

### Added (Previous)
- **Modular Client Configuration**: Refactored clients.yaml into per-client files for better maintainability
  - Created `app/config/clients/` directory with individual YAML files: `mister.yaml`, `mame.yaml`, `retrobat.yaml`, `retropie.yaml`, `generic.yaml`
  - Updated `read_clients_config()` to dynamically discover and load all YAML files from clients directory
  - Maintains backward compatibility with legacy `clients.yaml` as fallback
  - Enables parallel contributions and reduces merge conflicts as configs grow
  - MiSTer client: 40+ systems with detailed mappings in dedicated mister.yaml
- **Streaming Sync Progress**: Database sync API now supports Server-Sent Events for real-time progress updates
  - Added `stream=true` parameter to `/api/db/sync` endpoint
  - Streams progress messages for client/system processing, file counts, and completion status
  - Includes heartbeat messages to keep connection alive during long syncs
  - Progress callbacks throughout sync process emit structured JSON events
- **System-Wide File Scanning**: Database sync now scans entire system base paths instead of per-map directories
  - Finds all files under a system's local_base_path (e.g., `/Native/Acorn/Atom/`)
  - Matches files to maps based on extension, regardless of subdirectory location
  - Eliminates issues with files in non-standard locations (e.g., `Software/VHD/` vs `Software/Sources/`)
  - Single scan per system instead of multiple scans per map
- **Batch Processing Performance**: Implemented PostgreSQL bulk upsert for 2.4x sync speedup
  - Added file batching with configurable `BATCH_SIZE` (default 1000 files)
  - Uses `executemany()` with `ON CONFLICT DO UPDATE` for efficient bulk operations
  - Performance improvement: 384s → 158s for ~12,000 files (2.4x faster)
  - Reduced database round-trips from per-file to per-batch

### Changed
- **Sync System Consolidation**: Unified to single DatabaseSync implementation
  - Removed dual-sync architecture (FilesystemSync + DatabaseSync)
  - Updated API `/api/db/sync` endpoint to use DatabaseSync exclusively
  - Updated data_provider_db sync_on_startup to use DatabaseSync
  - Moved deprecated db/sync.py to legacy folder
  - All syncs now properly populate system/client/map_name fields
- **Configuration Performance**: Added LRU cache to read_config() function
  - Eliminated 870ms overhead on every API request
  - API browse requests reduced from 2.8s to <100ms
  - Added reload_config() function to clear cache when needed
- **Metadata Enrichment Race Condition Fix**: Fixed foreign key violations during concurrent sync
  - Changed _ensure_lookup() to use `INSERT ON CONFLICT DO NOTHING` with commit=True
  - Eliminates race conditions when multiple files try to create same lookup entries
- **Default Extension Support**: Pack metadata can now specify `extension` in defaults to assign extensions to files without one
  - Added `default_extension` field to `PackContext` dataclass
  - Modified database sync to apply default extension during file scanning when files lack an extension
  - Updated Acorn Atom pack configuration to use `extension: ATM` in defaults for files without extensions
  - Enables proper handling of archives with extensionless files (e.g., hoglet67 Acorn Atom software archive)

### Fixed
- **Zaparoo Launch Path Normalization**: Added lstrip("/") to path construction
  - Fixes Zaparoo launch failures where paths started with double slash (//)
  - Ensures clean path construction from virtual_path components
- Fixed schema initialization to execute multi-statement SQL safely and continue after idempotent failures
- Improved virtual mappings generation to match systems using normalized client config fields

### Performance
- Database sync: 384s → 158s (2.4x faster) for ~12,000 files
- API latency: 2.8s → <100ms for browse requests
- Database connection pooling: 5-15 concurrent connections
- Batch size: 1000 files per bulk operation

### Migration Notes
- **PostgreSQL Migration (COMPLETE)**
  - Replaced SQLite with PostgreSQL 15-alpine in docker-compose
  - Added persistent postgres_data volume for database persistence
  - Implemented psycopg2-binary connection pooling (5 min, 15 max connections)
  - Converted all database operations to use PostgreSQL %s parameter syntax
  - Updated schema.py for PostgreSQL (SERIAL PRIMARY KEY, BIGINT timestamps, BOOLEAN types)
  - Migrated all SQL queries from ? to %s placeholders across all modules
  - Converted SQLite-specific syntax to PostgreSQL equivalents
  - Fixed RealDictCursor row access (dict keys instead of tuple indices)
  - Eliminated concurrent access locking errors with PostgreSQL MVCC
  - Validated: 20,213 files indexed, 6,641 enriched with metadata

### Added
  - Added info icon next to Zaparoo button with hover tooltip for file metadata
  - Added `/api/file-metadata` endpoint to serve normalized metadata for UI display
- **Source-Based Download Layout**
  - Added source-based download layout option to store files under Software/Sources/<source>
  - Applied MiSTer default download layout to source-based storage
  - Sync, listing, and source-path resolution now support recursive source folders
- **Atarimania Ruleset**
  - Renamed Atari 2600 ruleset to atarimania
  - Linked Atari 2600 pack metadata and client config to the renamed ruleset
- **Filename Parsing Enhancements for Atari 2600**
  - Date/Year bracket detection to derive title prefix and publisher candidate
  - Fallback publisher extraction from remaining tags (excluding Prototype/CX/MT/DA)
  - Added PAL/SECAM region recognition
  - Stored parsed title in file metadata
- **Database-Only Architecture for Query Maps** - Complete end-to-end database-driven file access
  - Query maps (FDs, HDs, etc.) now bypass parse_trans_path entirely
  - Three-tier database-only implementation:
    1. **Readdir**: query_files_by_client_system_and_map() → 76+ files, pagination support
    2. **Getattr**: query_file_by_client_system_map_and_name() → stat structures with mtime/size
    3. **Open**: Direct database lookup → transform pipeline → source file access
  - Validated: 76 FDs files + 420 HDs files successfully listed, stat'd, and read
  - File integrity verified: 143KB test file copied correctly (bit-for-bit match)
  - Performance: Database queries replace expensive parse_trans_path/filesystem traversal

- **Database-Only Readdir for Query Maps** - Query map directories now list files from database without filesystem access
  - Eliminates parse_trans_path overhead for directory listings
  - Direct database queries via query_files_by_client_system_and_map()
  - Proper extension filtering from query.extensions configuration
  - Pagination support for large directories (tested with 76 FD files)
  - Graceful fallback to filesystem mode if database fails
  - Validates query map configuration before attempting database mode

- **Database-Only Getattr for Query Maps** - File attribute queries now use database-only lookups
  - Query single files by client/system/map/filename via query_file_by_client_system_map_and_name()
  - Proper stat structures with size and mtime from database
  - Transform size adjustment for transformed files
  - Significantly faster than filesystem-based stat calls

- **Database-Only Open for Query Maps** - File opens now resolved via database lookups
  - Simplifies source path resolution for files in query maps
  - Applies transform pipelines after database lookup
  - Complete database-driven file access without parse_trans_path overhead
  - Tested: Successfully reading file contents for Apple-II disks

- **Byte-Size Filtering for Source Paths** - New `extension_filters` configuration for per-extension byte-size constraints
  - Configure size limits per file extension (e.g., 2MG files < 865KB go to FDs, ≥ 865KB go to HDs)
  - Filter source paths to separate collections by file size at database query time
  - Useful for separating multi-purpose extensions (e.g., 2MG can be FD or HD image)
  - Configuration: Add `extension_filters: {2MG: {max_size: X, min_size: Y}}` to query map config
  - Applied in both query_files_by_client_system_and_map and query_files_by_system_and_query
  - Validation: Apple-II FDs (2MG ≤ 865KB) = 76 files, HDs (2MG > 865KB) = 210 files correctly separated

- **Normalized Metadata Tables (Initial Implementation)**
  - Added controlled vocab tables (media types, regions, languages, genres, app types, publishers)
  - Added `file_metadata`, `file_tags`, `packs`, `file_packs`, and `metadata_edits` tables

### Fixed
- Fixed PostgreSQL sync cleanup in sync_database.py to return pooled connections cleanly
- Added progress logging during file counting in database sync to show filesystem walk activity - Improved database sync UI responsiveness by adding early initialization logging and output flushing- **Download Log CR Handling**
  - Added carriage-return-aware progress output for DDL and torrent downloads
  - Updated UI log renderer to handle in-place progress updates without line spam
  - Added filename-based metadata enrichment hook during database sync
  - Pack-level metadata defaults now flow into metadata enrichment during sync
  - Added starter ruleset files for GoodTools and TOSEC in config/metadata/rulesets
- **Query Map Database Lookup Alignment**
  - Aligns database query `source_dir` with source-based layout
  - Falls back to system name when manufacturer/system identifiers differ
  - Prevents slow filesystem scans for large ROM directories when database mode is enabled
- **Database Readdir Cache for Query Maps**
  - Caches database-only readdir results to avoid repeated full queries during large listings
  - Reduces listing time for large ROM directories (e.g., Atari 2600 ROMs)
- **Unique Virtual Filenames for Duplicates**
  - Disambiguates virtual filenames when multiple source files would collide
  - Prevents duplicate entries in virtual listings and avoids OS confusion
  - Reuses existing virtual filename when the same source path already exists (update instead of duplicate)
- **Database Sync Performance Optimization**
  - Uses single persistent database connection with batched commits (100 files per batch)
  - Eliminates per-file connection overhead, dramatically improving sync speed
  - Adds file counting and progress reporting every 100 files
  - Progress shown as percentage and file count (e.g., "Progress: 45.2% (3000/6639)")

### Fixed
- **Database Sync Schema Initialization** - Sync now uses centralized schema initialization
  - Ensures v2 metadata tables are created during sync
  - Prevents missing-table errors during metadata enrichment

- **SQLite PRAGMA Compatibility on WSL Mounts** - Disabled WAL mode to avoid disk I/O errors
  - Uses DELETE journal mode for mounted filesystem compatibility

- **Pack Context Folder Matching** - Normalized pack folder paths during sync
  - Supports folders that already include Software/ prefixes
  - Enables pack defaults to match files stored under Software/BIN layouts

- **Atari 2600 Pack Source Folder Alignment** - Source folder now matches on-disk Software/BIN layout
  - Allows pack metadata defaults to resolve against actual file paths

- **Explicit output_extension Configuration for Transformed Files** - Large 2MG files in HDs now appear as .hdv
  - Issue: 2MG files ≥ 908,289 bytes appearing with wrong extension (.do) in HDs directory
  - Root cause: TwoMGTransform auto-detection returning "do" format override explicit "output_extension: hdv" config
  - Solution: Modified TransformPipeline.get_effective_output_extension() to prioritize explicit config over auto-detection
  - Result: Files in HDs map now correctly display as .hdv, FDs files still show as .do/.po based on detection
  - 494 FDs files properly filtered and displayed, 6 HDs files with large 2MG images now in .hdv format

- **Case-Insensitive Extension Transform Lookup** - Fixed transforms not applying when extension case mismatched
  - Issue: Database stored extensions as lowercase (e.g., "2mg") but FUSE code looked up transforms with uppercase keys ("2MG")
  - Solution: Updated all extension lookups in transform map to try both uppercase and lowercase
  - Impacts: READDIR file renaming, getattr size adjustment, all places using system_transform_map
  - Tested: 2MG files correctly transformed regardless of extension case in database

- **Extension-Aware Sample File Selection** - Transform detection now uses appropriate sample files for size-filtered extensions
  - Issue: Building transform pipeline for 2MG files in HDs was finding small floppy samples instead of large drives
  - Solution: When building system transform map, filter sample files by extension_filters to match the map's size constraints
  - Result: HDs map correctly detects hard drive format characteristics using large 2MG file samples

- **System Name Format Normalization** - Fixed FUSE queries failing to find files in database
  - Issue: Database stored system names as "Apple/AppleII" (from source_path extraction) but FUSE queries used "Apple-II" format
  - Root cause: System name mismatch prevented query_files_by_client_system_and_map() from matching database records
  - Solution: Normalized all system names in database to match URL path format (e.g., "Apple-II" instead of "Apple/AppleII")
  - Validation: 4th & Inches 2MG files (819KB) now correctly appear in FDs listing, 500+ disk files restored

- **Database Out-of-Sync Issues After Schema Changes** - Complete database resync and population
  - Issue: After adding client and map_name columns, database required repopulation with correct values
  - Solution: Extracted system names from source_path patterns and populated client='MiSTer' for all 15,984 files
  - Map name assignment: Matched file extensions to virtual directories (/2mg/→2MG, /hdv/→HDs, /dsk/→FDs, etc.)
  - Size-based filtering: Applied 908,288-byte threshold for 2MG files (≤threshold→FDs, ≥threshold→HDs)
  - Result: Database fully synced with 510 files in FDs, 6 files in HDs for Apple-II system

- **Query Map Extension Configuration** - Fixed readdir not finding extensions in query config
  - Issue: Extensions were stored under query.extensions but code looked for top-level extensions
  - Solution: Updated _readdir_database_only to use get_query_config() to access nested extensions

- **2MG Transform Bogus Header Support** - Fixed reading 2MG files with invalid data_offset values
  - Issue: 2MG files with bogus data_offset=819200 (should be 64) only read 69 bytes instead of 819KB
  - Root Cause: Header field pointed beyond actual data, clamping calculation limited reads
  - Solution: Added validation in `_parse_header()` to detect and reject bogus offsets
  - Validation: If data_offset leaves <1KB data remaining, use header_size (64) instead
  - Impact: Also fixes format detection (FD vs HD) which was using bogus offset in calculations
  - Verification: Files now read full 819200 bytes with correct disk data (not "2IMGRVLW" header)

- **2MG Format Detection Threshold** - Updated floppy/hard disk threshold to 800KB
  - Changed from 200KB to 800KB to match Apple IIe 3.5" floppy capacity
  - Files ≤800KB: Classified as floppy (.do/.po based on format byte)
  - Files >800KB: Classified as hard disk (.hdv)
  - Supports both 140KB (5.25") and 800KB (3.5") floppy formats


- **Query Map Listing Performance** - Avoided expensive per-entry resolution in query map directories
  - Issue: Large query map directories (e.g., Apple-II FDs) took several minutes to list
  - Solution: Added fast-path readdir for query maps to emit entries without per-file stat
  - Impact: Listings return immediately; file stats are resolved on demand

- **Data Corruption in Large File Delivery** - REVERTED problematic retry logic in read() function
  - Issue: Previous "fix" for FUSE short reads introduced data corruption
  - Root Cause: Concatenating multiple os.read() calls corrupted the byte stream
  - Solution: Reverted to original simple read() function (single os.lseek + os.read call)
  - Verification: Files now return correct MD5 checksums
    - boot.vhd: b9e3f5e78ccfb5d7523f82f3113445ca ✓ (was corrupted with retry logic)
    - Size: 104.8 MB delivered correctly, no truncation
  - Impact: MiSTer will receive correct file checksums and boot properly
  - Note: FUSE short read issue resolved by kernel/pyfuse3 v3.4.2 - works correctly without retry logic

- **Query Map File Access** - Fixed inability to open files from query map directories
  - Issue: Files listed in query maps (e.g., HDs/) couldn't be opened - returned "file not found"
  - Root Cause: File resolution code didn't query database for actual file locations
  - Solution: Added database lookup in `TransFS.open()` to resolve query map filenames to actual paths
  - Verification: Query maps now list and open files correctly, full reads work with correct checksums
  - Impact: Query map-based views (HDs, FDs, etc.) are now fully functional

- **Query Map Directory Listing (Apple-II)** - Fixed empty FDs/HDs listings despite indexed files
  - Issue: /MiSTer/Apple-II/FDs and /MiSTer/Apple-II/HDs appeared empty even though files existed
  - Root Cause: Query-map resolution was skipped when `...SoftwareArchives...` was absent; readdir sent no entries
  - Solution: Allow query-map resolution without `...SoftwareArchives...` and add a safe fallback listing for query maps
  - Verification: Apple-II FDs/HDs now list correctly with transformed extensions (do/po/hdv)

### Added (Phase 3 Batch Testing - WIP)
- Batch dual-mode verification for target systems via legacy scripts (filesystem vs database counts)
- Helper scripts moved to legacy for non-production use: `fix_systems_batch.py`, `phase3_batch_verify.py`, `phase3_sync_and_cleanup.py`, `phase3_diff_report.py`, `phase3_dualmode_batch.py`

### Changed
- Moved migration-only Python scripts from app/ to legacy/
- Moved migration summaries/guides from repo root to docs/development/
- Enabled query-based mode for all `...SoftwareArchives...` maps via `db_mode: true`
- Passed `db_mode` and optional `extensions` from config into `list_dynamic_map()`
- Replaced `...SoftwareArchives...` with explicit query/file maps in clients.yaml
- Added structured query support for query maps and new schema documentation

### Added (Phase 2 Proof of Concept - BBC_B Real Data Validation - COMPLETE)
- **Phase 2.1-2.8**: BBC_B Pilot Implementation with Real User Data
  - Real-world test system: Acorn BBC_B with 52 actual software files (50 floppy images + 2 hard disk images)
  - Comprehensive Phase 2 documentation: `PHASE_2_BBC_B_COMPLETE.md` with detailed task breakdown and performance metrics
  - Database migration for BBC_B: All 52 files indexed with correct system extraction (Acorn/BBC_B)
  - Dual-mode validation: Verified identical results between YAML-driven (folder_based) and database-driven access
  - Flattening proof-of-concept: Successfully merged SSD/ + MMB/ subfolders into flat layout with rollback verification
  - Performance baseline established: Database queries 3-28ms, file access <16ms with mixed media types
  - Migration scripts created: `migrate_database_phase1.py`, `fix_bbc_b_system.py` for reusable system migrations
  - Comprehensive test suite: 8 test scripts validating assessment, queries, dual-mode, flattening, and performance
  - Backup/restore validation: Software.backup.tar.gz (21M) created and verified for safe round-trip testing

### Added (Phase 1 Foundation - Database-Driven File Organization - COMPLETE)
- **Phase 1.0-1.5**: Database Infrastructure
  - Database schema enhancements: `system` column (e.g., "Apple/AppleII") and `content_type` column for files table
  - System extraction logic: `_extract_system(source_path)` automatically populates system metadata during sync
  - 7 database query helpers in `app/db/queries.py` for system-based file discovery
  - 4 REST API endpoints (`/api/systems`, `/api/systems/{system}/query-mapping`, etc.) for database-driven queries
  
- **Phase 1.6**: Configuration Infrastructure
  - `download_layout` field (folder_based|flat) in SystemConfig for layout preference storage
  - All 25 systems in clients.yaml now configured with `download_layout: folder_based`
  - Configuration fully backward compatible with zero breaking changes
  
- **Phase 1.7**: Dual-Mode Directory Listing
  - `list_dynamic_map()` refactored with `db_mode` parameter for dual-mode operation:
    - YAML-driven mode (default): Folder-based scanning (existing behavior)
    - Database-driven mode (new): Database queries for file discovery
  - Graceful fallback to folder-based mode if database unavailable
  - 100% backward compatible - existing code works unchanged
  
- **Phase 1.8-1.9**: Testing & Validation
  - Comprehensive test suite created: `tests/test_phase1.py` (23 tests)
  - Test results: 12/12 passed, 11 skipped (require database/filesystem)
  - Verified: SystemConfig, configuration loading, dual-mode signature, integration
  
- **Documentation** (10+ pages):
  - [docs/PHASE_1_COMPLETE.md](docs/PHASE_1_COMPLETE.md) - Phase 1 completion summary
  - [docs/PHASE_1_7_COMPLETION.md](docs/PHASE_1_7_COMPLETION.md) - Dual-mode refactoring details
  - [docs/FLAT_LAYOUT_MIGRATION.md](docs/FLAT_LAYOUT_MIGRATION.md) - 4-phase migration plan
  - [docs/DATABASE_DRIVEN_MAPPINGS.md](docs/DATABASE_DRIVEN_MAPPINGS.md) - Technical assessment
  - Additional guides and reference documentation

### Changed
- `list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)` signature updated:
  - Added optional `db_mode: bool = False` parameter
  - Added optional `extensions: list = None` parameter
  - Enhanced docstring with 40-line comprehensive documentation
  
### Technical Details
- Database queries optimized for system + extension combinations
- System metadata extracted from source path: `/Native/{manufacturer}/{system}/...` → `{manufacturer}/{system}`
- All 25 systems configured for layout: Acorn, Apple, Atari, Coleco, Commodore, GCE, Mattel, Microsoft, MITS, NEC, Nintendo, Sega, Sinclair, SNK, Tandy
- Dual-mode supports gradual Phase 2 migration (systems can be flattened one-by-one)
- Complete backward compatibility maintained throughout

### Added
- `/sync/client/{client}/system/{system}` API endpoint for manual system cache population
- Comprehensive logging to track getattr cache hits, database lookups, and transform calculations
- Support for `display_name` field in clients.yaml for custom UI display names independent of filesystem paths
- Real filestore path tooltips in Virtual browse UI - shows actual filestore location when hovering over files
- `/api/source-paths` endpoint for resolving virtual paths to their real filestore locations using clients.yaml mapping rules
- UI configuration option `show_real_path_tooltips` (enabled by default) to toggle path tooltips in Config tab
- Transform plugin system with auto-discovery from `app/transform_plugins`
- Transform plugin documentation index and feature page
- Mapping and filtering documentation: `docs/MAPPING_AND_FILTERING.md`

### Changed
- **PERF**: Getattr cache validation now uses file's own mtime instead of parent directory mtime (prevents false invalidations)
- **PERF**: Readdir batch phase now checks getattr cache FIRST, before source path lookups and transform calculations
- **PERF**: Getattr priority reordered: cache → database → full resolution (prevents unnecessary database lookups)
- Cache warmer now calls `os.stat()` on files to pre-populate transform sizes, not just directory listings
- Disabled persistent PKL dir/getattr caches in favor of in-memory session cache + database to prevent stale listings
- Moved `two_mg` transform into plugin (`app/transform_plugins/two_mg_transform.py`)

### Fixed
- Catastrophic slowdown for systems with file transforms (38-45x speedup for Apple-II: 76s → 2s)
- Cache hits now properly reflected in batch phase instead of only in send phase
- Unbound variable error in readdir cache_hits initialization
- Apple-II DSK image loading - removed incorrect 64-byte header strip transform (only 2MG files need 512-byte strip)

## [2026-02-14] - Display Name System Implementation

### Added
- Optional `display_name` field in clients.yaml configuration
- Display name resolution system in pathutils.py for virtual path mapping
- Web API returns display_name for UI while filesystem operations use actual names
- Fall-back to `name` field when display_name not provided (backward compatible)

### Changed
- Config API endpoint (`/clients/{client}/systems`) now returns display_name for system list
- Virtual path resolution updated to handle both display_name and name lookups

### Technical Details
- `resolve_system_name()` function maps display names back to actual system names
- Display names work across all path resolution functions
- Separate concerns: `name` (filesystem/internal), `display_name` (UI), `canonical_system_name` (config), `local_base_path` (filestore)

## [2026-02-07] - Previous Release

### Features
- Core FUSE filesystem with caching strategies
- Multi-source support (HTTP/HTTPS, MEGA, Torrent, local archives)
- File transformation pipeline (strip_header, zip remapping, etc.)
- Web UI with file browser and download management
- SMB server integration
- Database-backed metadata storage for large collections

---

## Template for Future Entries

When adding new changes, use this format:

```markdown
## [YYYY-MM-DD] - Feature/Fix Description

### Added
- New features

### Changed
- Modifications to existing functionality

### Fixed
- Bug fixes

### Performance
- Performance improvements

### Technical
- Internal changes, refactoring, API changes
```

## Release Strategy

Releases are made from the `dev` branch to `main` when:
- A significant feature is complete and tested
- Multiple bug fixes are accumulated
- Performance improvements are validated
- At minimum: monthly snapshot

Each release should:
1. Update CHANGELOG.md with date and version
2. Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
3. Push tag: `git push origin vX.Y.Z`
4. Update version in relevant files (if applicable)
