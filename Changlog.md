# Changlog

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
