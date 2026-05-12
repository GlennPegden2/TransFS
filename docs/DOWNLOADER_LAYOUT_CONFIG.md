# Phase 1.6: Downloader Configuration Integration Guide

**Status**: Planning  
**Date**: February 17, 2026  
**Scope**: Add `download_layout` configuration to support both folder-based and flat layouts

---

## Overview

When users download files, the downloader needs to know whether to:
- **Save to extension folders** (current): `/Software/dsk/`, `/Software/po/`, `/Software/2mg/`, etc.
- **Save directly** (future): `/Software/` (flat structure)

Phase 1.6 adds configuration support so the downloader can respect this choice.

---

## What Needs to Change

### 1. Configuration (`app/config/clients.yaml`)

Add `download_layout` field to each system:

```yaml
clients:
  MiSTer:
    systems:
      - name: Apple-II
        local_base_path: Apple/AppleII
        download_layout: folder_based  # NEW: folder_based or flat
        
        ...SoftwareArchives...:
          source_dir: Software
          filetypes: "FDs: DSK,DO,PO"
          ...

      - name: NES
        local_base_path: Nintendo/NES
        download_layout: folder_based  # Default for Phase 1
        ...SoftwareArchives...:
          source_dir: Software
          filetypes: "ROMs: NES"
          ...
```

**Values**:
- `folder_based` (default): Current behavior - organize by extension
- `flat` (future): All files in `/Software/`, no subfolders

---

### 2. Downloader Code (`app/api.py`)

Find all download functions and update path construction:

**Pattern to replace**:
```python
# OLD: Always use extension-based path
dest_folder = f"{base_dir}/Software/{extension}/"
```

**New pattern**:
```python
# NEW: Check download_layout setting
layout = system_config.get('download_layout', 'folder_based')

if layout == 'flat':
    dest_folder = f"{base_dir}/Software/"
else:
    # folder_based (default)
    dest_folder = f"{base_dir}/Software/{extension}/"
```

**Files to search in `app/api.py`**:
- Download from Internet Archive (search: `archive_item_download`)
- Download from remote sources (search: `download`)
- Download from Mega/torrents (search: `dest_dir`)

---

## Implementation Checklist

### Phase 1.6 (Foundation)

- [ ] **Add config field** to clients.yaml
  - [ ] MiSTer: All systems → `download_layout: folder_based`
  - [ ] Other clients: All systems → `download_layout: folder_based`
  - [ ] Document in CONFIGURATION_GUIDE.md

- [ ] **Update api.py download functions**
  - [ ] Find all download location decision points
  - [ ] Add layout mode checking
  - [ ] Default to `folder_based` for backward compatibility

- [ ] **Validation**
  - [ ] Config parsing: Valid values = {`folder_based`, `flat`}
  - [ ] Fallback: Missing field defaults to `folder_based`
  - [ ] Test: Downloads still work with new code

- [ ] **Testing**
  - [ ] Download a file with `folder_based` → should go to `/Software/dsk/` etc.
  - [ ] Try `flat` mode manually → verify path construction works
  - [ ] Verify no downloads break with default setting

### Phase 2+ (When Flattening Systems)

- [ ] Change system to: `download_layout: flat`
- [ ] Test: Downloads go to `/Software/` directly
- [ ] Verify files appear in virtual folder listings

---

## Code Search Reference

**In `app/api.py`**, search for these patterns to find places needing updates:

```bash
grep -n "Software.*extension\|dest_dir.*extension\|Software.*ext\|dsk\|po\|do" app/api.py
```

Common patterns:
```python
# Internet Archive
f"{download_dir}/{item_id}/..."

# Remote sources  
f"{base_path}/Software/{ext}/..."

# Mega/Torrents
os.path.join(dest, extension, ...)
```

---

## Example: Before & After

### Before (Current)
```python
# app/api.py - Internet Archive downloader
extension = file_extension(item_name)
dest_folder = os.path.join(
    config["filestore"],
    "Native",
    system["local_base_path"],
    "Software",
    extension  # Always creates extension folder!
)
```

### After (Phase 1.6)
```python
# app/api.py - Internet Archive downloader
extension = file_extension(item_name)

# Get layout preference
layout = system_config.get('download_layout', 'folder_based')

# Construct path based on layout
if layout == 'flat':
    software_dir = "Software"
else:
    software_dir = os.path.join("Software", extension)

dest_folder = os.path.join(
    config["filestore"],
    "Native",
    system["local_base_path"],
    software_dir
)
```

---

## Backward Compatibility

**All existing systems default to `folder_based`**:

```python
layout = system_config.get('download_layout', 'folder_based')
# ↑ If missing, defaults to current behavior
```

**Result**: 
- ✅ No config changes required for Phase 1
- ✅ Existing downloads work unchanged
- ✅ When Phase 2 flattens a system, just update YAML
- ✅ Downloader automatically uses new path

---

## Testing Commands (After Implementation)

```bash
# Test 1: Verify config parsing
docker exec transfs python3 -c "
from config import get_system_config
sys = get_system_config('MiSTer', 'Apple-II')
layout = sys.get('download_layout', 'folder_based')
print(f'Apple-II layout: {layout}')
assert layout in ['folder_based', 'flat']
print('✓ Config parsing OK')
"

# Test 2: Download file and verify destination
# (After implementing Phase 1.6 changes)
curl -X POST http://localhost:8000/api/download \
  -d '{"system": "Apple-II", "file": "test.zip"}'
# Verify files go to /Software/dsk/, not /Software/

# Test 3: Try flat mode (manual)
# Edit clients.yaml: Apple-II download_layout: flat
# Download same file
# Verify files go to /Software/ directly
```

---

## Configuration Example

Complete example with multiple systems:

```yaml
clients:
  MiSTer:
    systems:
      # Flat layout systems (Phase 2+)
      - name: Altair
        local_base_path: MITS/Altair
        download_layout: flat  # NEW: flat layout
        ...SoftwareArchives...:
          source_dir: Software
          db_mode: true
          ...

      # Folder-based layout systems (Phase 1)
      - name: Apple-II
        local_base_path: Apple/AppleII
        download_layout: folder_based  # NEW: folder-based (default)
        ...SoftwareArchives...:
          source_dir: Software
          filetypes: "FDs: DSK,DO,PO,2MG"
          ...

      - name: NES
        local_base_path: Nintendo/NES
        download_layout: folder_based  # NEW: folder-based (default)
        ...SoftwareArchives...:
          source_dir: Software
          filetypes: "ROMs: NES"
          ...

  # Can mix layouts across clients!
  Custom:
    systems:
      - name: CustomRoms
        local_base_path: Custom/Systems
        download_layout: flat  # This client uses flat
        ...
```

**Key insight**: Each system can independently choose its layout!

---

## Timeline

**Phase 1.6 (Now)**:
1. Add `download_layout` config field (default: `folder_based`)
2. Update downloader code to check layout
3. Verify backward compatibility (all defaults to folder-based)
4. **No functional changes** - everything works as before

**Phase 2 (Future)**:
1. Flatten first test system (e.g., MITS Altair)
2. Change its config to: `download_layout: flat`
3. Test downloads go to `/Software/` directly
4. Repeat for other systems

**Phase 3 (Future)**:
1. Gradually migrate more systems to flat
2. Mixed-mode coexistence works seamlessly

---

## Quick Validation Checklist

- [ ] Config adds `download_layout` field to all systems with value `folder_based`
- [ ] Code checks `system_config.get('download_layout', 'folder_based')`
- [ ] Default behavior unchanged (files still go to extension folders)
- [ ] `flat` mode path construction works (no syntax errors)
- [ ] No downloads broken by changes
- [ ] Code is backward compatible (old configs still work)

---

## Notes for Implementation

1. **Don't change behavior yet** - Phase 1.6 only adds config support
2. **All systems stay `folder_based`** - no functional changes
3. **Prepare infrastructure** - so Phase 2 is easy
4. **Document clearly** - so users know they can change it in Phase 2

This is about **preparation**, not **migration**. The migration happens in Phase 2.
