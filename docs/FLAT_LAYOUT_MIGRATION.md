# Flat Layout Migration: Comprehensive Implementation Plan

**Status**: Planning Phase
**Created**: February 17, 2026
**Objective**: Replace per-extension folder structure with database-driven virtual organization

---

## PART 1: EXECUTIVE SUMMARY

### Current State (Folder-Based)
```
/Native/Apple/AppleII/Software/
├── dsk/        ← Physical folder enforces what's visible
├── do/
├── po/
├── 2mg/
├── nib/
├── bxy/
└── ...
```

### Target State (Database-Driven)
```
/Native/Apple/AppleII/Software/
├── file1.dsk    ← All files flat, organized by DB queries
├── file2.do
├── file3.po
├── file4.2mg
├── file5.nib
└── file6.bxy
```

### Key Benefits
1. **Simpler filesystem** - One folder instead of many
2. **Flexible organization** - Same file can appear in multiple virtual views
3. **Easier to manage** - No folder creation overhead
4. **Better at scale** - DB indexes faster than filesystem scanning
5. **Atomic operations** - Can reorganize views without moving files

---

## PART 2: IMPLEMENTATION PHASES

### PHASE 1: Foundation (1-2 weeks) ⭐ START HERE

**Objective**: Add database infrastructure, refactor code to support dual-mode (folder OR DB queries), configure downloader for both modes, validate with existing folder structure.

#### 1.1: Database Schema Changes

**File**: `app/db/schema.py`

```sql
ALTER TABLE files ADD COLUMN system TEXT;
ALTER TABLE files ADD COLUMN content_type TEXT;  -- 'disk_image', 'rom', 'core', 'tool'

CREATE INDEX idx_files_system ON files(system);
CREATE INDEX idx_files_system_ext ON files(system, extension);
CREATE INDEX idx_files_content_type ON files(content_type);
```

**Migration approach**: 
- Add columns as nullable (backward compatible)
- Populate during next sync
- Future: Can make NOT NULL once populated

#### 1.2: Sync Changes

**File**: `app/db/sync.py`

New method `_extract_system(rel_path)`:
```python
def _extract_system(rel_path: str) -> str:
    """
    Extract system from path like 'Native/Manufacturer/System/Software/...'.
    
    Examples:
      'Native/Apple/AppleII/Software/game.dsk' → 'Apple/AppleII'
      'Native/Nintendo/NES/Software/game.nes' → 'Nintendo/NES'
      'Native/Atari/AtariST/Software/game.st' → 'Atari/AtariST'
    """
    parts = rel_path.split('/')
    if len(parts) >= 4 and parts[0] == 'Native':
        return f"{parts[1]}/{parts[2]}"  # Manufacturer/System
    return None
```

Update `_add_file()` and `_update_file()` to populate `system` field.

#### 1.3: New Query Helper Module

**File**: `app/db/queries.py` (NEW)

```python
def query_files_by_system_and_extensions(
    system: str, 
    extensions: List[str], 
    limit: int = None
) -> List[dict]:
    """
    Query files for custom mapping.
    
    Args:
        system: 'Apple/AppleII', 'Nintendo/NES', etc.
        extensions: ['dsk', 'do', 'po', '2mg']
        limit: Max results to return
    
    Returns:
        List of file dicts: {file_id, filename, extension, virtual_path, ...}
    """
    # Implementation in Phase 1
    pass

def query_files_by_system_and_content_type(
    system: str,
    content_types: List[str],
    limit: int = None
) -> List[dict]:
    """Query by content type instead of extension."""
    pass

def query_all_systems() -> List[str]:
    """Get list of all systems in database."""
    pass
```

#### 1.4: Refactor list_dynamic_map()

**File**: `app/dirlisting.py`

**Key change**: Accept optional `db_mode` parameter that switches between:
- **db_mode=False** (default): Current behavior - scan folders
- **db_mode=True** (new): Query database instead

```python
def list_dynamic_map(
    config, path, root_parts, system, sa_entry, map_name,
    db_mode=None,  # NEW: None=auto-detect, True=force DB, False=force folders
    db_filters=None  # NEW: {'extensions': [...]} for DB queries
):
    """
    List files and directories for a dynamic ...SoftwareArchives... map.
    
    NEW: Can use database queries instead of folder scanning.
    
    Args:
        db_mode: 
            None (default): Use YAML filetypes, maintain current behavior
            True: Use DB query (requires db_filters)
            False: Force folder scanning
        db_filters: Dict with 'extensions' key for DB queries
    """
    
    # Get extensions (from YAML or DB query)
    if db_mode is True and db_filters:
        real_exts = db_filters.get('extensions', [])
        file_list = query_from_database(system, real_exts)  # NEW
        # Rest of listing logic uses file_list
    else:
        # Current behavior: scan folders
        filetype_map, reverse_map = get_filetype_maps(sa_entry)
        real_exts = filetype_map.get(map_name.upper(), [])
        # Current folder scanning logic
```

**Why dual-mode**: Allows gradual migration. Old systems keep working while new ones use DB.

#### 1.5: API Endpoint for Queries

**File**: `app/api.py`

```python
@app.route('/api/systems/<system>/query-mapping', methods=['POST'])
def query_custom_mapping(system):
    """
    Query files for custom mapping creation.
    
    POST body:
    {
        "extensions": ["nib", "bxy", "dsk"],
        "limit": 100
    }
    
    Returns:
    {
        "files": [
            {"name": "game.nib", "path": "...", "extension": "nib"},
            ...
        ],
        "count": N,
        "system": "Apple/AppleII"
    }
    """
    try:
        system = urllib.parse.unquote(system)
        data = request.json or {}
        extensions = data.get('extensions', [])
        limit = data.get('limit', 100)
        
        if not extensions or not system:
            return {'error': 'extensions and system required'}, 400
        
        files = query_files_by_system_and_extensions(system, extensions, limit)
        
        return {
            'files': files,
            'count': len(files),
            'system': system,
            'extensions': extensions
        }
    except Exception as e:
        logger.error(f"Query mapping error: {e}", exc_info=True)
        return {'error': str(e)}, 500

@app.route('/api/systems', methods=['GET'])
def list_all_systems():
    """List all systems in database."""
    try:
        systems = query_all_systems()
        return {'systems': systems, 'count': len(systems)}
    except Exception as e:
        return {'error': str(e)}, 500
```

#### 1.6: Downloader Configuration Support (NEW)

**Objective**: Ensure downloader respects layout mode (folder-based vs flat) for each system.

**File**: `app/config/clients.yaml`

Add download layout specification per system:

```yaml
clients:
  MiSTer:
    systems:
      - name: Apple-II
        local_base_path: Apple/AppleII
        download_layout: folder_based  # NEW: how to organize downloaded files
        # folder_based: /Software/dsk/, /Software/po/, etc. (current)
        # flat: /Software/ (future, Phase 2+)
        ...SoftwareArchives...:
          source_dir: Software
          filetypes: "FDs: DSK,DO,PO"
          ...
```

**Rationale**: 
- **Folder-based (default)**: Files downloaded to per-extension folders (/dsk/, /do/, /po/)
- **Flat (future)**: Files downloaded directly to /Software/
- Allows mixed-mode transition (some systems flat, others folder-based)

**Implementation in Phase 1** (minimal):
1. Add `download_layout` field to clients.yaml for all systems (default: `folder_based`)
2. Update API downloader code to respect this flag
3. Prepare for Phase 2 when some systems switch to `flat`

**Where to update in code**:
- `app/api.py` - Download functions (search for "download", "sources/")
- Add download path logic:
  ```python
  download_layout = system_config.get('download_layout', 'folder_based')
  
  if download_layout == 'flat':
      download_path = f"/mnt/filestorefs/Native/{system_path}/Software/"
  else:
      # Current behavior: folder_based
      download_path = f"/mnt/filestorefs/Native/{system_path}/Software/{extension}/"
  ```

**Testing**:
- Verify downloads still go to correct folder (backward compatible)
- Add config option validation
- Test that flat mode path would work (even if not used in Phase 1)

**Backward Compatibility**: ✅
- Default is `folder_based` (current behavior)
- All existing downloads unaffected
- New field is optional

---

### PHASE 2: Proof of Concept (1 week)

**Objective**: Successfully flatten ONE small system to validate the approach.

#### 2.1: Choose Target System

**Recommendation**: MITS Altair or Tandy CoCo (smaller, simpler)

**Criteria**:
- < 50 files
- Single or few file types
- Not critical if migration fails

#### 2.2: Flatten Process

For chosen system (e.g., MITS Altair):

**Before**:
```
/Native/MITS/Altair/Software/
├── bin/
│   ├── prog1.bin
│   └── prog2.bin
├── cas/
│   ├── tape1.cas
└── txt/
    └── readme.txt
```

**After**:
```
/Native/MITS/Altair/Software/
├── prog1.bin
├── prog2.bin
├── tape1.cas
└── readme.txt
```

#### 2.3: Database Query Config

Add to `clients.yaml`:
```yaml
systems:
  - name: Altair
    local_base_path: MITS/Altair
    ...SoftwareArchives...:
      source_dir: Software
      db_mode: true  # NEW: Use DB queries instead of folders
      virtual_folders:  # NEW: Define virtual views
        - name: Programs
          extensions: [bin]
        - name: Tapes
          extensions: [cas]
        - name: All
          extensions: [bin, cas, txt]
```

#### 2.4: Validation Tests

- [ ] Rescan filesystem (sync fills database with system='MITS/Altair')
- [ ] API query: `POST /api/systems/MITS%2FAltair/query-mapping` with `{"extensions": ["bin"]}`
- [ ] Verify results match filesystem files
- [ ] Mount via FUSE and browse `/Altair/Programs/` - should see all .bin files
- [ ] Performance: Query time < 100ms
- [ ] Verify caching works (subsequent queries faster)

---

### PHASE 3: Gradual Rollout (2-4 weeks)

**Objective**: Migrate remaining systems one by one.

#### 3.1: System Priority List

```
1. Altair (MITS)           - Proof of concept, done in Phase 2
2. CoCo (Tandy)            - Small, similar to Altair
3. Apple II (Apple)        - Medium, multiple file types, critical
4. TRS-80 (Tandy)          - Medium
5. Amstrad (Amstrad)       - Medium
6. Atari (Atari)           - Medium
7. Acorn (Acorn)           - Large, complex
8. All others              - Batch remaining systems
```

#### 3.2: Per-System Checklist

For each system:

- [ ] Flatten folder structure
- [ ] Rescan filesystem (populate DB with system field)
- [ ] Update clients.yaml with db_mode settings
- [ ] Test API query endpoint
- [ ] Mount via FUSE and verify directory listing
- [ ] Verify all files appear in expected virtual folders
- [ ] Performance check (query time, memory usage)
- [ ] Commit with message: `Migration: System -> database-driven layout`

#### 3.3: Backward Compatibility

During Phase 3:
- Code supports **both folder AND DB modes simultaneously**
- Old systems (folder-based) keep working
- New systems (DB-based) use queries
- No breaking changes

**Timeline**: Do one system per week. Systems can be on mixed modes.

---

### PHASE 4: Cleanup (Optional, 1-2 weeks)

**Objective**: Remove folder-based code path, simplify implementation.

#### 4.1: Cleanup Steps

Only after all systems migrated:

- [ ] Remove folder-scanning code from `list_dynamic_map()`
- [ ] Remove `db_mode` parameter (always use DB)
- [ ] Delete `get_filetype_maps()` and related folder functions
- [ ] Simplify caching (DB results are stable)
- [ ] Update documentation

#### 4.2: Result

```python
# Simple, clean code path:
def list_dynamic_map(config, path, root_parts, system, sa_entry, map_name):
    """List directory using database queries (no folder scanning)."""
    filters = sa_entry[map_name].get('db_filters')
    return query_and_build_listing(system, filters)
```

---

## PART 3: CODE STRUCTURE & FILE CHANGES

### Files to Create

1. **`app/db/queries.py`** (NEW)
   - Database query helper functions
   - System extraction, file queries
   - ~150 lines

### Files to Modify

1. **`app/db/schema.py`** (~20 lines)
   - Add system, content_type columns
   - Add indexes

2. **`app/db/sync.py`** (~40 lines)
   - Add `_extract_system()` method
   - Update `_add_file()` to populate system field

3. **`app/api.py`** (~100 lines)
   - Add `/api/systems/<system>/query-mapping` endpoint
   - Add `/api/systems` endpoint
   - Update download logic to respect `download_layout` setting
   - Add download path routing: folder_based vs flat

4. **`app/dirlisting.py`** (~80 lines)
   - Add optional `db_mode`, `db_filters` parameters
   - Add database query branch
   - Maintain backward compatibility

5. **`app/config/clients.yaml`** (Phase 1)
   - Add `download_layout: folder_based` to all systems (default, backward compat)
   - Document `download_layout: flat` option for Phase 2

---

## PART 4: TESTING STRATEGY

### Unit Tests (Phase 1)

**File**: `tests/test_database_driven.py`

```python
def test_extract_system_from_path():
    assert extract_system('Native/Apple/AppleII/Software/game.dsk') == 'Apple/AppleII'
    assert extract_system('Native/Nintendo/NES/Software/game.nes') == 'Nintendo/NES'

def test_query_files_by_system_and_extension():
    files = query_files_by_system_and_extensions('Apple/AppleII', ['dsk', 'po'])
    assert len(files) > 0
    assert all(f['extension'] in ['dsk', 'po'] for f in files)

def test_api_query_mapping():
    response = client.post(
        '/api/systems/Apple%2FAppleII/query-mapping',
        json={'extensions': ['dsk']}
    )
    assert response.status_code == 200
    assert 'files' in response.json
```

### Integration Tests (Phase 1)

- Rescan filesystem, verify system field populated
- Query API, verify results match database
- Mount filesystem, browse virtual folders
- Verify extension mapping still works

### Manual Tests (Phase 2)

For each system:
- Browse flat `/Software/` folder via FUSE
- Verify files appear under correct virtual views
- Test performance (should be fast)
- Verify caching works

---

## PART 5: ROLLBACK STRATEGY

### If something breaks:

**Level 1: Code Rollback (Simple)**
```bash
git revert <commit>
# Old code path still works, just ignore new DB fields
```

**Level 2: Data Rollback (Folder Restoration)**
```bash
# If filesystem was flattened but code reverted
# Restore from backup OR manually recreate folders
for file in /Software/*; do
    ext=${file##*.}
    mkdir -p /Software/$ext
    mv "$file" /Software/$ext/
done
```

**Level 3: Database Rollback**
```sql
-- If needed, drop new columns (migration is reversible)
ALTER TABLE files DROP COLUMN system;
ALTER TABLE files DROP COLUMN content_type;
```

### Safe Approach

- **Phase 1**: No risk, just adds columns. Backward compatible.
- **Phase 2**: Test on small system. If fails, restore from backup.
- **Phase 3**: Do one system at a time. Easy to roll back individual systems.
- **Phase 4**: Only do after all systems verified in Phase 3.

---

## PART 6: SUCCESS CRITERIA

### Phase 1 Complete When:
- [ ] Schema updated (system, content_type columns exist)
- [ ] Sync extracts system field
- [ ] Query helper functions work
- [ ] API endpoints respond correctly
- [ ] list_dynamic_map() accepts db_mode parameter
- [ ] Dual-mode works (folder mode still functions)
- [ ] Unit tests pass

### Phase 2 Complete When:
- [ ] One system (e.g., Altair) successfully flattened
- [ ] DB queries return correct files
- [ ] FUSE mount shows correct virtual views
- [ ] Performance acceptable (< 100ms per query)
- [ ] Caching works
- [ ] All integration tests pass

### Phase 3 Complete When:
- [ ] All systems migrated to database-driven layout
- [ ] Each system tested individually
- [ ] No breaking changes to API
- [ ] Performance acceptable across all systems

### Phase 4 Complete When:
- [ ] Folder-based code removed
- [ ] Codebase simplified
- [ ] All tests still pass
- [ ] Documentation updated

---

## PART 7: TIME & RESOURCE ESTIMATES

| Phase | Duration | Effort | Risk | Owner |
|-------|----------|--------|------|-------|
| 1: Foundation | 1-2 weeks | 30-40 hrs | LOW | Dev |
| 2: PoC | 1 week | 15-20 hrs | LOW | Dev |
| 3: Rollout | 2-4 weeks | 40-60 hrs | LOW-MED | Dev |
| 4: Cleanup | 1-2 weeks | 15-20 hrs | LOW | Dev (optional) |
| **Total** | **5-9 weeks** | **100-140 hrs** | **LOW** | |

---

## PART 8: DECISION TREE (For Context Overflow)

If context runs out during implementation, use this to know where you are:

```
START
 ├─ Phase 1 Foundation?
 │  ├─ Schema updated?           → Go to 1.2 (sync changes)
 │  ├─ Sync extracts system?     → Go to 1.3 (queries.py)
 │  ├─ queries.py created?       → Go to 1.4 (refactor list_dynamic_map)
 │  ├─ list_dynamic_map refactored? → Go to 1.5 (API endpoints)
 │  └─ API endpoints done?       → PHASE 1 COMPLETE, commit
 │
 ├─ Phase 2 Proof of Concept?
 │  ├─ System chosen?            → Go to 2.2 (flatten process)
 │  ├─ Folders flattened?        → Go to 2.3 (DB config)
 │  ├─ clients.yaml updated?     → Go to 2.4 (validation tests)
 │  └─ Tests pass?               → PHASE 2 COMPLETE, commit
 │
 ├─ Phase 3 Gradual Rollout?
 │  └─ For each system:
 │     ├─ Flatten folders
 │     ├─ Update clients.yaml
 │     ├─ Test API query
 │     └─ Commit per-system
 │
 └─ Phase 4 Cleanup?
    └─ Remove folder-based code (only if all systems migrated)
```

---

## PART 9: QUICK REFERENCE

### Key Files & Line Numbers (for future sessions)

**app/db/schema.py**:
- `CREATE_TABLES`: Add system, content_type columns + indexes

**app/db/sync.py**:
- `_extract_system()`: NEW METHOD
- `_add_file()`: Update INSERT to include system field

**app/db/queries.py**:
- `query_files_by_system_and_extensions()`: NEW
- `query_all_systems()`: NEW

**app/dirlisting.py**:
- `list_dynamic_map()`: Add db_mode, db_filters parameters (~line 410)

**app/api.py**:
- `/api/systems/<system>/query-mapping`: NEW ENDPOINT
- `/api/systems`: NEW ENDPOINT (list all systems)

**app/config/clients.yaml**:
- Add `db_mode: true` per system (Phase 2+)
- Add `virtual_folders` definitions (Phase 2+)

---

## NEXT STEP

Start with **PHASE 1: Foundation** (Sections 1.1-1.5 in Part 2).

This is LOW RISK and BACKWARD COMPATIBLE. Once Phase 1 is done, you can decide whether to continue with Phase 2-4 or keep the folder structure and use DB as an **optional feature**.

**Ready to implement Phase 1?**
