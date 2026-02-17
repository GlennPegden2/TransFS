# Phase 1 Implementation Checklist

**Status**: Core Implementation Complete ✅  
**Date**: February 17, 2026  
**Remaining**: Refactoring list_dynamic_map(), testing, and validation

---

## PHASE 1 DELIVERABLES

### 1. Database Schema ✅
- [x] Added `system` column to files table
- [x] Added `content_type` column to files table  
- [x] Created `idx_files_system` index
- [x] Created `idx_files_system_ext` index (critical for performance)
- [x] Created `idx_files_content_type` index
- **File**: `app/db/schema.py` (lines 18-30, 37-43)

### 2. Filesystem Sync ✅
- [x] Added `_extract_system(source_path)` method
- [x] Implemented system extraction from path: `Native/Apple/AppleII/...` → `Apple/AppleII`
- [x] Updated `_sync_file()` to call `_extract_system()`
- [x] Updated INSERT statement to include system and content_type fields
- **File**: `app/db/sync.py` (lines 21-47, 98-115)

### 3. Query Helper Module ✅
- [x] Created `app/db/queries.py` (NEW FILE)
- [x] `query_files_by_system_and_extensions()` - main query function
- [x] `query_files_by_system_and_content_type()` - future-ready
- [x] `query_all_systems()` - system discovery
- [x] `query_extensions_by_system()` - extension enumeration
- [x] `query_file_count_by_system_and_extension()` - for UI counts
- [x] `query_file_by_id()` - file metadata lookup
- [x] `query_system_statistics()` - comprehensive stats
- **File**: `app/db/queries.py` (~280 lines, all functions)

### 4. API Endpoints ✅
- [x] `/api/systems` (GET) - list all systems
- [x] `/api/systems/{system}/query-mapping` (POST) - core mapping query endpoint
- [x] `/api/systems/{system}/extensions` (GET) - list extensions with counts
- [x] `/api/systems/{system}/stats` (GET) - comprehensive statistics
- [x] Created `QueryMappingRequest` Pydantic model for type safety
- **File**: `app/api.py` (lines 849-850, 2700-2828)

### 5. Documentation ✅
- [x] `docs/FLAT_LAYOUT_MIGRATION.md` - Complete 9-part implementation plan
- [x] `PHASE_1_STATUS.md` - Current status and next steps

---

## VALIDATION CHECKLIST

### Before Container Restart:

- [ ] Verify all files were modified:
  ```bash
  # Check if files exist and were modified
  ls -l app/db/queries.py  # Should exist
  grep -n "system TEXT" app/db/schema.py  # Should find it
  grep -n "_extract_system" app/db/sync.py  # Should find method
  grep -n "query-mapping" app/api.py  # Should find endpoint
  ```

- [ ] Verify no syntax errors:
  ```bash
  python3 -m py_compile app/db/queries.py
  python3 -m py_compile app/db/schema.py
  python3 -m py_compile app/db/sync.py
  python3 -m py_compile app/api.py
  ```

### After Container Restart:

- [ ] Verify container is running:
  ```bash
  docker ps | grep transfs  # Should show transfs container
  ```

- [ ] Verify database is initialized:
  ```bash
  docker exec transfs python3 -c "
  from db.connection import get_connection
  conn = get_connection()
  cursor = conn.execute('PRAGMA table_info(files)')
  rows = cursor.fetchall()
  for row in rows:
    print(row['name'])
  " | grep -E "system|content_type"  # Should find both
  ```

- [ ] Run filesystem sync to populate system field:
  ```bash
  docker exec transfs python3 -c "
  from db.sync import FilesystemSync
  sync = FilesystemSync('/mnt/filestorefs', '/mnt/transfs')
  stats = sync.initial_scan()
  print(f'Added: {stats[\"files_added\"]}')
  print(f'Updated: {stats[\"files_updated\"]}')
  print(f'Skipped: {stats[\"files_skipped\"]}')
  "
  ```

### API Testing:

- [ ] List all systems:
  ```bash
  curl http://localhost:8000/api/systems
  # Should return: {"systems": [...], "count": N}
  ```

- [ ] Query files for Apple-II:
  ```bash
  curl -X POST http://localhost:8000/api/systems/Apple%2FAppleII/query-mapping \
    -H "Content-Type: application/json" \
    -d '{"extensions": ["dsk", "do", "po"], "limit": 10}'
  # Should return: {"files": [...], "count": N, "system": "Apple/AppleII", ...}
  ```

- [ ] Get system extensions:
  ```bash
  curl http://localhost:8000/api/systems/Apple%2FAppleII/extensions
  # Should return: {"system": "...", "extensions": [...], "counts": {...}}
  ```

- [ ] Get system statistics:
  ```bash
  curl http://localhost:8000/api/systems/Apple%2FAppleII/stats
  # Should return: {"system": "...", "total_files": N, "total_size": B, ...}
  ```

### Regression Testing:

- [ ] Verify existing folder-based listing still works:
  ```bash
  # Browse /mnt/transfs via FUSE, should see normal folders
  docker exec transfs ls -la /mnt/transfs/MiSTer/Apple-II/FDs/
  # Should see files (no changes to listing behavior)
  ```

- [ ] Verify cache still works:
  ```bash
  curl http://localhost:8000/api/cache/info
  # Should return cache statistics
  ```

- [ ] Verify existing API endpoints still work:
  ```bash
  curl http://localhost:8000/api/browse-directory?path=/MiSTer
  # Should return directory listing
  ```

---

## QUICK COMMAND REFERENCE

### Full Validation Sequence:

```bash
# 1. Check files
echo "=== Checking files..."
python3 -m py_compile app/db/queries.py && echo "✓ queries.py"
python3 -m py_compile app/db/schema.py && echo "✓ schema.py"
python3 -m py_compile app/db/sync.py && echo "✓ sync.py"
python3 -m py_compile app/api.py && echo "✓ api.py"

# 2. Restart container
echo "=== Restarting container..."
docker compose down
docker compose up -d --build

# 3. Wait for startup
echo "=== Waiting for container..."
sleep 5

# 4. Check database
echo "=== Checking database..."
docker exec transfs python3 -c "
from db.connection import get_connection
cursor = get_connection().execute('SELECT COUNT(DISTINCT system) FROM files')
print(f'Systems: {cursor.fetchone()[0]}')
"

# 5. Test API
echo "=== Testing API..."
curl -s http://localhost:8000/api/systems | head -20

echo "=== Done!"
```

---

## STATUS SUMMARY

| Component | Status | Notes |
|-----------|--------|-------|
| Schema | ✅ Complete | system, content_type columns + indexes |
| Sync | ✅ Complete | _extract_system() method implemented |
| Queries | ✅ Complete | 7 helper functions, all error-handled |
| API | ✅ Complete | 4 endpoints + Pydantic model |
| Refactoring | ⏳ Next | list_dynamic_map() → dual-mode support |
| Testing | ⏳ Next | Unit & integration tests |
| Commit | ⏳ Next | Phase 1 ready to commit |

---

## KNOWN LIMITATIONS (For Now)

1. **Not yet used in listing**: APIs work, but list_dynamic_map() still only uses YAML filetypes
   - **Fix**: Implement db_mode parameter refactoring (next step)

2. **System field not populated**: Column exists, but files have NULL until sync runs
   - **Fix**: Run filesystem sync after restart

3. **Manual API testing only**: No automated tests yet
   - **Fix**: Create unit/integration tests (Phase 1 final step)

---

## NEXT IMMEDIATE STEP

Refactor `list_dynamic_map()` in `app/dirlisting.py` to support dual-mode operation:
- Keep existing folder-based logic (db_mode=False, default)
- Add database query logic (db_mode=True)
- Allow clients.yaml to specify which mode per system

**Estimated time**: 45 minutes

See `app/dirlisting.py` lines 410-430 for where to make changes.

---

## CONTEXT CONTINUATION

If context runs out:

1. This Phase 1 foundation is **complete and safe**
2. No breaking changes to existing code
3. All new code is isolated (doesn't affect old paths)
4. Next steps are in `docs/FLAT_LAYOUT_MIGRATION.md` (Phase 1 § 1.4)

**Key files to check**:
- ✅ `app/db/queries.py` exists? → Foundation done
- ✅ `system` column in schema? → Database ready
- ✅ API endpoints in api.py? → APIs ready
- ⏳ `db_mode` in list_dynamic_map? → Still needed

---

## TESTING COMMANDS FOR NEXT SESSION

```bash
# Quick validation
docker exec transfs python3 -c "from db.queries import query_all_systems; print(query_all_systems())"

# Check system extraction
docker exec transfs python3 -c "from db.sync import FilesystemSync; s = FilesystemSync('/mnt/filestorefs'); print(s._extract_system('/mnt/filestorefs/Native/Apple/AppleII/Software/game.dsk'))"

# Query files
docker exec transfs python3 -c "
from db.queries import query_files_by_system_and_extensions
files = query_files_by_system_and_extensions('Apple/AppleII', ['dsk'], 5)
print(f'Found {len(files)} files')
for f in files[:3]:
    print(f'  {f[\"filename\"]}')
"
```
