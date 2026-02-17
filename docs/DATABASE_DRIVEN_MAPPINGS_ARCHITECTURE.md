## Database-Driven Mappings: Before & After

### CURRENT ARCHITECTURE (YAML-Driven)

```
clients.yaml
├── MiSTer:
│   └── systems:
│       └── Apple-II:
│           └── ...SoftwareArchives...:
│               ├── filetypes: "FDs: DSK,DO,PO,2MG"
│               │   (Hardcoded extension list)
│               └── source_dir: Software
│
┌─────────────────────────────────────┐
│ list_dynamic_map()                  │
│ - Read filetypes from YAML          │
│ - real_exts = [DSK, DO, PO, 2MG]   │
│ - For each ext: scan folder         │
│ - Apply extension mapping           │
│ - Return entries                    │
└─────────────────────────────────────┘
        ↓
    Filesystem scan
    /mnt/filestorefs/Native/Apple/AppleII/Software/
    ├── dsk/
    ├── do/
    ├── po/
    └── 2mg/
```

**Limitation**: 
- Can't show files without updating YAML
- No dynamic queries (e.g., "all .nib files")
- All extensions must exist in physical folders

---

### PROPOSED ARCHITECTURE (Database + YAML)

```
┌─────────────────────────────┐         ┌────────────────────────┐
│ clients.yaml (YAML-mode)    │         │ Database Query (new)   │
│                             │         │                        │
│ filetypes: "FDs: DSK,DO,PO" │  OR    │ SELECT * FROM files    │
│                             │         │ WHERE system='Apple...'│
│                             │         │ AND extension IN (...)  │
│ (Static, config-driven)     │         │                        │
│                             │         │ (Dynamic, query-driven)│
└────────────┬────────────────┘         └────────┬───────────────┘
             │                                   │
             └───────────┬───────────────────────┘
                         ↓
         ┌───────────────────────────────┐
         │ list_dynamic_map()            │
         │ (Refactored)                  │
         │                               │
         │ Get real_exts from:           │
         │ - YAML (default)              │
         │ - Query results (new)         │
         │                               │
         │ rest of logic unchanged...    │
         └───────────────────────────────┘
                         ↓
         ┌───────────────────────────────┐
         │ Extension mapping + caching   │
         │ (unchanged)                   │
         └───────────────────────────────┘
                         ↓
         ┌───────────────────────────────┐
         │ Virtual folder listing        │
         │ (/mnt/transfs/Apple-II/FDs/)  │
         └───────────────────────────────┘
```

---

### NEW API FLOW (Custom Mapping Query)

```
┌─────────────────────────────────────┐
│ Client UI / Script                  │
│                                     │
│ POST /api/systems/.../query-mapping │
│ {                                   │
│   "extensions": ["nib", "bxy"]     │
│ }                                   │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ API Endpoint (new)                  │
│                                     │
│ Extract system from path            │
│ Query database:                     │
│   SELECT * FROM files              │
│   WHERE system=? AND ext IN (?)     │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ Database Query                      │
│                                     │
│ files table with new system column: │
│ - file_id                           │
│ - source_path                       │
│ - extension                         │
│ - system  ← NEW COLUMN             │
│ - size, mtime, ...                  │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│ Response                            │
│                                     │
│ {                                   │
│   "files": [                        │
│     {                               │
│       "name": "game.nib",          │
│       "path": "Apple-II/.../",     │
│       "system": "Apple/AppleII",   │
│       "extension": "nib"           │
│     },                              │
│     ...                             │
│   ],                                │
│   "count": N                        │
│ }                                   │
└─────────────────────────────────────┘
```

---

### DATA MODEL EVOLUTION

#### Current `files` Table
```sql
CREATE TABLE files (
    file_id INTEGER PRIMARY KEY,
    source_path TEXT UNIQUE,      -- /mnt/filestorefs/Native/Apple/AppleII/.../file.nib
    virtual_path TEXT,            -- /mnt/transfs/Apple-II/.../file.nib
    filename TEXT,                -- file.nib
    extension TEXT,               -- nib
    size INTEGER,
    mtime INTEGER,
    ...
);

CREATE INDEX idx_files_extension ON files(extension);
```

**Problem**: Can't query "all .nib files in AppleII" because no system column

---

#### Proposed `files` Table (with system)
```sql
CREATE TABLE files (
    file_id INTEGER PRIMARY KEY,
    source_path TEXT UNIQUE,      -- /mnt/filestorefs/Native/Apple/AppleII/.../file.nib
    virtual_path TEXT,            -- /mnt/transfs/Apple-II/.../file.nib
    filename TEXT,                -- file.nib
    extension TEXT,               -- nib
    size INTEGER,
    mtime INTEGER,
    system TEXT,                  -- "Apple/AppleII" ← NEW COLUMN
    ...
);

-- Extract from source_path during sync
-- e.g., /mnt/filestorefs/Native/Apple/AppleII/Software/...
--       → system = "Apple/AppleII"

CREATE INDEX idx_files_extension ON files(extension);
CREATE INDEX idx_files_system ON files(system);
CREATE INDEX idx_files_system_ext ON files(system, extension);  -- For fast queries
```

---

### SCHEMA EVOLUTION TIMELINE

**Phase 1: Foundation (Today)**
```sql
-- Add system column
ALTER TABLE files ADD COLUMN system TEXT;
CREATE INDEX idx_files_system ON files(system);

-- Update sync.py to extract system during scan
-- Next scan will populate system field for all files
```

**Phase 2: Query Optimization (Later)**
```sql
-- If performance needed
CREATE INDEX idx_files_system_ext ON files(system, extension);
```

**Phase 3: Persistent Custom Mappings (Future)**
```sql
-- Use existing virtual_mappings table
INSERT INTO virtual_mappings (source_pattern, virtual_pattern, is_active)
VALUES ('Apple/AppleII:nib,bxy', 'Apple-II/All-Disks', 1);

-- OR: Create custom_mappings table if virtual_mappings is insufficient
CREATE TABLE custom_mappings (
    mapping_id INTEGER PRIMARY KEY,
    system TEXT,
    extensions TEXT,  -- JSON list ["nib", "bxy"]
    virtual_name TEXT,
    is_active BOOLEAN,
    created_at INTEGER
);
```

---

### QUERY EXAMPLES (Future API)

#### Query 1: Show all NIB files in AppleII
```python
POST /api/systems/Apple%2FAppleII/query-mapping
{
    "extensions": ["nib"]
}

Response: 15 files found
```

#### Query 2: Show all disk formats in AppleII
```python
POST /api/systems/Apple%2FAppleII/query-mapping
{
    "extensions": ["nib", "bxy", "dsk", "do", "po", "2mg"]
}

Response: 250+ files found
```

#### Query 3: Create virtual mapping
```python
# (Future UI-driven, or manual YAML)
custom_mappings:
  - name: AllDiskImages
    system: Apple/AppleII
    extensions: [nib, bxy, dsk, do, po, 2mg]

# Result: New virtual folder
/mnt/transfs/MiSTer/Apple-II/All-Disk-Images/
  ├── game1.nib
  ├── game2.bxy
  ├── system.2mg (maybe transforms to .do, .po, or .hdv)
  └── ...
```

---

### RISK & COMPLEXITY CHART

```
┌─────────────────────────┬────────┬──────────────┐
│ Component               │ Risk   │ Complexity   │
├─────────────────────────┼────────┼──────────────┤
│ Add system column       │ LOW    │ Simple       │
│ Extract in sync.py      │ LOW    │ Simple       │
│ Database query helper   │ LOW    │ Simple       │
│ Refactor list_dynamic   │ MEDIUM │ Moderate     │
│ API endpoint            │ LOW    │ Simple       │
│ Transform integration   │ HIGH   │ Complex      │
│ UI for mappings         │ MEDIUM │ Moderate     │
└─────────────────────────┴────────┴──────────────┘

Recommended Approach:
Phase 1 (LOW-MEDIUM risk): Do simple foundation work
  ✓ Add column
  ✓ Query helper
  ✓ API endpoint
  ✓ Manual testing

Phase 2 (MEDIUM risk): Refactor list_dynamic_map
  ✓ Make it accept query results
  ✓ Maintain backward compatibility

Phase 3 (Deferred): Transforms, UI
  - Can defer until demand is clear
```

---

### BACKWARD COMPATIBILITY

**All changes are additive**:
- ✅ Existing YAML config still works (default behavior)
- ✅ list_dynamic_map() new parameter is optional
- ✅ API is new, doesn't affect existing code
- ✅ Database column is nullable, migration is non-breaking

**Migration path**:
```
Old system: YAML filetypes only
    ↓ (Add system column)
    ↓ (Rescan filesystem)
    ↓
New system: YAML + Database queries both work
```

