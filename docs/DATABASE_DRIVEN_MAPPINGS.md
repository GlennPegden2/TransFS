# Database-Driven Custom Mappings Architecture

## Overview

This document details the feasibility and architecture for supporting **database-driven custom mappings** instead of (or in addition to) hardcoded YAML `filetypes` entries.

**Goal**: Enable queries like "Show all `.nib` and `.bxy` files in Apple-II" without requiring YAML configuration changes.

## Current Architecture

### File Discovery Flow

```
clients.yaml: filetypes: "FDs: DSK,DO,PO"
         ↓
dirlisting.list_dynamic_map()
         ↓
Iterate through real_exts [DSK, DO, PO]
         ↓
For each extension:
  - Scan filesystem: source_dir/extension/
  - Apply extension mapping (DSK→FD)
  - Return entries
```

### Current Data Model

**files table** (in database):
- `file_id` (PK)
- `source_path` (UNIQUE) - Full filesystem path
- `virtual_path` - Virtual path under /mnt/transfs
- `filename` - Basename
- **`extension`** - File extension (nib, bxy, dsk, po, etc.)
- `size`, `mtime`, etc.

**metadata table** (linked to files):
- `file_id` (FK)
- `genre`, `region`, `year`, `publisher`, etc.
- Could be extended with **system** field

**virtual_mappings table** (exists but unused):
- `mapping_id` (PK)
- `source_pattern`
- `virtual_pattern`
- `priority`
- `is_active`

### Key Limitation: Missing System Association

**Problem**: Files table doesn't have `system` field, so we can't query "all .nib files in AppleII".

**Files are discovered from**:
```
/mnt/filestorefs/Native/
  ├── Apple/
  │   ├── AppleII/
  │   │   └── Software/
  │   │       ├── nib/
  │   │       ├── bxy/
  │   │       └── ...
  ├── Atari/
  │   ├── AtariST/
  │   └── ...
```

**Current workaround**: Parse `source_path` to extract system:
```python
# /mnt/filestorefs/Native/Apple/AppleII/Software/nib/file.nib
# Extract: Apple/AppleII (system) → files belong to AppleII
parts = source_path.split('/')
system_path = '/'.join(parts[3:5])  # Apple/AppleII
```

## Feasibility Assessment

### ✅ What We Have

1. **Database exists with file data**
   - Files indexed by extension
   - Files indexed by path
   - Can query "all .nib files" easily

2. **System identification possible**
   - Source paths follow standard layout: `Native/Manufacturer/System/Software/...`
   - Can extract system from path regex or column

3. **Extension mapping infrastructure exists**
   - `reverse_map` dict: `{DSK: FD, DO: FD, PO: FD, ...}`
   - `get_effective_output_extension()` in transform pipeline
   - Transform plugins can auto-detect format

4. **Directory listing function is modular**
   - `list_dynamic_map()` accepts `real_exts` list
   - Could accept **query results** instead of just YAML-derived lists
   - Caching mechanism is in-memory session-scoped

### ⚠️ What Needs Changes

#### 1. **Add System Column to files table** (Schema Migration)

```sql
ALTER TABLE files ADD COLUMN system TEXT;
CREATE INDEX idx_files_system ON files(system);
```

Extract from source_path during sync:
```python
# /mnt/filestorefs/Native/Apple/AppleII/Software/nib/file.nib
def extract_system(source_path: str) -> str:
    parts = source_path.split('/')
    if len(parts) >= 5 and parts[2] == 'Native':
        return f"{parts[3]}/{parts[4]}"  # Apple/AppleII
    return None
```

#### 2. **Refactor list_dynamic_map() to Accept Query Results**

**Option A: Query Object**
```python
def list_dynamic_map(
    config, path, root_parts, system, sa_entry, map_name,
    extension_source=None  # New parameter
):
    # Get real_exts from YAML (default) or query results
    if extension_source == "query":
        real_exts = sa_entry.get("_queried_extensions", [])
    else:
        filetype_map, _ = get_filetype_maps(sa_entry)
        real_exts = filetype_map.get(map_name.upper(), [])
```

**Option B: Separate Function**
```python
def list_custom_mapping(config, path, extensions_from_query):
    """List directory using query-provided extensions instead of YAML."""
    # Same logic as list_dynamic_map, but extensions come from DB query
```

#### 3. **Create API Endpoint for Custom Mappings**

```python
@app.route('/api/systems/<system>/mappings/query', methods=['POST'])
def query_custom_mapping(system):
    """
    Query database for custom mapping results.
    
    POST body:
    {
        "extensions": ["nib", "bxy"],
        "system": "Apple/AppleII"
    }
    
    Returns:
    {
        "files": [
            {
                "name": "Game1.nib",
                "path": "/Apple-II/Software/Game1.nib",
                "system": "Apple/AppleII"
            }
        ]
    }
    """
```

#### 4. **Update Database Sync to Extract System**

In [app/db/sync.py](app/db/sync.py):

```python
def _add_file(self, conn, rel_path: str, stats: dict):
    # ... existing code ...
    
    system = self._extract_system(rel_path)
    
    conn.execute(
        """INSERT INTO files (
            source_path, virtual_path, system, extension, ...
        ) VALUES (...)""",
        (source_path, virtual_path, system, extension, ...)
    )

def _extract_system(self, rel_path: str) -> str:
    """Extract system from path like 'Native/Apple/AppleII/Software/...'"""
    parts = rel_path.split('/')
    if len(parts) >= 4 and parts[0] == 'Native':
        return f"{parts[1]}/{parts[2]}"  # Manufacturer/System
    return None
```

## Implementation Plan

### Phase 1: Foundation (Low Risk)

1. **Add system column to files table**
   - Schema migration in [app/db/schema.py](app/db/schema.py)
   - Update [app/db/sync.py](app/db/sync.py) to extract system
   - Rescan filesystem to populate `system` field

2. **Create query helper function**
   ```python
   # app/db/queries.py (new)
   def query_files_by_system_and_extensions(
       system: str, extensions: List[str]
   ) -> List[FileEntry]:
       """Query files for custom mapping."""
       return conn.execute(
           "SELECT * FROM files WHERE system = ? AND extension IN ({})".format(
               ','.join(['?'] * len(extensions))
           ),
           [system] + extensions
       )
   ```

3. **Wire into list_dynamic_map()**
   - Add optional `extension_source` parameter
   - Accept pre-computed `real_exts` from query

### Phase 2: API Exposure

1. **Create `/api/custom-mapping/query` endpoint**
   - Accept system + extension list
   - Return file listing (no transform pipeline yet)

2. **Manual testing**
   - Query: system=Apple/AppleII, extensions=[nib, bxy]
   - Verify results match filesystem

### Phase 3: UI Integration

1. **Add UI for custom mapping creation**
   - System selector
   - Extension multi-select
   - Virtual folder name

2. **Store user-defined mappings in virtual_mappings table**
   - Can be persistence layer for saved queries

## Code Changes Required

### [app/db/schema.py](app/db/schema.py)
```diff
CREATE TABLE IF NOT EXISTS files (
    ...
    extension TEXT,
    size INTEGER NOT NULL,
+   system TEXT,  -- Extracted from source_path (Native/Manufacturer/System)
    ...
);

+CREATE INDEX IF NOT EXISTS idx_files_system ON files(system);
+CREATE INDEX IF NOT EXISTS idx_files_system_ext ON files(system, extension);
```

### [app/db/sync.py](app/db/sync.py)
```python
def _extract_system(self, rel_path: str) -> str:
    """Extract system from path like 'Native/Apple/AppleII/Software/...'"""
    parts = rel_path.split('/')
    if len(parts) >= 4 and parts[0] == 'Native':
        return f"{parts[1]}/{parts[2]}"  # e.g., "Apple/AppleII"
    return None

def _add_file(self, ...):
    # ... existing code ...
    system = self._extract_system(rel_path)
    
    conn.execute(
        """INSERT INTO files (
            source_path, virtual_path, filename, extension,
            size, system, mtime, ...
        ) VALUES (...)""",
        (..., system, ...)
    )
```

### [app/dirlisting.py](app/dirlisting.py)
```python
def list_dynamic_map(
    config, path, root_parts, system, sa_entry, map_name,
    extension_source=None,  # "yaml" (default) or "query"
    queried_extensions=None  # Pre-computed from database
):
    """
    List directory for dynamic software archives map.
    
    extension_source: How to determine extensions to scan
        - "yaml": Use filetypes from clients.yaml (default)
        - "query": Use queried_extensions list from database
    queried_extensions: Pre-computed extension list from DB query (for "query" mode)
    """
    if extension_source == "query" and queried_extensions:
        real_exts = queried_extensions
    else:
        filetype_map, _ = get_filetype_maps(sa_entry)
        real_exts = filetype_map.get(map_name.upper(), [])
    
    # Rest of function unchanged
    ...
```

### [app/api.py](app/api.py)
```python
@app.route('/api/systems/<system>/query-mapping', methods=['POST'])
def query_custom_mapping(system):
    """
    Query files for custom mapping creation.
    
    POST: {
        "extensions": ["nib", "bxy"],
        "limit": 100
    }
    
    Response: {
        "files": [
            {"name": "file.nib", "path": "..."},
            ...
        ],
        "count": N
    }
    """
    data = request.json
    extensions = data.get('extensions', [])
    limit = data.get('limit', 100)
    
    if not extensions:
        return {'error': 'extensions required'}, 400
    
    conn = get_db_connection()
    cursor = conn.execute(
        """SELECT filename, virtual_path, source_path 
           FROM files 
           WHERE system = ? AND extension IN ({})
           LIMIT ?""".format(','.join(['?'] * len(extensions))),
        [system] + extensions + [limit]
    )
    
    files = [dict(row) for row in cursor.fetchall()]
    return {
        'files': files,
        'count': len(files),
        'system': system,
        'extensions': extensions
    }
```

## Alternative Approaches

### Approach 1: Metadata-Only (Current Proposal)
- Query database for file extension + system
- No transform pipeline integration
- Fast, lightweight
- Good for "show all .nib files"

### Approach 2: Full Transform Integration
- Query → get files → run through transform pipeline
- Supports automatic format detection (2MG → DO/PO/HDV)
- More complex, slower
- Good for "show all Apple disks (mixed formats)"

### Approach 3: Hybrid View
- Create virtual collection/group in database
- Link files to group via collection_members table
- Display as virtual folder
- Requires more schema changes, but very flexible

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|-----------|
| Add `system` column | LOW | Non-breaking, nullable, index can be added later |
| Schema migration | LOW | No existing schema version, fresh start |
| Modify sync.py | LOW | Pure addition, doesn't affect existing code |
| Refactor list_dynamic_map() | MEDIUM | Parameter is optional, defaults to YAML behavior |
| New API endpoint | LOW | Isolated, no side effects |

## Testing Strategy

1. **Unit tests**
   - `_extract_system()` path parsing
   - Query helper functions

2. **Integration tests**
   - Database: Insert files with system, query by system+extension
   - API: POST to `/api/systems/Apple%2FAppleII/query-mapping`
   - Listing: Verify list_dynamic_map() accepts query results

3. **Manual testing**
   - Query: "all .nib and .bxy files in AppleII"
   - Verify files appear in virtual listing
   - Compare with filesystem scan

4. **Performance tests**
   - Database query speed (should be <100ms for typical queries)
   - In-memory caching effectiveness

## Example Usage (Future)

```python
# API Query
POST /api/systems/Apple%2FAppleII/query-mapping
{
    "extensions": ["nib", "bxy"]
}

# Response
{
    "files": [
        {"name": "Game1.nib", "path": "Apple-II/Software/Game1.nib"},
        {"name": "Game2.bxy", "path": "Apple-II/Software/Game2.bxy"},
        ...
    ],
    "count": 47
}

# In clients.yaml (future custom mapping)
custom_mappings:
  - name: AllAppleDiskImages
    system: Apple/AppleII
    extensions: [nib, bxy, dsk, do, po, 2mg]
    virtual_name: "All Disks"

# Would automatically appear as virtual folder:
# /mnt/transfs/Client/AppleII/All Disks/
```

## Summary

**Answer to your question**: **YES, we have 85% of the infrastructure in place.**

What's needed:
1. ✅ Database (exists)
2. ✅ File extension data (exists)
3. ✅ Path extraction (easy to add)
4. ⚠️ System column in files table (schema migration)
5. ⚠️ Query function (straightforward DB query)
6. ⚠️ API endpoint (new Flask route)
7. ⚠️ list_dynamic_map() refactoring (add optional parameter)

**Effort estimate**: ~2-4 hours for Phase 1 (foundation), minimal risk.

**Next step**: Would you like me to implement Phase 1?
