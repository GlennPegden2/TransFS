# Investigation: Collections Folder Issue for Amstrad CPC

## Problem Statement

The Amstrad CPC configuration has a Collections folder at `Software/Collections/` containing two large ZIP files:
- `AmstradCPC-CDT_Collection.zip` (115MB)
- `Amstrad_CPC_TOSEC_2012_04_23.zip` (265MB)

These ZIPs should appear in a virtual "Collections" folder with hierarchical mode enabled, but they don't. The path resolution is looking at `Amstrad/CPC/Collections` instead of `Amstrad/CPC/Software/Collections`.

## Current Configuration

```yaml
- name: Amstrad
  cananonical_system_name: CPC
  local_base_path: Amstrad/CPC/
  maps:
    - boot.rom:
        default_source:
          source_filename: BIOS/boot.rom
    - cpc464nd.eZ0:
        default_source:
          source_filename: BIOS/cpc464nd.eZ0
    - ...SoftwareArchives...:
        supports_zip: true
        zip_mode: hierarchical
        source_dir: Software
        filetypes:
        - Disks: "DSK"
        - Tapes: "CDT"
        - Collections: "ZIP"  # Problem: expects files with .zip extension
```

## Root Cause Analysis

### How SoftwareArchives Filetype Mapping Works

1. **Extension-Based Folders**: Each filetype entry like `Tapes: "CDT"` creates a virtual folder that looks for files in `{source_dir}/{EXTENSION}/`
   - Example: `Tapes: "CDT"` → looks in `Software/CDT/` for files with `.cdt` extension
   - Works because: `Software/CDT/intro.cdt` exists ✓

2. **Collections Filetype Problem**: 
   - `Collections: "ZIP"` tries to look in `Software/ZIP/` for files with `.zip` extension
   - But the actual path is `Software/Collections/` (not `Software/ZIP/`)
   - The folder name "Collections" != the extension "ZIP"

3. **Path Resolution in `list_dynamic_map()`** (line 217-218):
   ```python
   for real_ext in real_exts:  # real_exts = ["ZIP"]
       dir_path = os.path.join(source_dir, real_ext, *subpath)
       # Results in: Software/ZIP/ instead of Software/Collections/
   ```

4. **Path Resolution in `get_dynamic_source_path()`** (line 193):
   ```python
   for real_ext in real_exts:
       dir_path = os.path.join(source_dir, real_ext)
       if os.path.isdir(dir_path):
           return dir_path
   # Looking for Software/ZIP/ which doesn't exist
   ```

5. **Why it Fails Existence Check** (transfs.py line 80-92):
   - `readdir()` calls `get_source_path()` for "Collections" entry
   - Returns None or non-existent path
   - Entry filtered out because `exists=False`

## Why This Design Exists

The standard layout pattern assumes:
```
Software/
├── {EXTENSION1}/     # e.g., MMB/
│   └── file1.mmb
├── {EXTENSION2}/     # e.g., SSD/
│   └── file2.ssd
```

Virtual folder names map to extension folders:
- `HDs: "MMB,VHD"` → looks in `Software/MMB/` and `Software/VHD/`
- Extension name == Folder name (by convention)

But Collections breaks this pattern:
- Virtual folder: `Collections`
- Extension: `ZIP`
- Physical folder: `Software/Collections/` (not `Software/ZIP/`)

## Viable Approaches

### Approach 1: Rename Physical Folder (Non-Starter)
**What**: Rename `Software/Collections/` → `Software/ZIP/`

**Pros**:
- No code changes needed
- Follows standard pattern

**Cons**:
- ❌ Requires manual intervention (not deployable)
- ❌ Breaks semantic meaning (ZIP is extension, not content type)
- ❌ Won't work for future cases where folder name != extension

### Approach 2: Use Folder Mapping Syntax
**What**: Allow direct folder mappings outside SoftwareArchives:
```yaml
maps:
  - Collections/:
      source_folder: Software/Collections
      supports_zip: true
      zip_mode: hierarchical
```

**Pros**:
- Clean separation of concerns
- Explicit path specification
- Could work for any folder passthrough

**Cons**:
- No existing implementation for `source_folder` syntax
- Needs code in `get_source_path()` to handle folder mappings
- Would bypass SoftwareArchives extension mapping logic

**Implementation Complexity**: Medium
- Add folder mapping support to `get_source_path()`
- Ensure folder mappings appear in `list_maps()`
- Handle ZIP processing for folder mappings

### Approach 3: Enhanced Filetype Syntax with Folder Override
**What**: Allow filetype to specify folder name separately from extension:
```yaml
filetypes:
  - Collections:
      extensions: "ZIP"
      folder: "Collections"  # Override: look in this folder
```

**Pros**:
- Stays within SoftwareArchives pattern
- Extension mapping still works
- Explicit folder specification

**Cons**:
- Changes filetype parsing in `parse_filetype_map()`
- Need to handle both old format (string) and new format (dict)
- More complex YAML structure

**Implementation Complexity**: Medium
- Modify `parse_filetype_map()` to handle dict values
- Update `list_dynamic_map()` to use folder override
- Update `get_dynamic_source_path()` to use folder override
- Maintain backward compatibility

### Approach 4: Folder Name Inference from Filetype Key
**What**: If the filetype key doesn't match any extension folder, use the key as folder name:
```yaml
filetypes:
  - Collections: "ZIP"  # If Software/Collections/ exists, use it
```

**Logic**:
```python
for real_ext in real_exts:
    dir_path = os.path.join(source_dir, real_ext)
    if not os.path.isdir(dir_path):
        # Fallback: try using the filetype key as folder name
        dir_path = os.path.join(source_dir, map_name)
        if os.path.isdir(dir_path):
            # Use this path for lookups
```

**Pros**:
- No config changes needed
- Backward compatible
- Minimal code changes
- Handles semantic folder names naturally

**Cons**:
- Implicit behavior (could be confusing)
- Might mask configuration errors
- Need to ensure extension matching still works inside folder

**Implementation Complexity**: Low-Medium
- Modify `list_dynamic_map()` directory resolution (line 217)
- Modify `get_dynamic_source_path()` directory resolution (line 193)
- Ensure ZIP listing works correctly in fallback path

### Approach 5: Multi-Level Folder Syntax
**What**: Allow nested folder specification in extension:
```yaml
filetypes:
  - Collections: "Collections/ZIP"  # Look in Collections/ for ZIP files
```

Parse as: `folder_path/extension_filter`

**Pros**:
- Explicit and clear
- Minimal config change
- Extension filtering still works

**Cons**:
- Changes parsing logic significantly
- Ambiguous if folder contains "/"
- Need to decide: is it `Collections/ZIP` or `ZIP` files in `Collections/`?

**Implementation Complexity**: Medium
- Modify `parse_filetype_map()` to split on last "/"
- Update path resolution in both listing functions
- Handle edge cases (no /, multiple /)

## Recommended Approach

**Approach 4: Folder Name Inference from Filetype Key**

### Rationale:
1. **No Config Changes**: Works with existing YAML structure
2. **Semantic Clarity**: Folder name "Collections" matches its purpose
3. **Backward Compatible**: Doesn't break existing configurations
4. **Minimal Code Impact**: Focused changes in 2-3 functions
5. **Future-Proof**: Handles other semantic folder names (Games, Demos, etc.)

### Implementation Plan:

1. **Modify `list_dynamic_map()`** (line 217-260):
   ```python
   for real_ext in real_exts:
       # Try standard extension folder first
       dir_path = os.path.join(source_dir, real_ext, *subpath[:-1] if subpath else [])
       
       # If extension folder doesn't exist, try map_name as folder
       if not os.path.isdir(dir_path) and not subpath:
           alt_dir_path = os.path.join(source_dir, map_name)
           if os.path.isdir(alt_dir_path):
               dir_path = alt_dir_path
       
       if not os.path.isdir(dir_path):
           continue
       
       # Rest of logic unchanged...
   ```

2. **Modify `get_dynamic_source_path()`** (line 190-199):
   ```python
   if not subpath:
       # Try extension folders first
       for real_ext in real_exts:
           dir_path = os.path.join(source_dir, real_ext)
           if os.path.isdir(dir_path):
               return dir_path
       
       # Fallback: try using map_name as folder name
       alt_dir_path = os.path.join(source_dir, map_name)
       if os.path.isdir(alt_dir_path):
           return alt_dir_path
       
       return None
   ```

3. **Handle Subpaths**: When inside Collections/, need to use alt path for file lookups:
   - Track which path was used (extension or map_name)
   - Use same path for subpath navigation

4. **Extension Filtering**: Inside Collections/, still filter by extension:
   - Files must match the extension list (ZIP in this case)
   - Hierarchical mode shows ZIPs as navigable folders

### Testing Requirements:
- Collections/ appears in virtual filesystem ✓
- ZIP files appear as navigable folders (hierarchical mode) ✓
- Files inside ZIPs are accessible ✓
- Standard extension folders still work (Tapes → CDT/) ✓
- Doesn't break BBC Micro, Electron configs ✓

### Edge Cases:
- What if both `Software/ZIP/` and `Software/Collections/` exist?
  - Priority: Extension folder first (standard pattern)
- What if Collections contains non-ZIP files?
  - Filtered out (only ZIP extension shown based on filetype config)
- What if map_name conflicts with a real folder at base level?
  - Won't happen: source_dir is "Software", so base-level folders excluded

## Alternative Quick Fix (Not Recommended)

Create a symlink: `Software/ZIP → Software/Collections`
- Pros: No code changes
- Cons: Platform-specific, not portable, hacky, requires manual setup
