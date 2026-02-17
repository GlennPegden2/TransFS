# Phase 2: Proof of Concept Flat Layout Migration - PILOT PLAN

**Status**: 🎯 Starting Now  
**Date**: Today  
**Target System**: MITS Altair8800 (Recommended - Smallest & Simplest)  
**Timeline**: 1 Week  
**Goal**: Prove flat layout migration works end-to-end  

---

## Phase 2 Overview

Phase 2 validates the architecture built in Phase 1 by:

1. **Selecting a test system** (MITS Altair8800)
2. **Flattening its folder structure** (optional initially)
3. **Updating configuration** (`download_layout: flat`)
4. **Testing database queries** (verify queries work)
5. **Documenting the process** (for Phase 3 rollout)

This is a **proof of concept** - we're validating that the infrastructure works, not necessarily making permanent changes yet.

---

## Why MITS Altair8800?

**Perfect test candidate**:
- ✅ Smallest system (fewest files = faster to test)
- ✅ Simple structure (limited file types)
- ✅ Low risk (minimal impact if something goes wrong)
- ✅ Well-documented (clear requirements)

**Configuration**:
```yaml
Manufacturer: MITS
System: Altair8800
Local Path: MITS/Altair8800
Files: /Native/MITS/Altair8800/Software/{ROM,BIN}/*
Extensions: ROM, BIN, HEX (mapped to ROM)
```

---

## Phase 2 Tasks (Detailed)

### Task 2.1: Assess Current Structure (30 min)
**Objective**: Understand what we're working with

```bash
# Count files by extension in Altair8800
ls -la /mnt/filestorefs/Native/MITS/Altair8800/Software/

# Check if files are organized in extension folders
find /mnt/filestorefs/Native/MITS/Altair8800/Software -type f | wc -l

# Sample a few file names and extensions
find /mnt/filestorefs/Native/MITS/Altair8800/Software -type f | head -20
```

**Expected Result**:
- Current structure: `/Software/ROM/file1.rom`, `/Software/BIN/file2.bin`, etc.
- Total files: Likely < 500 (small system)
- Sample output: Mix of ROM, BIN, HEX files

**Deliverable**: Screenshot/log of current structure

---

### Task 2.2: Query Database (30 min)
**Objective**: Verify database has metadata for Altair8800

```python
# Test database queries in Python
import sys
sys.path.insert(0, 'app')

from db.queries import (
    query_files_by_system_and_extensions,
    query_all_systems,
    query_extensions_by_system,
    query_system_statistics
)

# 1. List all systems (should include MITS/Altair8800)
systems = query_all_systems()
print(f"Total systems: {len(systems)}")
print("Altair8800 in list:", "MITS/Altair8800" in systems)

# 2. Get extensions for this system
exts = query_extensions_by_system("MITS/Altair8800")
print(f"Extensions: {exts}")

# 3. Query files (use exts from above)
if exts:
    files = query_files_by_system_and_extensions("MITS/Altair8800", exts, limit=10)
    print(f"Sample files: {len(files)} total")
    for f in files[:5]:
        print(f"  - {f.get('filename')}")

# 4. Get statistics
stats = query_system_statistics("MITS/Altair8800")
print(f"Statistics: {stats}")
```

**Expected Result**:
- ✅ MITS/Altair8800 found in systems list
- ✅ ROM, BIN, HEX extensions identified
- ✅ Files returned from query (e.g., 200-500 files)
- ✅ Statistics show file count and size breakdown

**Deliverable**: Output showing database has complete metadata

---

### Task 2.3: Test list_dynamic_map() Dual-Mode (30 min)
**Objective**: Verify both modes work

```python
from pathlib import Path
from dirlisting import list_dynamic_map
from pathutils import get_system_info, find_software_archive_entry
from config import get_system_config

# Setup
config = {
    "filestore": "/mnt/filestorefs",
    # ... rest of config
}
system_config = get_system_config("MiSTer", "Altair8800", "app/config")
root_parts = ("transfs",)  # Standard mount point
system = {"name": "Altair8800", "local_base_path": "MITS/Altair8800"}
sa_entry = find_software_archive_entry(system)
map_name = "ROMs"  # Or "Disks" depending on config

# Test 1: YAML-driven mode (current default)
path = Path("/transfs/MiSTer/Altair8800/ROMs")
entries_yaml = list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)
print(f"YAML mode: {len(entries_yaml)} entries")

# Test 2: Database mode
extensions = ["ROM", "BIN"]  # From query
entries_db = list_dynamic_map(
    config, path, root_parts, system, sa_entry, map_name,
    db_mode=True,
    extensions=extensions
)
print(f"DB mode: {len(entries_db)} entries")

# Compare results
print(f"Results match: {set(entries_yaml) == set(entries_db)}")
```

**Expected Result**:
- ✅ YAML mode works (returns files)
- ✅ DB mode works (returns files)
- ✅ Both modes return same files

**Deliverable**: Output comparing both modes

---

### Task 2.4: Plan Flattening (30 min)
**Objective**: Design the actual folder flattening

**Current Structure**:
```
/Native/MITS/Altair8800/Software/
├── ROM/
│   ├── file1.rom
│   ├── file2.rom
│   └── ...
├── BIN/
│   ├── prog1.bin
│   └── ...
└── HEX/ (if exists)
    └── data.hex
```

**Proposed Flat Structure**:
```
/Native/MITS/Altair8800/Software/
├── file1.rom
├── file2.rom
├── prog1.bin
└── data.hex
```

**Flattening Plan**:
```bash
# Backup current structure
cp -r /mnt/filestorefs/Native/MITS/Altair8800/Software \
      /mnt/filestorefs/Native/MITS/Altair8800/Software.backup

# Move files to root
mv /mnt/filestorefs/Native/MITS/Altair8800/Software/ROM/* \
   /mnt/filestorefs/Native/MITS/Altair8800/Software/

mv /mnt/filestorefs/Native/MITS/Altair8800/Software/BIN/* \
   /mnt/filestorefs/Native/MITS/Altair8800/Software/

# Remove empty directories
rmdir /mnt/filestorefs/Native/MITS/Altair8800/Software/ROM
rmdir /mnt/filestorefs/Native/MITS/Altair8800/Software/BIN

# Verify
ls /mnt/filestorefs/Native/MITS/Altair8800/Software | wc -l
```

**Considerations**:
- ⚠️ File naming conflicts? (unlikely with extension mapping)
- ⚠️ Need backup before proceeding
- ⚠️ Update database if we change structure

**Deliverable**: Approved flattening plan

---

### Task 2.5: Update Configuration (15 min)
**Objective**: Enable flat layout mode

**File**: `app/config/clients.yaml`

**Change**:
```yaml
# Before
- name: Altair8800
  manufacturer: MITS
  system_mapping_name: Altair8800
  local_base_path: MITS/Altair8800
  download_layout: folder_based  # ← Currently this

# After
- name: Altair8800
  manufacturer: MITS
  system_mapping_name: Altair8800
  local_base_path: MITS/Altair8800
  download_layout: flat  # ← Change to this
```

**Verification**:
```python
from config import get_system_config

config = get_system_config("MiSTer", "Altair8800", "app/config")
print(f"Layout: {config.download_layout}")  # Should be "flat"
```

**Deliverable**: Configuration updated and verified

---

### Task 2.6: Test Virtual View (30 min)
**Objective**: Verify virtual folder structure appears correct to users

**Testing**:
```bash
# Mount TransFS and check virtual path
cd /transfs

# List system ROMs
ls -la /transfs/MiSTer/Altair8800/ROMs/

# Verify expected files are present
find /transfs/MiSTer/Altair8800 -type f | wc -l
find /mnt/filestorefs/Native/MITS/Altair8800/Software -type f | wc -l
# Should be same count

# Spot-check specific files
ls /transfs/MiSTer/Altair8800/ROMs/altairbasic*
```

**Expected Result**:
- ✅ Virtual path shows all files
- ✅ File count matches
- ✅ Files accessible and readable

**Deliverable**: Screenshot of virtual view

---

### Task 2.7: Performance Validation (45 min)
**Objective**: Ensure flat layout doesn't degrade performance

**Baseline** (from Phase 1):
- YAML mode: ~0.2-0.5s per listing
- DB mode (small system): ~0.3-0.6s per listing

**Tests**:
```python
import time
from dirlisting import list_dynamic_map

# Test 1: Multiple calls (caching test)
path = Path("/transfs/MiSTer/Altair8800/ROMs")

times = []
for i in range(5):
    start = time.time()
    entries = list_dynamic_map(config, path, root_parts, system, sa_entry, map_name, db_mode=True)
    times.append(time.time() - start)

print(f"Times: {times}")
print(f"Average: {sum(times)/len(times):.3f}s")
print(f"Cache hit (2nd call): {times[1] < times[0]}")
```

**Expected Result**:
- ✅ First call: 0.3-0.6s (database query)
- ✅ Subsequent calls: < 0.1s (cache hit)
- ✅ No performance degradation

**Deliverable**: Performance metrics comparison

---

### Task 2.8: Document Migration Process (1 hour)
**Objective**: Create guide for Phase 3 rollout

**Create**: `docs/PHASE_2_ALTAIR_MIGRATION.md`

**Contents**:
- [ ] Pre-migration checklist
- [ ] Step-by-step flattening procedure
- [ ] Configuration update process
- [ ] Testing procedures
- [ ] Rollback instructions (if needed)
- [ ] Performance metrics
- [ ] Lessons learned

**Deliverable**: Complete migration guide

---

## Phase 2 Success Criteria

✅ **All must be true**:
1. Database queries return results for Altair8800
2. Both YAML-driven and DB-driven modes work
3. Virtual folder view shows correct files
4. Performance is acceptable (< 1s for listing)
5. Configuration successfully updated to `flat`
6. Migration process documented

🎯 **Stretch Goal**:
- Migrate 2-3 small systems during pilot
- Validate gradual rollout approach

---

## Timeline

**Today**: Start Phase 2 kick-off
- Task 2.1: 30 min
- Task 2.2: 30 min  
- Task 2.3: 30 min
- Task 2.4: 30 min
- **Subtotal: 2 hours**

**Tomorrow**: Implementation phase
- Task 2.5: 15 min
- Task 2.6: 30 min
- Task 2.7: 45 min
- Task 2.8: 1 hour
- **Subtotal: 2.5 hours**

**Next week**: Validation & documentation
- User testing (30 min)
- Final validation (30 min)
- Phase 2 completion (15 min)
- **Subtotal: 1.25 hours**

**Total Phase 2 Time**: ~6 hours spread over 1 week

---

## Risk Mitigation

⚠️ **Potential Issues & Solutions**:

| Risk | Probability | Mitigation |
|------|-------------|-----------|
| File naming conflicts | Low | Backup first; test sample |
| Database stale | Medium | Run sync before testing |
| Virtual view corruption | Low | Revert to backup if needed |
| Performance degradation | Low | Measure with metrics |
| Configuration errors | Low | Validate immediately |

**Rollback Plan**:
```bash
# If anything breaks, restore from backup
rm -rf /mnt/filestorefs/Native/MITS/Altair8800/Software
cp -r /mnt/filestorefs/Native/MITS/Altair8800/Software.backup \
      /mnt/filestorefs/Native/MITS/Altair8800/Software

# Revert config
# Update download_layout back to "folder_based"
```

---

## What Happens Next (Phase 3)

Once Phase 2 is successful:
1. Choose next system for migration
2. Repeat process (should be faster second time)
3. Continue until all 25 systems migrated
4. Phase 4: Cleanup (remove old code paths)

**Estimated total migration**: 2-4 weeks for all 25 systems

---

## Questions to Answer During Phase 2

1. **Does database query performance scale?** (test with larger systems)
2. **Are there file naming edge cases?** (duplicates, special chars)
3. **How noticeable is virtual folder view change?** (user perspective)
4. **Can we automate flattening?** (script for Phase 3)
5. **Any database sync issues?** (with flat structure)

---

**Phase 2 Objective**: Validate the architecture works end-to-end  
**Phase 2 Success**: Altair8800 migrated successfully, document for rollout  
**Phase 2 Deliverable**: Migration guide + validation report

Ready to begin? 🚀
