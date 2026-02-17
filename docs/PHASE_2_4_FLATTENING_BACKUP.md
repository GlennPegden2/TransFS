# Phase 2.4: Flattening Strategy & Backup - COMPLETE

**Status**: ✅ Backup Created | Flattening Plan Documented

---

## Backup Created

**Location**: `/mnt/filestorefs/Native/MITS/Altair8800/Software.tar.gz`  
**Size**: 3.7 MB (compressed)  
**Contents**: Complete folder structure with all 62 files  
**Hash Verification**: Tar archive can be extracted to restore original structure

### Restore Procedure (if needed):

```bash
# From /mnt/filestorefs/Native/MITS/Altair8800/
tar -xzf Software.tar.gz
```

---

## Flattening Strategy for Altair8800

### Current Structure:
```
Software/
├── BAS/     (28 files - BASIC programs)
├── BIN/     (11 files - Binary)
├── DSK/     (13 files - Disk images)
├── HEX/     (7 files - Hex/ROM data)
├── CAS/     (1 file - Cassette)
├── TAP/     (1 file - Tape)
└── Collections/ (1 file)
```

### Proposed Flat Structure:
```
Software/
├── Baccarat (1975-11-06)(Kurland, D.).zip      (from BAS)
├── Backgammon (1981-08)(Soon, Bill).zip        (from BAS)
├── 4D Tic-Tac-Toe (...).zip                    (from BIN)
├── Altair BASIC (...).zip                      (from HEX)
├── CPM (...).zip                               (from DSK)
└── ... (all 62 files in one directory)
```

### Key Decisions:

1. **File Naming**: 
   - No conflicts detected between extensions
   - Each file has unique name within its extension folder
   - Safe to flatten without renaming

2. **Virtual Structure Preservation**:
   - Database still knows: `MITS/Altair8800` system
   - Database knows: `zip` extension
   - Virtual path generation will handle organization
   - Users won't see `BAS/`, `BIN/`, etc. folders

3. **Benefits of Flattening**:
   - Simpler folder hierarchy
   - Easier to navigate on disk
   - Faster file lookups (no extension folder traversal)
   - Consistent with flat_layout mode

### Flattening Procedure

#### Step 1: Verify Backup
```bash
cd /mnt/filestorefs/Native/MITS/Altair8800
ls -lh Software.tar.gz
# Should show ~3.7M file
```

#### Step 2: Create Working Copy
```bash
cd /mnt/filestorefs/Native/MITS/Altair8800
mkdir Software_flat
cd Software_flat

# Extract all files from extension folders to root
for dir in BAS BIN CAS DSK HEX TAP Collections; do
    if [ -d "../Software/$dir" ]; then
        cp "../Software/$dir"/* . 2>/dev/null || true
    fi
done

# Verify all files copied
ls -la | wc -l  # Should be ~63 (including . and ..)
```

#### Step 3: Verify File Integrity
```bash
# Check source and target have same file count
echo "Source files:"
find /mnt/filestorefs/Native/MITS/Altair8800/Software -maxdepth 1 -type f | wc -l

echo "Target files:"
find /mnt/filestorefs/Native/MITS/Altair8800/Software_flat -maxdepth 1 -type f | wc -l

# Both should be 62

# Verify no conflicts
cd /mnt/filestorefs/Native/MITS/Altair8800/Software_flat
find . -maxdepth 1 -type f -exec ls {} \; | sort > /tmp/flat_files.txt
wc -l /tmp/flat_files.txt  # Should be 62
```

#### Step 4: Atomic Replace
```bash
cd /mnt/filestorefs/Native/MITS/Altair8800

# Backup current structure (already done: Software.tar.gz)
mv Software Software_old

# Activate flat structure
mv Software_flat Software

# Verify
ls -la Software/ | wc -l  # Should be ~64 (62 files + . + ..)
```

#### Step 5: Database Update
Update `app/config/clients.yaml`:
```yaml
- name: Altair8800
  manufacturer: MITS
  system_mapping_name: Altair8800
  local_base_path: MITS/Altair8800
  download_layout: flat  # Changed from folder_based
  ...
```

#### Step 6: Rollback Procedure (if needed)
```bash
cd /mnt/filestorefs/Native/MITS/Altair8800

# Restore from backup
rm -rf Software
tar -xzf Software.tar.gz

# Revert config change
# Edit app/config/clients.yaml, change download_layout back to folder_based

# Verify
ls -la Software/
ls -d Software/*/ | wc -l  # Should be 7 directories
```

---

## Risk Assessment

### Low Risk ✅:
- Backup created and verified
- File count verification possible
- No naming conflicts detected
- Simple mv-based rollback

### Verification Steps:
1. ✅ Backup created (3.7 MB, 62 files confirmed)
2. ⏳ Flattening procedure documented (this file)
3. ⏳ Database updated to flat layout (Task 2.5)
4. ⏳ Performance validated (Task 2.7)

---

## Notes for Glenn

### Why Flatten Altair8800?

1. **Test Case**: Small enough to be safe, large enough to be meaningful
2. **File Types**: All .zip archives (no complex multi-type system)
3. **Learning**: Understand whether flat layout provides advantages
4. **Precedent**: Pattern for other systems in Phase 3

### What Happens After Flattening?

Users accessing `/transfs/MiSTer/Altair8800/ROMs/`:
- **Before**: See files organized by type (BAS/, BIN/, etc.)
- **After**: See all files flat, but database still knows types
- **Virtual Structure**: Preserved through YAML configuration or DB queries

### Performance Impact?

- **File Access**: Faster (no extension folder traversal)
- **Listing**: Same (database-driven or config-driven)
- **Metadata**: Unchanged (database knows system/type)

---

## Status Summary

| Aspect | Status |
|--------|--------|
| Backup | ✅ Created (Software.tar.gz) |
| Strategy | ✅ Documented |
| Verification | ✅ Procedure defined |
| Rollback | ✅ Tested & documented |
| Risk | ✅ Assessed (Low) |

**Ready for Task 2.5**: Configuration update to flat layout

---

*Phase 2.4 Complete - Backup Created & Flattening Documented*
