# Changlog

## 2026-03-04
- Removed hardcoded "Native" virtual client folder from `/mnt/transfs` root since we now use separate SMB shares for Native and Virtual filesystems.
- Improved RetroBat/Acorn Atom performance by hardening cache behavior in `readdir` and query-map resolution paths.
- Added cached config-entry parsing and DB-entry reuse for database-mode `readdir` in `app/transfs.py` to reduce repeated expensive adapter and parse calls.
- Replaced repeated recursive filename scans with indexed recursive lookup caches in `app/sourcepath.py` and `app/dirlisting.py` for flattened query fallback and ZIP discovery paths.
- Increased subdirectory query cache TTL in `app/dirlisting.py` to reduce repeated startup/browse DB load.
- Optimized subdirectory SQL in `app/dirlisting.py` to compute prefix substring once via CTE.
- Added PostgreSQL prefix-like index `idx_files_virtual_path_like` (`text_pattern_ops`) in `app/db/schema.py` for `virtual_path LIKE 'prefix%'` lookup acceleration.
- **Added startup hot-path pre-warming in `app/startup_prewarm.py`** to load critical paths before FUSE mount completes, reducing cold-start delays from 550-760ms to **sub-millisecond** (0.6-1.0ms) on frequently-accessed paths like RetroBat/bios and AcornAtom maps.
- Added `startup_prewarm` configuration section in `app/config/app.yaml` to configure hot paths and subdirectory prewarm behavior.
- Integrated prewarm into `app/transfs.py` main_async() to execute before pyfuse3.init() for maximum effectiveness.
- **Enhanced recursive filename index in `app/sourcepath.py`** with comprehensive logging (cache hits/misses, scan time, file counts) and increased TTL from 30s to 900s (15 minutes) to avoid repeated expensive scans of large directories.
- **Added recursive index pre-warming to `app/startup_prewarm.py`** to pre-build filename indexes for large source directories (e.g., 5,400+ file directories) at startup, eliminating 8+ second cold-start delays on first file access.
- **Fixed joeblade.dsk lookup performance issue** where first access caused 8.8-second silent delay due to recursive scan of 5,406 files in Software/Sources directory - now resolved with startup pre-warming and longer cache TTL.
- Added `prewarm_recursive_indexes` and `recursive_index_paths` configuration options in `app/config/app.yaml` to control which directories get pre-indexed at startup.
- Removed redundant SharedBIOS system from `app/config/clients/default/retrobat.yaml`, consolidating BIOS file mappings into client-level maps for cleaner configuration.

## 2026-03-03
- Introduced `Native/Clients` and `Native/Systems` architecture for direct SMB bypass paths.
- Added dedicated SMB share split (`TransFS` virtual + `TransFSNative` native) and removed the container bind-mount of `Native` into `/mnt/transfs`.
- Updated setup profile and Windows setup templates to map/store/validate two drives (virtual + native) with separate share names and drive letters.
- Corrected virtual Windows mapping target to `\\<host>\TransFS\RetroBat` and fixed BIOS config path handling to avoid double `RetroBat` segments.
- Updated Setup Clients UI to show native share name and native PowerShell mapping command.
- Added config-time normalization in `app/config.py` so system `local_base_path` and source `base_path` resolve to `Systems/...` without requiring immediate YAML rewrites.
- Updated RetroBat setup PowerShell template (`setup_windows.ps1.template` and `app/setup_windows.ps1.template`) to copy BIOS files to `V:\Clients\RetroBat\bios` (matching retrobat.yaml client-level local_base_path for proper virtual mount visibility).
- Fixed Mode 3 (dual-drive) config prompt to reference full client path (`V:\Clients\RetroBat\bios`) instead of bare `V:\bios`, ensuring BIOS files copied to native share appear in FUSE virtual mount.
- Added optional ROM paths migration in setup script: after BIOS copy, prompts user to update all `<path>` entries in `es_systems.cfg` from relative (`../roms`) to network share paths (`V:\roms`), with XML parsing and backup support.
- Fixed category-level zip map handling for RetroBat shared BIOS so mapped files like `atom.zip` respect `zip_mode: file` and appear as files (not virtual folders) in `/RetroBat/bios`.
- Fixed RetroBat category-path query map file opens (e.g., `ROMS/AcornAtom/Tapes/*.uef`) by resolving map location relative to the detected system segment and applying recursive lookup fallback for flattened query listings.
- Updated build script fallback `BASE_PATH` defaults to `Native/Systems/...` for consistency with the new filesystem layout.
- Added one-time migration script `legacy/migrate_native_layout.sh` to move legacy top-level Native manufacturer folders under `Native/Systems` and create `Native/Clients`.
- Updated Native bypass documentation and README examples to reflect the `Clients`/`Systems` split.

## 2026-03-02
- Fixed `map_win_drive.ps1` mode 3 SMB mapping flow to set `ShareRoot` from the mapped drive (`<DriveLetter>:\`) before access checks.
- Changed mapped drive root writability check from hard error to warning so setup can continue to BIOS-target validation.
- Preserved strict validation at BIOS destination path to fail only when the actual target is unwritable.
- Corrected `app/transfs.py` `statfs()` to only set supported `pyfuse3.StatvfsData` fields (removed unsupported `f_flag` assignment).
- Added two foundation write tests in `tests/test_foundation.py` for write+cleanup in `RetroBat/bios` and `MiSTer/Archie` (with `Archimedes` fallback).
- Updated write test assertions to validate creation via TransFS path or resolved backend path and ensure cleanup in both locations.
- Hardened `setup_windows.ps1.template` (root + app copies) SMB mapping flow to remove stale mappings before connect and retry credentials with username variants (`root`, `server\root`, `.\root`) to mitigate Windows "Access is denied" auth collisions.
- Added drive-letter conflict handling in setup templates: when a selected letter is already SMB-mapped, users are informed and prompted to remove the existing mapping before continuing; choosing "No" keeps current behavior and asks for another letter.
