# Current Architecture Reference

**Purpose**: Implementation details for database migration phases  
**Companion to**: METADATA_DATABASE_DESIGN.md  
**Last Updated**: 2026-02-12

---

## Module Architecture

```
app/
├── transfs.py              # FUSE filesystem (pyfuse3)
├── passthroughfs.py        # Base FUSE passthrough implementation
├── main.py                 # FastAPI web server
├── api.py                  # REST API endpoints
├── sourcepath.py           # Virtual→source path resolution
├── dirlisting.py           # Dynamic directory listing (SoftwareArchives)
├── pathutils.py            # Path manipulation utilities
├── transforms.py           # Transform pipeline execution
├── post_process.py         # Post-processing (zip2zip, extract, etc.)
├── filetypes.py            # File extension definitions
├── zippath.py              # ZIP archive navigation
├── ziptutils.py            # ZIP utilities
├── cache_warmer.py         # Background cache warming
├── logging_setup.py        # Logging configuration
└── config.py               # Configuration management
```

---

## 1. Module Responsibilities

### transfs.py - FUSE Filesystem Core

**Primary class**: `TransFS(Passthrough)`

#### Key Methods

**`async def readdir(self, fh: FileHandleT, start_id: int, token)`** (Lines ~257-785)
- **Purpose**: List directory contents with full attributes (readdirplus)
- **Input**: File handle, pagination start_id, response token
- **Output**: Sends entries to FUSE via `pyfuse3.readdir_reply()`
- **Key steps**:
  1. Resolve virtual path to source path via `get_source_path()`
  2. Scan source directory with `os.scandir()` (builds `dir_entry_cache`)
  3. Check for extension subdirectories (A52/BIN/ROM merging)
  4. Build `source_paths` dict (maps entry_name → source file path)
  5. For each entry: get/build attributes, send to FUSE
  6. Log performance metrics (parse time, batch time, total time)

**`async def getattr(self, inode: InodeT, ctx=None)`** (Lines ~787-900)
- **Purpose**: Get file attributes by inode
- **Input**: Inode number
- **Output**: `pyfuse3.EntryAttributes` object
- **Flow**:
  1. Resolve inode → virtual path via `_inode_to_path()`
  2. Check getattr cache via `get_cached_getattr()`
  3. If miss: resolve virtual → source via `get_source_path()`
  4. Stat source file with `os.lstat()`
  5. Apply transforms if needed (adjust size/mode)
  6. Cache result via `cache_getattr()`

**`async def open(self, inode: InodeT, flags, ctx)`** (Lines ~1100-1150)
- **Purpose**: Open file for reading
- **Key**: Resolves virtual path and opens source file or applies transform

**Extension Subdirectory Detection** (Lines ~305-350)
```python
# Whitelist of known extension subdirectories
known_extension_subdirs = {'A52', 'BIN', 'ROM', 'TMP', 'CDT', 'CRT', 'CAS', 'TAP'}

# Only scan for siblings if current dir is in whitelist
is_known_extension_subdir = current_subdir_name in known_extension_subdirs

# If in whitelist, scan parent for sibling extension dirs
# Example: In A52/ directory, find BIN/, ROM/ siblings
# Then scan those siblings for same relative path
```

**Performance Optimizations**:
- `dir_entry_cache`: Caches `os.DirEntry` objects to avoid repeated stat calls
- `skip_cache_lookup`: When all entries have DirEntry cache, skip expensive getattr cache lookup
- `fast_listing`: For dirs > 500 files, use minimal stat info (just is_dir check)
- `system_transform_map`: Pre-build transform map once per directory

#### Configuration Flags
```python
cache_config = self.config.get("cache", {})
direntry_cache_enabled = cache_config.get("readdir_direntry_cache_enabled", True)
skip_cache_lookup_enabled = cache_config.get("readdir_skip_cache_lookup_with_direntry", True)
max_readdir_getattr_cache = cache_config.get("readdir_getattr_cache_max_entries", 300)
fast_listing_threshold = cache_config.get("readdir_fast_listing_threshold", 500)
```

---

### sourcepath.py - Path Resolution

**Primary function**: `get_source_path(logger, config, mount_path, vpath)`

**Purpose**: Convert virtual path (e.g., `/mnt/transfs/MiSTer/Atari5200/ROMs`) to source path(s)

**Returns**: 
- `str`: Simple source path (`/mnt/filestorefs/...`)
- `dict`: Complex result with transforms
  ```python
  {
      'path': '/mnt/filestorefs/...',
      'transform_pipeline': [{'tool': 'zip2zip', ...}]
  }
  ```
- `tuple`: ZIP internal file `(zip_path, internal_path)`

**Resolution Priority**:
1. **Virtual mappings** (client-specific, then default)
2. **Dynamic maps** (SoftwareArchives) → calls `list_dynamic_map()`
3. **Transform mappings** (file extension transforms)
4. **Native paths** (direct filesystem)

**Key Data Structures**:
```python
# Client-specific mapping example
virtual_mappings = {
    'default': {
        '/MiSTer/Atari5200': {
            'source': '/Native/Atari/5200',
            'filetypes': ['a52', 'bin', 'rom']
        }
    }
}

# Transform example
'a52': {
    'filetype': 'zip',
    'transform': {
        'tool': 'zip2zip',
        'extensions': ['a52', 'bin'],
        'flattenDirs': True
    }
}
```

---

### dirlisting.py - Dynamic Directory Listing

**Primary function**: `list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)`

**Purpose**: Generate virtual directory listings for SoftwareArchives mapped paths

**Use case**: When path doesn't exist on disk but is mapped in config
```
/MiSTer/Atari5200/ROMs → doesn't exist
Maps to: /Native/Atari/5200/Software/{A52,BIN,ROM}/ with merging
```

**Key Algorithm** (Lines ~540-730):
1. Parse path components to determine depth and target
2. Build `extension_name_map` from filetypes config
3. For each extension directory (A52/, BIN/, etc.):
   - Scan directory with `os.listdir()`
   - Map real extension → virtual extension (BIN → .rom)
   - Filter files by extension
   - Handle nested directories (e.g., A52/Prototype Games/)
4. Deduplicate entries across extension dirs
5. Cache result with mtime validation

**Critical Bug Fix** (Line 569):
```python
# OLD (WRONG): path_components = subpath[:-1]  # Removed last element!
# NEW (CORRECT):
path_components = subpath if subpath else []
```
This was causing files in nested directories to appear at wrong level.

**Cache Structure**:
```python
cache_key = f"{source_dir}:{','.join(filetypes)}:{subpath_str}"
cache = {
    'entries': [...],
    'mtime': 1234567890,
    'extension_name_map': {...}
}
```

---

### config.py - Configuration Management

**Primary functions**:
- `read_config()`: Load ALL config (app.yaml + clients.yaml + all sources/*.yaml)
- `read_app_config()`: Load ONLY app.yaml (lightweight)

**Configuration Structure**:

#### app.yaml
```yaml
filestore: /mnt/filestorefs
mount_path: /mnt/transfs
web_api:
  host: 0.0.0.0
  port: 8000
cache:
  readdir_direntry_cache_enabled: true
  readdir_skip_cache_lookup_with_direntry: true
  readdir_getattr_cache_max_entries: 300
  readdir_fast_listing_threshold: 500
```

#### clients.yaml
```yaml
clients:
  - name: MiSTer
    ips: ["192.168.1.100"]
    hostnames: ["MiSTer"]
    mappings_override: mister
```

#### source configuration (e.g., Atari5200.yaml)
```yaml
Atari 5200:
  path: Atari/5200
  filetypes:
    - a52
    - bin
    - rom
  destination_path: /MiSTer/Atari5200/ROMs
  mode: dynamic_map
  map_type: SoftwareArchives
  software_dir: Software
  shared_dir: Shared
```

**Dynamic Reload**: Monitors config files for changes, hot-reloads without restart

---

## 2. Key Data Flows

### Flow 1: Directory Listing (readdir)

```
User: ls /mnt/transfs/MiSTer/Atari5200/ROMs
         ↓
FUSE: readdir(inode, start_id=0, token)
         ↓
transfs.py: _inode_to_path(inode) → "/mnt/transfs/MiSTer/Atari5200/ROMs"
         ↓
transfs.py: get_source_path(logger, config, mount_path, vpath)
         ↓
sourcepath.py: Check virtual_mappings
         ↓ (dynamic map)
dirlisting.py: list_dynamic_map() 
    → Scan /Native/Atari/5200/Software/{A52,BIN,ROM}/
    → Merge files from all extension dirs
    → Return: ['game1.a52', 'game2.bin', ...]
         ↓
transfs.py: Build source_paths dict
    game1.a52 → /Native/Atari/5200/Software/A52/game1.a52
    game2.bin → /Native/Atari/5200/Software/BIN/game2.bin
         ↓
transfs.py: For each entry, get attributes
    - Check getattr cache
    - If miss: stat source file
    - Apply transforms if configured
    - Build pyfuse3.EntryAttributes
         ↓
transfs.py: pyfuse3.readdir_reply(token, name, attrs, entry_id)
         ↓
User sees: -rw-r--r-- 1 root root 8192 game1.a52
           -rw-r--r-- 1 root root 16384 game2.bin
```

### Flow 2: File Access (open/read)

```
User: cat /mnt/transfs/MiSTer/Atari5200/ROMs/game.a52
         ↓
FUSE: open(inode, flags, ctx)
         ↓
transfs.py: Resolve virtual → source path
         ↓
Check if transform needed (a52 → zip)
         ↓
  YES: Execute transform pipeline
    transforms.py: apply_transform()
      → Run zip2zip tool
      → Create temp file
      → Return temp file FD
         ↓
  NO: Open source file directly
    os.open(source_path, flags)
         ↓
FUSE: read(fh, offset, size)
         ↓
transfs.py: os.read(source_fd, size)
         ↓
User receives file data
```

### Flow 3: Extension Subdirectory Merging

```
Directory: /Native/Atari/5200/Software/
    A52/
        game1.a52
        Prototype Games/
            proto1.a52
    BIN/
        game2.bin
        Prototype Games/
            proto2.bin
    ROM/
        game3.rom

Virtual path: /MiSTer/Atari5200/ROMs/
    ↓ readdir()
    ↓ Check: current_subdir = "A52" (or BIN, ROM)
    ↓ Is "A52" in known_extension_subdirs? YES
    ↓ Scan parent for siblings: finds BIN, ROM
    ↓ extension_subdirs = [
        "/Native/Atari/5200/Software/BIN",
        "/Native/Atari/5200/Software/ROM"
      ]
    ↓ Scan main dir (A52/) + siblings (BIN/, ROM/)
    ↓ Merge and deduplicate entries
    ↓ Result: [game1.a52, game2.bin, game3.rom]

Virtual path: /MiSTer/Atari5200/ROMs/Prototype Games/
    ↓ readdir()
    ↓ Check: parent is "A52" (extension subdir)
    ↓ relative_subpath = "Prototype Games"
    ↓ extension_subdirs = [
        "/Native/Atari/5200/Software/BIN/Prototype Games",
        "/Native/Atari/5200/Software/ROM/Prototype Games"
      ]
    ↓ Scan A52/Prototype Games/ + BIN/Prototype Games/
    ↓ Result: [proto1.a52, proto2.bin]
```

---

## 3. Cache System

### Cache Files

**Location**: `/mnt/filestorefs/.transfs_cache.pkl` (directory listings)
**Location**: `/mnt/filestorefs/.transfs_getattr_cache.pkl` (file attributes)

### Directory Listing Cache

**Key**: Virtual path (e.g., `/mnt/transfs/MiSTer/Atari5200/ROMs`)
**Value**:
```python
{
    'entries': ['game1.a52', 'game2.bin', ...],
    'mtime': 1234567890,  # Source directory mtime
    'extension_name_map': {'BIN': '.rom', 'A52': '.a52'}
}
```

**Invalidation**: Compare current source dir mtime with cached mtime

### Getattr Cache

**Key**: `f"{virtual_path}:{parent_source_dir}"`
**Value**:
```python
{
    'st_atime': 1234567890,
    'st_ctime': 1234567890,
    'st_mtime': 1234567890,
    'st_gid': 0,
    'st_uid': 0,
    'st_mode': 0o100444,
    'st_nlink': 1,
    'st_size': 8192
}
```

**Invalidation**: No automatic invalidation - relies on periodic clears

### Cache Functions

```python
# dirlisting.py
def get_cached_listing(cache_key: str) -> Optional[dict]:
    """Check if directory listing is cached and valid."""
    
def cache_listing(cache_key: str, entries: list, mtime: int, extension_name_map: dict):
    """Cache directory listing with metadata."""

# transfs.py (via imported functions)
def get_cached_getattr(virtual_path: str, parent_dir: str) -> Optional[dict]:
    """Check getattr cache."""
    
def cache_getattr(virtual_path: str, parent_dir: str, stat_dict: dict):
    """Cache file attributes."""
```

---

## 4. Transform System

### Transform Pipeline Structure

```yaml
# In source config (e.g., Atari5200.yaml)
a52:
  filetype: zip
  transform:
    tool: zip2zip
    extensions: [a52, bin]
    flattenDirs: true
    removePrefix: "Atari 5200"
```

### Transform Execution

**Function**: `apply_transform(pipeline: list, source_path: str, logger) → str`

**Tools**:
- `zip2zip`: Repackage ZIP with different structure
- `extract`: Extract archive to temp directory
- `atr2dsk`: Convert ATR to DSK format (Atari disk images)

**Temp File Management**:
- Creates temp files in system temp dir
- Returns temp file path
- FUSE release() cleans up temp files

**Size Estimation**:
```python
def _get_transform_output_size(self, pipeline: list, input_size: int) -> int:
    """Estimate output size for transformed files."""
    # Returns approximate size for proper file stat reporting
```

---

## 5. Performance Characteristics

### Current Benchmarks (After Optimizations)

| Operation | File Count | Time | Notes |
|-----------|-----------|------|-------|
| Small dir readdir | < 100 | < 0.5s | Direct filesystem |
| Large dir readdir | 3500 | 0.6s | Amstrad FDs with cache |
| Extension merge | 29 files | < 0.1s | Atari 5200 nested dir |
| Dynamic map (cold) | 3500 | 2s | First access, builds cache |
| Dynamic map (warm) | 3500 | 0.6s | Cache hit |
| Getattr (cached) | 1 file | < 0.01s | Cache hit |
| Getattr (uncached) | 1 file | 0.01-0.05s | Stat + cache store |

### Optimization Techniques in Use

1. **DirEntry Cache** (Lines ~372-378 in transfs.py)
   ```python
   with os.scandir(parent_dir) as entries:
       for entry in entries:
           dir_entry_cache[entry.name] = entry  # Caches stat info
   ```

2. **Skip Cache Lookup** (Lines ~434-443)
   ```python
   if skip_cache_lookup_enabled and dir_entry_cache:
       missing_entries = [name for name in virtual_entries if name not in dir_entry_cache]
       if not missing_entries:
           skip_cache_lookup = True  # All entries in DirEntry cache
   ```

3. **Fast Listing Mode** (Lines ~621-634)
   ```python
   if fast_listing:  # > 500 files
       is_dir = de.is_dir(follow_symlinks=False)  # Don't stat, just is_dir
       # Use minimal attributes (timestamp = now, size = 0/4096)
   ```

4. **System Transform Map** (Lines ~413-420)
   ```python
   system_transform_map = self._build_system_transform_map(xfull_path)
   # Pre-build map once per directory instead of calling get_source_path() per file
   ```

5. **Extension Subdir Whitelist** (Lines ~306-350)
   ```python
   known_extension_subdirs = {'A52', 'BIN', 'ROM', 'TMP', 'CDT', 'CRT', 'CAS', 'TAP'}
   # Only scan for siblings if directory is in whitelist
   # Prevents expensive scanning for non-extension directories
   ```

---

## 6. Critical Code Locations

### Path Resolution
- `sourcepath.py:get_source_path()` - Lines 50-450
- `dirlisting.py:list_dynamic_map()` - Lines 420-790
- `transfs.py:_normalize_to_virtual_path()` - Lines 230-250

### Extension Subdirectory Merging
- `transfs.py:readdir()` extension detection - Lines 305-350
- `transfs.py:readdir()` sibling scanning - Lines 379-400
- `transfs.py:getattr()` fallback logic - Lines 664-735

### Caching
- `dirlisting.py:get_cached_listing()` - Lines 478-495
- `dirlisting.py:cache_listing()` - Lines 750-760
- Cache import/export in transfs.py - Lines referenced via imported functions

### Transform Execution
- `transforms.py:apply_transform()` - Main entry point
- `transfs.py:open()` transform check - Lines 1100-1150
- `post_process.py` - Tool implementations

### Performance Critical Sections
- `transfs.py:readdir()` - Lines 257-785 (entire function)
- `transfs.py:readdir()` source_paths building - Lines 424-518
- `transfs.py:readdir()` entry sending loop - Lines 522-765

---

## 7. Test Structure

### Test Files
```
tests/
├── conftest.py                    # Pytest fixtures
├── test_foundation.py             # Basic functionality
├── test_systems.py                # System-specific tests
├── test_snapshots.py              # Snapshot testing
└── test_performance.py            # Performance benchmarks
```

### Key Fixtures

```python
@pytest.fixture(scope="session")
def fuse_mount():
    """Returns /mnt/transfs path."""
    return Path("/mnt/transfs")

@pytest.fixture(scope="session")
def system_config(request):
    """SystemTestConfig with paths and thresholds."""
    return SystemTestConfig(
        system_name="Atari 5200",
        native_path=Path("/mnt/filestorefs/Native/Atari/5200"),
        transfs_path=Path("/mnt/transfs/MiSTer/Atari5200"),
        performance_thresholds=[...]
    )
```

### Performance Test Structure

```python
class TestSystemPerformance:
    @pytest.mark.performance(target_seconds=15.0)
    def test_directory_readdir_performance(self, system_config):
        """Verify directory listing meets performance targets."""
        # Emits structured output: PERF|test=...|op=readdir|actual=...|target=...
```

### Critical Test Cases

1. **Extension Subdirectory Merging**: Verify files from A52/, BIN/, ROM/ appear together
2. **Nested Directory Handling**: Files in A52/Prototype Games/ show correctly
3. **Dynamic Map Caching**: Verify cache hit/miss behavior
4. **Transform Pipeline**: Verify zip2zip and other transforms work
5. **Client Filtering**: Verify client-specific mappings work
6. **Performance Thresholds**: All directories meet < 15s listing time

---

## 8. Common Patterns

### Error Handling

```python
try:
    result = expensive_operation()
except OSError as e:
    logger.warning(f"Operation failed: {e}")
    return fallback_value
```

### Logging Levels

- `DEBUG`: Detailed execution flow (cache hits, path resolution)
- `INFO`: Key operations (READDIR START/COMPLETE, performance metrics)
- `WARNING`: Non-fatal issues (cache misses, slow operations)
- `ERROR`: Fatal errors (configuration issues, filesystem errors)

### Path Normalization

```python
# Always use forward slashes
path = path.replace('\\', '/')

# Remove trailing slashes
path = path.rstrip('/')

# Convert to absolute
path = os.path.abspath(path)
```

---

## 9. Known Issues & Workarounds

### Issue 1: Cache Invalidation
**Problem**: Getattr cache doesn't auto-invalidate on file changes  
**Workaround**: Periodic cache clears or manual deletion  
**Future**: Database with filesystem watchers

### Issue 2: Large Directory Performance
**Problem**: Initial scan of 3500+ files takes 2+ seconds  
**Workaround**: Cache warming, DirEntry cache, fast listing mode  
**Future**: Database with pre-indexed metadata

### Issue 3: Transform Size Estimation
**Problem**: Transform output size is estimated, not exact  
**Workaround**: Conservative estimates (1:1 ratio)  
**Future**: Database stores actual transformed sizes

### Issue 4: Dynamic Map Complexity
**Problem**: list_dynamic_map() has complex nested logic  
**Workaround**: Extensive logging and tests  
**Future**: Database queries replace dynamic generation

---

## 10. Database Migration Mapping

### Current → Database Equivalents

| Current Component | Database Equivalent | Notes |
|------------------|---------------------|-------|
| `os.scandir()` | `SELECT * FROM files WHERE virtual_path LIKE ?` | Query replaces scan |
| `dir_entry_cache` | SQLite page cache | Built into DB |
| Pickle cache files | Database tables | Persistent and queryable |
| `get_source_path()` | `virtual_mappings` table | Join queries |
| `list_dynamic_map()` | Dynamic SQL query | Path → WHERE clause |
| Extension name map | `metadata.extension` field | Indexed |
| Transform pipeline | `transforms` table | JSON or foreign key |
| Client filtering | WHERE clause with client_id | Add to queries |

### Data Access Layer Interface

```python
class FileDataProvider(ABC):
    """Abstract interface for both current and future systems."""
    
    @abstractmethod
    def list_directory(self, virtual_path: str, client_id: str = None) -> List[FileEntry]:
        """List files in virtual directory."""
        pass
    
    @abstractmethod
    def get_file_attributes(self, virtual_path: str) -> FileAttributes:
        """Get file stats and metadata."""
        pass
    
    @abstractmethod
    def resolve_source_path(self, virtual_path: str) -> Union[str, dict, tuple]:
        """Resolve virtual path to source path/transform."""
        pass
```

---

## 11. Configuration Hot-Reload Mechanism

**File**: `config.py`

```python
# Monitors config files for changes
def watch_config_changes(config_path: str):
    last_mtime = os.path.getmtime(config_path)
    
    while True:
        time.sleep(5)  # Check every 5 seconds
        current_mtime = os.path.getmtime(config_path)
        
        if current_mtime > last_mtime:
            logger.info("Config changed, reloading...")
            reload_config()
            last_mtime = current_mtime
```

**Affected by reload**:
- Virtual mappings
- Transform pipelines
- Client filtering rules
- Cache configuration

**Not affected**:
- Running FUSE operations (complete first)
- Open file handles
- Existing cache data

---

## 12. Client Filtering Details

### Configuration
```yaml
# clients.yaml
clients:
  - name: MiSTer
    ips: ["192.168.1.100"]
    hostnames: ["MiSTer"]
    mappings_override: mister

  - name: Zaparoo
    ips: ["192.168.1.200"]
    hostnames: ["zaparoo"]
    mappings_override: zaparoo
```

### Detection
```python
# In get_source_path()
client_ip = ctx.get('client_ip') if ctx else None
client = detect_client(client_ip, config.get('clients', []))
mappings_key = client.get('mappings_override', 'default')
```

### Usage
- Different clients see different virtual directory structures
- Same source files, different organization
- Example: MiSTer sees `/MiSTer/Atari5200/`, Zaparoo sees `/Zaparoo/Atari5200/`

---

## 13. ZIP Handling Modes

### Flat Mode (Default)
```
archive.zip:
  ├── game1.rom
  └── subdir/
      └── game2.rom

Mounted as: /archive.zip/game1.rom
            /archive.zip/game2.rom  (flattened)
```

### Hierarchical Mode
```
archive.zip → mounted as directory

/archive/:
  ├── game1.rom
  └── subdir/
      └── game2.rom
```

**Configuration**:
```python
def _get_zip_mode_for_path(self, path: str) -> str:
    # Returns 'flat' or 'hierarchical' based on config
```

---

## 14. Inode Management

### Synthetic Inodes
```python
def _make_synthetic_inode(self, path: str) -> int:
    """Generate inode from path hash."""
    return hash(path) & 0x7FFFFFFF  # 31-bit positive integer
```

### Inode→Path Mapping
```python
self._inode_path_map = {}  # inode → virtual_path

def _add_path(self, inode: int, path: str):
    self._inode_path_map[inode] = path

def _inode_to_path(self, inode: int) -> str:
    return self._inode_path_map.get(inode, "/")
```

**Note**: Database migration should consider using actual filesystem inodes where available

---

## 15. Logging Output Examples

### Successful readdir
```
2026-02-12 00:12:47 INFO transfs: READDIR START: path=/mnt/transfs/MiSTer/Amstrad/FDs start_id=0
2026-02-12 00:12:47 INFO transfs: CACHE HIT: /mnt/transfs/MiSTer/Amstrad/FDs (hits=1, misses=0)
2026-02-12 00:12:47 INFO transfs: READDIR BATCH: 3554 entries, transform_map=2 exts, get_source_path=0 calls, time=0.0115s skip_cache=True
2026-02-12 00:12:47 INFO transfs: READDIR COMPLETE: /mnt/transfs/MiSTer/Amstrad/FDs entries=3554 sent=22 cache_hits=0 hit_rate=0.0% parse=0.0089s batch=0.0115s total=0.3824s
```

### Extension subdir merge
```
2026-02-12 00:12:47 DEBUG transfs: READDIR: found extension subdirs to merge: ['BIN', 'ROM'] (relative_subpath=Prototype Games)
2026-02-12 00:12:47 DEBUG transfs: READDIR: adding game.bin from extension subdir
```

### Slow operation warning
```
2026-02-12 00:12:47 WARNING dirlisting: SLOW list_dynamic_map() took 2.50s, returned 3554 entries at path=/MiSTer/Amstrad/FDs
```

---

## Summary for Database Migration

When implementing database phases, refer to this document for:

1. **Integration points**: Where to inject DatabaseProvider vs PickleCacheProvider
2. **Query equivalents**: Map readdir logic to SQL queries
3. **Performance targets**: Match or exceed current benchmarks
4. **Feature parity**: Ensure all flows (extension merge, transforms, client filtering) work
5. **Test coverage**: Replicate existing test structure with database backend

**Critical**: The Data Access Layer abstraction in section 10 is the key to parallel development. Implement it first in Phase 1.
