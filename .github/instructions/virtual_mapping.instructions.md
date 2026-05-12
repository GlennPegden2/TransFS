---
alwaysApply: true
trigger: always_on
applyTo: "app/{sourcepath,dirlisting,transfs}.py"
description: Virtual Directory Mapping Architecture
---

# SoftwareArchives Virtual Mapping Pattern

## Critical Design Pattern

`...SoftwareArchives...` creates **virtual directories based on file extensions**, NOT simple directory renames.

### Mapping Logic

**Configuration Pattern:**
```yaml
- ...SoftwareArchives...:
    source_dir: Software        # Base physical directory
    filetypes:
      - HDs: HDF               # Virtual "HDs" → Physical "Software/HDF/"
      - FDs: ADF               # Virtual "FDs" → Physical "Software/ADF/"
```

**Path Translation:**
- Physical: `Software/HDF/game.hdf`
- Virtual: `HDs/game.hdf`

### Implementation Rules (sourcepath.py)

1. **Empty Subpath Handling (Line ~187)**
   - When `subpath` is empty (e.g., accessing `/MiSTer/Archie/HDs` itself)
   - MUST check if physical directory exists: `source_dir/real_ext/`
   - MUST return the physical directory path if it exists
   - Example: `HDs` with no subpath → return `Software/HDF/` if exists

2. **Path Construction**
   ```python
   # For file: /MiSTer/Archie/HDs/game.hdf
   # Constructs: source_dir/real_ext/subpath
   # Result: Software/HDF/game.hdf
   ```

3. **Multiple Extensions**
   - Loop through all `real_exts` to find first matching directory/file
   - Return first match found

### Why This Exists

**Client Independence:** Different clients can view same physical files differently:
```yaml
# MiSTer
- HDs: HDF

# Another emulator  
- Disks: HDF

# Yet another
- HardDrives: HDF
```

All map to the same `Software/HDF/` directory but present different virtual names.

### Common Mistakes to Avoid

❌ **Wrong:** Treating as simple directory rename
❌ **Wrong:** Looking for physical directory named after virtual name (e.g., `HDs/`)
❌ **Wrong:** Returning None when subpath is empty

✅ **Correct:** Virtual name is just a label; physical path uses extension from mapping
✅ **Correct:** When subpath empty, return `source_dir/EXTENSION/` if exists
✅ **Correct:** Files must be in `source_dir/EXTENSION/` directories

### Debugging Checklist

When virtual directory doesn't appear:
1. Physical directory exists? `ls Native/.../Software/HDF/`
2. Mapping syntax correct? `VirtualName: EXTENSION` (uppercase)
3. Empty subpath returns directory? Check sourcepath.py line ~187
4. FUSE logs show path resolution? `docker logs transfs | grep readdir`

### Related Code

- `app/sourcepath.py` - Lines 160-300 (path resolution)
- `app/dirlisting.py` - Lines 50-100 (virtual directory listing)
- `app/transfs.py` - Calls get_source_path for FUSE operations
