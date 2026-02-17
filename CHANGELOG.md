# TransFS Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
