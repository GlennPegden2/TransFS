# TransFS Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `/sync/client/{client}/system/{system}` API endpoint for manual system cache population
- Comprehensive logging to track getattr cache hits, database lookups, and transform calculations
- Support for `display_name` field in clients.yaml for custom UI display names independent of filesystem paths
- Real filestore path tooltips in Virtual browse UI - shows actual filestore location when hovering over files
- `/api/source-paths` endpoint for resolving virtual paths to their real filestore locations using clients.yaml mapping rules
- UI configuration option `show_real_path_tooltips` (enabled by default) to toggle path tooltips in Config tab

### Changed
- **PERF**: Getattr cache validation now uses file's own mtime instead of parent directory mtime (prevents false invalidations)
- **PERF**: Readdir batch phase now checks getattr cache FIRST, before source path lookups and transform calculations
- **PERF**: Getattr priority reordered: cache → database → full resolution (prevents unnecessary database lookups)
- Cache warmer now calls `os.stat()` on files to pre-populate transform sizes, not just directory listings

### Fixed
- Catastrophic slowdown for systems with file transforms (38-45x speedup for Apple-II: 76s → 2s)
- Cache hits now properly reflected in batch phase instead of only in send phase
- Unbound variable error in readdir cache_hits initialization

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
