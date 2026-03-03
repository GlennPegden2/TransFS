# Changlog

## 2026-03-02
- Fixed `map_win_drive.ps1` mode 3 SMB mapping flow to set `ShareRoot` from the mapped drive (`<DriveLetter>:\`) before access checks.
- Changed mapped drive root writability check from hard error to warning so setup can continue to BIOS-target validation.
- Preserved strict validation at BIOS destination path to fail only when the actual target is unwritable.
- Corrected `app/transfs.py` `statfs()` to only set supported `pyfuse3.StatvfsData` fields (removed unsupported `f_flag` assignment).
- Added two foundation write tests in `tests/test_foundation.py` for write+cleanup in `RetroBat/bios` and `MiSTer/Archie` (with `Archimedes` fallback).
- Updated write test assertions to validate creation via TransFS path or resolved backend path and ensure cleanup in both locations.
- Hardened `setup_windows.ps1.template` (root + app copies) SMB mapping flow to remove stale mappings before connect and retry credentials with username variants (`root`, `server\root`, `.\root`) to mitigate Windows "Access is denied" auth collisions.
- Added drive-letter conflict handling in setup templates: when a selected letter is already SMB-mapped, users are informed and prompted to remove the existing mapping before continuing; choosing "No" keeps current behavior and asks for another letter.
