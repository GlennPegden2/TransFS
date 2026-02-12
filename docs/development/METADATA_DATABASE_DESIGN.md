# Metadata Database Architecture Design

**Status**: Design Proposal  
**Created**: 2026-02-12  
**Author**: Architecture Discussion

## Executive Summary

Proposal to replace the current pickle-based cache system with a structured database containing file metadata, enabling graph-like path queries through the FUSE layer for more granular organization and filtering.

### Key Goals
- **Rich Metadata**: Store genre, language, collections, and custom attributes
- **Graph Queries**: Path-based queries like `/Genre/Action/Language/English/`
- **Performance**: Match or exceed current system performance
- **Compatibility**: Maintain all existing features (transforms, merging, filtering)
- **Parallel Development**: Toggle between old and new systems

---

## Current Architecture Analysis

### Existing System
```
┌─────────────────────────────────────────────────────┐
│ FUSE Layer (transfs.py)                             │
│  - readdir() → os.scandir() + cache lookup          │
│  - getattr() → stat() + pickle cache                │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Mapping Layer (sourcepath.py, dirlisting.py)        │
│  - Virtual path → Source path resolution            │
│  - Dynamic maps (SoftwareArchives)                  │
│  - Extension subdirectory merging                   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Cache Layer (Pickle files)                          │
│  - .transfs_cache.pkl (directory listings)          │
│  - .transfs_getattr_cache.pkl (file attributes)     │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Filesystem (Native storage)                         │
│  - /mnt/filestorefs/Native/...                      │
└─────────────────────────────────────────────────────┘
```

### Performance Characteristics
- **Small directories** (< 100 files): < 0.5s
- **Large directories** (3500+ files): 0.6-2s (after optimizations)
- **Cache hits**: Near-instant (< 0.01s)
- **Cache misses**: Requires full directory scan

### Current Limitations
1. No metadata beyond filesystem stats
2. Limited query/filter capabilities
3. Cache invalidation relies on mtime checks
4. Complex mapping logic for virtual paths
5. No support for collections or tags

---

## Proposed Architecture

### Database-Backed Metadata System

```
┌─────────────────────────────────────────────────────┐
│ FUSE Layer (transfs.py)                             │
│  - readdir() → Database query                       │
│  - getattr() → Database lookup                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Query Translator (NEW)                              │
│  - Path → SQL query                                 │
│  - /Genre/Action/ → SELECT ... WHERE genre='Action' │
│  - /Collections/Favorites/ → JOIN collections       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Metadata Database (SQLite)                          │
│  - files table (path, size, mtime, ino, ...)        │
│  - metadata table (genre, language, tags, ...)      │
│  - collections table (collection_id, file_id)       │
│  - transforms table (source_file, pipeline, ...)    │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Filesystem Sync Layer (NEW)                         │
│  - Watches for file changes                         │
│  - Updates database on adds/deletes/modifications   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Filesystem (Native storage)                         │
│  - /mnt/filestorefs/Native/...                      │
└─────────────────────────────────────────────────────┘
```

---

## Data Model

### Core Tables

#### `files`
```sql
CREATE TABLE files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL UNIQUE,      -- Real filesystem path
    virtual_path TEXT,                     -- Computed virtual path
    filename TEXT NOT NULL,
    extension TEXT,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    ctime INTEGER NOT NULL,
    atime INTEGER NOT NULL,
    ino INTEGER,
    mode INTEGER,
    is_directory BOOLEAN DEFAULT 0,
    is_archive BOOLEAN DEFAULT 0,
    archive_format TEXT,                   -- 'zip', '7z', etc.
    INDEX idx_source_path (source_path),
    INDEX idx_virtual_path (virtual_path),
    INDEX idx_extension (extension),
    INDEX idx_mtime (mtime)
);
```

#### `metadata`
```sql
CREATE TABLE metadata (
    meta_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    
    -- Content metadata
    genre TEXT,
    subgenre TEXT,
    language TEXT,
    region TEXT,                           -- USA, Europe, Japan, etc.
    year INTEGER,
    publisher TEXT,
    developer TEXT,
    
    -- Quality indicators
    rating REAL,                           -- User/community rating
    play_count INTEGER DEFAULT 0,
    last_played INTEGER,
    
    -- Status flags
    is_prototype BOOLEAN DEFAULT 0,
    is_homebrew BOOLEAN DEFAULT 0,
    is_translation BOOLEAN DEFAULT 0,
    is_hack BOOLEAN DEFAULT 0,
    
    -- Custom tags (JSON array)
    tags TEXT,                             -- '["multiplayer", "coop"]'
    
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    INDEX idx_genre (genre),
    INDEX idx_language (language),
    INDEX idx_region (region),
    INDEX idx_year (year)
);
```

#### `collections`
```sql
CREATE TABLE collections (
    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    INDEX idx_name (name)
);

CREATE TABLE collection_members (
    collection_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    added_at INTEGER NOT NULL,
    sort_order INTEGER,
    PRIMARY KEY (collection_id, file_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);
```

#### `transforms`
```sql
CREATE TABLE transforms (
    transform_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    pipeline TEXT NOT NULL,                -- JSON: [{"tool": "zip2zip", ...}]
    target_extension TEXT,
    estimated_output_size INTEGER,
    is_active BOOLEAN DEFAULT 1,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    INDEX idx_file_transform (file_id, is_active)
);
```

#### `virtual_mappings`
```sql
CREATE TABLE virtual_mappings (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pattern TEXT NOT NULL,         -- '/Native/Atari/5200/%'
    virtual_pattern TEXT NOT NULL,        -- '/MiSTer/Atari5200/%'
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    INDEX idx_source_pattern (source_pattern),
    INDEX idx_priority (priority DESC)
);
```

---

## Path Query System

### Virtual Path Resolution

The core innovation: paths become queries against the database.

#### Example Path Patterns

1. **Traditional Directory**: `/MiSTer/Atari5200/ROMs/`
   ```sql
   SELECT * FROM files 
   WHERE virtual_path LIKE '/MiSTer/Atari5200/ROMs/%'
   AND is_directory = 0
   ```

2. **Genre Filter**: `/MiSTer/Atari5200/Genre/Action/`
   ```sql
   SELECT f.* FROM files f
   JOIN metadata m ON f.file_id = m.file_id
   WHERE f.virtual_path LIKE '/MiSTer/Atari5200/%'
   AND m.genre = 'Action'
   ```

3. **Multi-Dimensional**: `/MiSTer/Atari5200/Language/English/Genre/Puzzle/`
   ```sql
   SELECT f.* FROM files f
   JOIN metadata m ON f.file_id = m.file_id
   WHERE f.virtual_path LIKE '/MiSTer/Atari5200/%'
   AND m.language = 'English'
   AND m.genre = 'Puzzle'
   ```

4. **Collections**: `/Collections/Favorites/`
   ```sql
   SELECT f.* FROM files f
   JOIN collection_members cm ON f.file_id = cm.file_id
   JOIN collections c ON cm.collection_id = c.collection_id
   WHERE c.name = 'Favorites'
   ORDER BY cm.sort_order
   ```

5. **Year Range**: `/MiSTer/Atari5200/Year/1980s/`
   ```sql
   SELECT f.* FROM files f
   JOIN metadata m ON f.file_id = m.file_id
   WHERE f.virtual_path LIKE '/MiSTer/Atari5200/%'
   AND m.year BETWEEN 1980 AND 1989
   ```

### Path Query Grammar

Define a grammar for virtual paths:

```
<base_path>/<filter_type>/<filter_value>[/<filter_type>/<filter_value>]*
```

#### Reserved Filter Types
- `Genre/` - Filter by genre
- `Language/` - Filter by language
- `Region/` - Filter by region
- `Year/` - Filter by year or decade
- `Collections/` - Browse collections
- `Tags/` - Filter by tag
- `Publisher/` - Filter by publisher
- `Prototypes/` - Show only prototypes
- `Homebrew/` - Show only homebrew
- `Recent/` - Recently added files

#### Discovery Directories

Special virtual directories that list available filter values:

- `/MiSTer/Atari5200/_Genres/` → Lists all genres
- `/MiSTer/Atari5200/_Languages/` → Lists all languages
- `/MiSTer/Atari5200/_Years/` → Lists all years

---

## Performance Analysis

### Query Performance Targets

| Operation | Current | Target | Notes |
|-----------|---------|--------|-------|
| Small dir listing (< 100) | < 0.5s | < 0.1s | Indexed query |
| Large dir listing (3500+) | 0.6-2s | < 0.2s | No full scan |
| Filtered query | N/A | < 0.3s | With joins |
| Cache hit | < 0.01s | < 0.01s | Same |
| Initial DB build | N/A | < 10s | For 10k files |
| File change detection | N/A | < 0.1s | Per file |

### Optimization Strategies

1. **Indexes**: All filter columns indexed
2. **Query Plan Caching**: Prepared statements
3. **Denormalization**: Common queries pre-computed
4. **Materialized Views**: For complex aggregations
5. **In-Memory Cache**: SQLite with page cache
6. **Batch Updates**: Filesystem changes batched

### SQLite Configuration

```python
# Optimized for read-heavy workload
PRAGMA journal_mode = WAL;           # Write-Ahead Logging
PRAGMA synchronous = NORMAL;         # Faster writes
PRAGMA cache_size = -64000;          # 64MB page cache
PRAGMA temp_store = MEMORY;          # In-memory temp tables
PRAGMA mmap_size = 268435456;        # 256MB mmap
```

---

## Metadata Population

### Data Sources

1. **Filesystem Extraction**
   - Filename parsing (No-Intro naming convention)
   - File size, dates, permissions
   - Archive contents (zip inspection)

2. **External Databases**
   - No-Intro databases (XML/DAT files)
   - OpenVGDB (SQLite database of ROM metadata)
   - IGDB API (game metadata API)
   - ScreenScraper API (arcade/console metadata)

3. **Manual Curation**
   - YAML/JSON files alongside ROMs
   - Web UI for editing metadata
   - Bulk import from spreadsheets

4. **Automatic Classification**
   - Genre inference from filename patterns
   - Language detection from region codes
   - Year extraction from filenames

### Population Strategy

```python
# Phased population
Phase 1: Filesystem scan (paths, sizes, dates)
Phase 2: Filename parsing (basic metadata)
Phase 3: External database matching
Phase 4: Manual enrichment
```

### Example Filename Parsing

```
"Pac-Man (USA) (Proto).a52"
→ filename: "Pac-Man"
→ region: "USA"
→ is_prototype: True
→ extension: "a52"

"Zelda no Densetsu (Japan) (En,Ja) [T-Eng].bin"
→ filename: "Zelda no Densetsu"
→ region: "Japan"
→ language: "English, Japanese"
→ is_translation: True
```

---

## Compatibility Matrix

### Features to Maintain

| Feature | Current Implementation | Database Approach | Complexity |
|---------|----------------------|-------------------|------------|
| Virtual path mapping | sourcepath.get_source_path() | virtual_mappings table | Medium |
| Transform pipelines | config.yaml + runtime | transforms table | Low |
| Extension merging | A52/BIN/ROM scanning | Query with extension filter | Low |
| Client filtering | clients.yaml + IP check | Add client_id to queries | Medium |
| Dynamic maps | dirlisting.py list_dynamic_map() | Computed views or queries | High |
| Zip hierarchical mode | zippath module | Archive contents table | High |
| Cache invalidation | mtime checks | Filesystem watcher + triggers | Medium |
| Config hot-reload | YAML monitoring | Database triggers | Low |

### Integration Points

1. **FUSE readdir()**: Query database instead of scandir()
2. **FUSE getattr()**: Database lookup instead of stat()
3. **FUSE open()**: Still use real file paths from database
4. **Transform pipeline**: Store metadata, execute on-demand
5. **Client filtering**: WHERE clauses based on client_id

---

## Migration Strategy

### Parallel Development Approach

```python
# Configuration flag
database_mode: enabled | disabled | hybrid

# Hybrid mode: database for metadata, files for stats
# Enables gradual migration and A/B testing
```

### Development Phases

#### Phase 1: Foundation (2-3 weeks)
- [ ] Design database schema
- [ ] Create SQLite database module
- [ ] Implement basic file scanning
- [ ] Build filename parser
- [ ] Write unit tests

#### Phase 2: Core Integration (3-4 weeks)
- [ ] Abstract data access layer (DAL)
- [ ] Implement query translator (path → SQL)
- [ ] Replace readdir() with database queries
- [ ] Replace getattr() with database lookups
- [ ] Maintain backward compatibility

#### Phase 3: Metadata Enrichment (2-3 weeks)
- [ ] External database integrations
- [ ] Metadata import/export tools
- [ ] Web UI for metadata editing
- [ ] Automatic classification rules

#### Phase 4: Advanced Features (3-4 weeks)
- [ ] Collections support
- [ ] Multi-dimensional filtering
- [ ] Custom query paths
- [ ] Performance optimization

#### Phase 5: Testing & Refinement (2-3 weeks)
- [ ] Performance benchmarking
- [ ] Feature parity validation
- [ ] Migration tools (pickle → database)
- [ ] Documentation

**Total estimated time**: 12-17 weeks

### Rollback Strategy

- Feature flag allows instant rollback
- Keep pickle cache system in parallel
- Database failures fall back to legacy code
- Comprehensive logging of both systems

---

## Code Structure

### New Modules

```
app/
  db/
    __init__.py
    schema.py              # Table definitions
    connection.py          # Connection management
    models.py              # ORM models (optional)
    query_builder.py       # SQL query construction
    sync.py                # Filesystem → Database sync
  
  metadata/
    __init__.py
    parser.py              # Filename parsing
    sources/
      nointro.py           # No-Intro DAT parser
      openvgdb.py          # OpenVGDB integration
      igdb.py              # IGDB API client
    enrichment.py          # Metadata enrichment engine
  
  query/
    __init__.py
    translator.py          # Path → SQL translator
    filters.py             # Filter implementations
    virtual_dirs.py        # Discovery directory generation
```

### Data Access Layer

```python
# Abstract interface for both systems
class FileDataProvider(ABC):
    @abstractmethod
    def list_directory(self, path: str, filters: dict) -> List[FileEntry]:
        pass
    
    @abstractmethod
    def get_file_attrs(self, path: str) -> FileAttributes:
        pass

# Pickle-based implementation (current)
class PickleCacheProvider(FileDataProvider):
    pass

# Database implementation (new)
class DatabaseProvider(FileDataProvider):
    pass

# Factory selects based on config
def get_provider(config) -> FileDataProvider:
    if config.get('database_mode') == 'enabled':
        return DatabaseProvider(config)
    else:
        return PickleCacheProvider(config)
```

---

## Filesystem Sync

### Change Detection

```python
# Option 1: inotify/watchdog for real-time updates
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class FilesystemWatcher(FileSystemEventHandler):
    def on_created(self, event):
        # Add to database
        db.insert_file(event.src_path)
    
    def on_deleted(self, event):
        # Remove from database
        db.delete_file(event.src_path)
    
    def on_modified(self, event):
        # Update database
        db.update_file(event.src_path)

# Option 2: Periodic scan with mtime comparison
def incremental_sync():
    # Check database max(mtime)
    last_sync = db.get_last_sync_time()
    
    # Find files modified since last sync
    for path in find_modified_files(since=last_sync):
        db.update_or_insert_file(path)
```

### Bulk Import

```python
def initial_database_build(root_path: str):
    """Build initial database from filesystem."""
    with db.transaction():
        for dirpath, dirnames, filenames in os.walk(root_path):
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                
                filepath = os.path.join(dirpath, filename)
                stat = os.stat(filepath)
                
                # Extract metadata from filename
                meta = parse_filename(filename)
                
                # Insert into database
                file_id = db.insert_file(
                    source_path=filepath,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    ...
                )
                
                if meta:
                    db.insert_metadata(file_id, meta)
```

---

## Example Queries

### Use Case 1: Browse Action Games in English

**Path**: `/MiSTer/Atari5200/Genre/Action/Language/English/`

```sql
SELECT 
    f.filename,
    f.source_path,
    f.size,
    m.genre,
    m.language,
    m.year
FROM files f
JOIN metadata m ON f.file_id = m.file_id
WHERE f.virtual_path LIKE '/MiSTer/Atari5200/%'
  AND m.genre = 'Action'
  AND m.language LIKE '%English%'
ORDER BY f.filename;
```

### Use Case 2: List All Genres

**Path**: `/MiSTer/Atari5200/_Genres/`

```sql
SELECT DISTINCT 
    m.genre as name,
    COUNT(*) as count
FROM metadata m
JOIN files f ON m.file_id = f.file_id
WHERE f.virtual_path LIKE '/MiSTer/Atari5200/%'
  AND m.genre IS NOT NULL
GROUP BY m.genre
ORDER BY m.genre;
```

### Use Case 3: Collection with Transforms

**Path**: `/Collections/MiSTer-Optimized/`

```sql
SELECT 
    f.filename,
    f.source_path,
    t.target_extension,
    t.pipeline
FROM files f
JOIN collection_members cm ON f.file_id = cm.file_id
JOIN collections c ON cm.collection_id = c.collection_id
LEFT JOIN transforms t ON f.file_id = t.file_id AND t.is_active = 1
WHERE c.name = 'MiSTer-Optimized'
ORDER BY cm.sort_order;
```

---

## Risk Assessment

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Performance regression | High | Medium | Benchmark continuously, optimize queries |
| Database corruption | High | Low | WAL mode, backups, auto-repair |
| Metadata quality | Medium | High | Validation rules, manual review |
| Sync lag | Medium | Medium | Real-time watchers, queue processing |
| Memory usage | Medium | Low | Connection pooling, query limits |
| Migration complexity | High | High | Phased rollout, feature flags |

### Operational Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Learning curve | Medium | High | Documentation, examples |
| Initial setup time | Medium | High | Automated scripts, prebuilt databases |
| Maintenance overhead | Medium | Medium | Admin UI, diagnostic tools |
| Data loss | High | Low | Regular backups, export tools |

---

## Success Metrics

### Performance KPIs
- [ ] Directory listing < 200ms (95th percentile)
- [ ] Filtered queries < 300ms (95th percentile)
- [ ] Database size < 1% of file storage
- [ ] Sync lag < 5 seconds for file changes

### Feature KPIs
- [ ] Support 10+ metadata fields per file
- [ ] Enable 5+ dimensional filtering
- [ ] Collections with < 100ms add/remove
- [ ] External database integration for 3+ sources

### Quality KPIs
- [ ] 99%+ feature parity with current system
- [ ] Zero data loss during migration
- [ ] 95%+ test coverage for new code
- [ ] < 1% error rate in production

---

## Open Questions

1. **Metadata Source Priority**: When multiple sources conflict, which wins?
2. **Archive Handling**: Index files inside archives or treat as opaque?
3. **Distributed Databases**: Support for multiple database files (one per system)?
4. **Write Operations**: Allow metadata editing through FUSE (extended attributes)?
5. **Scalability**: What's the file count limit before performance degrades?
6. **Schema Evolution**: How to handle database migrations for future features?
7. **Multi-User**: Concurrent database access from multiple FUSE mounts?
8. **Backup Strategy**: How to backup database alongside files?

---

## Decision: Proceed?

### Pros
✅ Vastly improved metadata and querying  
✅ Simpler caching logic (DB is the cache)  
✅ Enables powerful new features (collections, filters)  
✅ Better performance potential  
✅ Industry-standard approach (SQL)  

### Cons
❌ Significant development effort (12-17 weeks)  
❌ Added complexity (database management)  
❌ Migration risk  
❌ Potential performance regression if poorly implemented  
❌ Metadata quality depends on external sources  

### Recommendation

**YES - Proceed with phased approach:**

1. Implement Phase 1 (Foundation) as proof-of-concept
2. Benchmark against current system
3. If performance is acceptable, continue to Phase 2
4. Maintain parallel development until feature parity
5. Run both systems in hybrid mode for 1-2 months
6. Full cutover only after validation

**Key Success Factors:**
- Feature flag from day one
- Continuous benchmarking
- Backward compatibility maintained
- Comprehensive testing at each phase
- Clear rollback path at all times

---

## Next Steps

If approved:
1. [ ] Review and refine database schema
2. [ ] Create proof-of-concept (Phase 1)
3. [ ] Benchmark basic operations
4. [ ] Present results for Phase 2 go/no-go decision
