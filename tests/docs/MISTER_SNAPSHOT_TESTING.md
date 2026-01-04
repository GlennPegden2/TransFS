# MiSTer System Snapshot Testing

## Overview

Snapshot tests have been created for the Acorn systems (BBC Micro and Electron) to ensure their virtual filesystem structure remains stable across code changes.

## What's Captured

### BBC Micro (`test_bbc_micro_structure`)
- **boot.vhd** - 100MB boot disk (transparent ZIP access)
- **HDs/** folder - Contains MMB files displayed as VHD (extension aliasing)
  - `BEEB.vhd` (100MB)
- **FDs/** folder - Contains SSD disk images (flatten mode, ZIP transparent)
  - Samples first 10 files (Arkanoid, Chuckie Egg, etc.)

### Acorn Electron (`test_acorn_electron_structure`)
- **boot.vhd** - 100MB boot disk (transparent ZIP access)
- **HDs/** folder - Contains MMB files displayed as VHD (extension aliasing)
  - `BEEB.vhd` (100MB)
- **Tapes/** folder - Contains UEF tape files
  - `Intro_E.uef` (Welcome tape)
- **FDs/** folder - Contains ADF/DFS/HFE/SSD files (hierarchical mode)

## Running the Tests

### Inside Docker Container (Recommended on Windows)
```bash
# Run MiSTer snapshot tests
docker exec transfs pytest /tests/test_filesystem_snapshots.py::TestMiSTerSystems -v

# Update snapshots after intentional changes
docker exec transfs pytest /tests/test_filesystem_snapshots.py::TestMiSTerSystems -v --snapshot-update
```

### On Linux/Mac (Direct FUSE Access)
```bash
# Activate venv
source .venv/bin/activate

# Run tests
pytest tests/test_filesystem_snapshots.py::TestMiSTerSystems -v

# Update snapshots
pytest tests/test_filesystem_snapshots.py::TestMiSTerSystems -v --snapshot-update
```

## What Gets Tested

1. **Directory Structure** - Verifies correct folders appear (HDs, FDs, Tapes)
2. **File Presence** - Ensures expected files exist with correct names
3. **Extension Aliasing** - Confirms MMB files appear as VHD (MiSTer compatibility)
4. **File Metadata** - Checks sizes and extensions match expectations
5. **Transparent ZIP** - Validates files inside ZIPs are accessible

## When Snapshots Should Change

Update snapshots (`--snapshot-update`) when you:
- Add new pack downloads (new files appear in HDs/FDs/Tapes)
- Change extension mappings (e.g., add new file types)
- Modify folder structure (rename virtual folders)
- Fix bugs that change file visibility

## When Tests Should Fail

Tests will fail (and you should investigate) when:
- Files disappear unexpectedly (regression)
- Extensions change incorrectly (MMB->VHD aliasing breaks)
- Folders go missing (configuration errors)
- File sizes change dramatically (download corruption)

## Critical Test Coverage

These tests specifically verify the fixes made for:
1. **FUSE Flatten Mode Bug** - Characters no longer truncated from filenames
2. **Extension Aliasing** - MMB files correctly appear as VHD for MiSTer cores
3. **Transparent ZIP Access** - Files inside ZIPs are accessible without extraction
4. **Standard Layout Compliance** - Paths aligned correctly per standards

## Snapshot Location

Snapshots are stored in: `tests/__snapshots__/test_filesystem_snapshots.ambr`

This is a text file you can review to see exactly what structure is captured.
