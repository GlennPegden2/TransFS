# pyfuse3 Migration Implementation Guide

**Date Started**: 2026-01-04  
**Goal**: Migrate from fusepy to pyfuse3 to eliminate 38s Python yield loop overhead  
**Expected Performance**: 42s → 2-5s for ls -al on 3,537 files (94-96% improvement)  
**Estimated Effort**: 2-3 weeks  

---

## Current State Analysis

### Existing Architecture
- **FUSE Library**: fusepy (synchronous, libfuse 2, unmaintained)
- **Files to Modify**:
  - `app/transfs.py` (617 lines) - Main filesystem with virtual path translation
  - `app/passthroughfs.py` (153 lines) - Base passthrough operations
  - `app/dirlisting.py` (658 lines) - Caching layer (minimal changes needed)
- **FUSE Operations**: 20+ implemented (getattr, readdir, open, read, write, etc.)
- **Current Performance**: 42s for ls -al (readdir: instant cached, getattr: 1.65s, yield loop: 38s)

### Performance Bottleneck Identified
```
parse_trans_path()           <0.01s   ✓ Fast
getattr() × 3,537 (cached)    1.65s   ✓ Fast
Python FUSE yield loop       38.00s   ✗ BOTTLENECK
─────────────────────────────────────
Total                        42.00s
```

### Target Architecture
- **FUSE Library**: pyfuse3 (async, libfuse 3, actively maintained)
- **Async Framework**: Trio (recommended - better tested with pyfuse3)
- **Key Benefits**:
  - C-level iteration (eliminates 38s overhead)
  - readdirplus() support (single call for entries + attributes)
  - Native async I/O for better concurrency

---

## Migration Steps

### Phase 1: Setup & Dependencies (1-2 days)

#### Step 1.1: Create Migration Branch
```bash
git checkout -b feature/pyfuse3-migration
```

#### Step 1.2: Update Dependencies
**File**: `requirements.txt`
```diff
- fusepy
+ pyfuse3>=3.2.0
+ trio>=0.22.0
```

**Action**: Update requirements and test installation
```bash
docker exec transfs pip install pyfuse3 trio
```

#### Step 1.3: Create Backup Points
- Tag current working version: `git tag v1.0-fusepy-baseline`
- Document current performance metrics (test_performance.py results)

---

### Phase 2: Base Class Rewrite (3-4 days)

#### Step 2.1: Create New Passthrough Base Class

**File**: `app/passthroughfs_pyfuse3.py` (NEW FILE)

**Implementation Checklist**:
- [ ] Import pyfuse3 and Trio
- [ ] Create inode management system
  - [ ] `_inode_path_map: Dict[InodeT, Union[str, Set[str]]]` - Track inode → path(s)
  - [ ] `_lookup_cnt: Dict[InodeT, int]` - Reference counting
  - [ ] `_fd_inode_map: Dict[int, InodeT]` - File descriptor → inode
  - [ ] `_inode_fd_map: Dict[InodeT, int]` - Inode → file descriptor
  - [ ] `_fd_open_count: Dict[int, int]` - Track open file handles
- [ ] Implement core inode helpers
  - [ ] `_inode_to_path(inode: InodeT) -> str`
  - [ ] `_add_path(inode: InodeT, path: str)`
  - [ ] `_forget_path(inode: InodeT, path: str)`
- [ ] Convert all FUSE operations to async

**API Mapping Reference**:

| fusepy (Sync) | pyfuse3 (Async) | Changes Required |
|---------------|-----------------|------------------|
| `def getattr(self, path, fh=None)` | `async def getattr(self, inode, ctx=None)` | Add `async`, path→inode, add ctx |
| `def readdir(self, path, fh)` | `async def readdir(self, fh, start_id, token)` | Add `async`, generator→token callback |
| `def open(self, path, flags)` | `async def open(self, inode, flags, ctx)` | Add `async`, path→inode, return FileInfo |
| `def read(self, path, size, offset, fh)` | `async def read(self, fh, off, size)` | Add `async`, reorder params |
| `def write(self, path, data, offset, fh)` | `async def write(self, fh, off, buf)` | Add `async`, reorder params |
| All operations | All operations | Add `ctx: RequestContext` parameter |

**Key Operations to Implement** (Priority Order):
1. ✓ `init()` - Initialize inode system (ROOT_INODE = source dir)
2. ✓ `lookup(parent_inode, name, ctx)` - Path lookup with inode management
3. ✓ `forget(inode_list)` - Reference count management
4. ✓ `getattr(inode, ctx)` - Get file attributes by inode
5. ✓ `readdir(fh, start_id, token)` - Token-based directory listing
6. ✓ `open(inode, flags, ctx)` - Open file, return FileInfo
7. ✓ `read(fh, off, size)` - Read file data
8. ✓ `write(fh, off, buf)` - Write file data
9. ✓ `create(parent_inode, name, mode, flags, ctx)` - Create file
10. ✓ `unlink(parent_inode, name, ctx)` - Delete file
11. ✓ `mkdir(parent_inode, name, mode, ctx)` - Create directory
12. ✓ `rmdir(parent_inode, name, ctx)` - Delete directory
13. ✓ `rename(parent_old, name_old, parent_new, name_new, flags, ctx)` - Move/rename

**Reference Implementation**: See pyfuse3 examples/passthroughfs.py

#### Step 2.2: Test Base Class Independently
```python
# tests/test_passthroughfs_pyfuse3.py
import trio
import pyfuse3
from app.passthroughfs_pyfuse3 import Passthrough

async def test_basic_operations():
    fs = Passthrough("/tmp/test_source")
    # Test lookup, getattr, readdir
    ...
```

---

### Phase 3: TransFS Conversion (5-7 days)

#### Step 3.1: Convert TransFS Class to Async

**File**: `app/transfs_pyfuse3.py` (NEW FILE initially, then replace transfs.py)

**Conversion Checklist**:
- [ ] Inherit from `Passthrough` (pyfuse3 version)
- [ ] Add `async` to all overridden methods
- [ ] Convert readdir() implementation:
  ```python
  # OLD (fusepy - generator):
  def readdir(self, path: str, fh: int):
      for entry in entries:
          yield entry
  
  # NEW (pyfuse3 - token callback):
  async def readdir(self, fh: int, start_id: int, token):
      for idx, entry in enumerate(entries):
          if idx < start_id:
              continue
          attr = await self.getattr(entry.inode)
          if not pyfuse3.readdir_reply(token, entry.name, attr, idx + 1):
              break  # Client buffer full
  ```

- [ ] Convert getattr() to use inodes:
  ```python
  # OLD: def getattr(self, path: str, fh: int)
  # NEW: async def getattr(self, inode: InodeT, ctx)
  async def getattr(self, inode, ctx=None):
      path = self._inode_to_path(inode)
      # Rest of logic stays similar but with await
      ...
  ```

- [ ] Add `await` to all blocking operations:
  - File I/O: `os.stat()` → `await trio.to_thread.run_sync(os.stat, ...)`
  - Parse operations: `parse_trans_path()` → May need async version
  - Cache operations: Already sync, minimal changes

#### Step 3.2: Handle Virtual Path Translation

**Critical**: TransFS does dynamic path translation. Need to ensure:
- [ ] `parse_trans_path()` works with inode-based paths
- [ ] Virtual directory entries get proper inode assignment
- [ ] Zip file handling maintains inode consistency

**Approach**:
```python
async def lookup(self, parent_inode, name, ctx=None):
    parent_path = self._inode_to_path(parent_inode)
    
    # Check if this is a virtual path that needs translation
    if is_virtual_path(parent_path):
        real_path = map_virtual_to_real(parent_path, name)
    else:
        real_path = os.path.join(parent_path, name)
    
    # Get attributes and assign inode
    stat = await trio.to_thread.run_sync(os.lstat, real_path)
    inode = stat.st_ino
    self._add_path(inode, real_path)
    return await self.getattr(inode)
```

#### Step 3.3: Preserve Cache Integration

**File**: `app/dirlisting.py`

**Minimal Changes Required**:
- Cache functions are synchronous and file-based (pickle)
- Can be called from async code with `await trio.to_thread.run_sync()` if needed
- Current implementation should work as-is for most operations

**Areas to Review**:
- [ ] Ensure cache operations don't block async event loop excessively
- [ ] Consider async-friendly cache backend (not critical for v1)

---

### Phase 4: Main Entry Point Rewrite (1-2 days)

#### Step 4.1: Convert main() Function

**File**: `app/transfs_pyfuse3.py`

**OLD (fusepy)**:
```python
def main(mount_path: str, root_path: str):
    FUSE(
        TransFS(root_path=root_path),
        mount_path,
        nothreads=True,
        foreground=True,
        debug=False,
        encoding='utf-8',
        allow_other=True,
        direct_io=True
    )
```

**NEW (pyfuse3)**:
```python
async def main_async(mount_path: str, root_path: str):
    fs = TransFS(root_path=root_path)
    
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=transfs')
    fuse_options.add('allow_other')
    fuse_options.discard('default_permissions')
    
    pyfuse3.init(fs, mount_path, fuse_options)
    
    try:
        await pyfuse3.main()
    finally:
        pyfuse3.close(unmount=True)

def main(mount_path: str, root_path: str):
    """Entry point - runs async main with Trio."""
    trio.run(main_async, mount_path, root_path)
```

#### Step 4.2: Update Dockerfile Entry Point

**File**: `Dockerfile`

**Check if changes needed** - likely minimal since we're keeping the same entry point function signature.

---

### Phase 5: Testing & Validation (3-5 days)

#### Step 5.1: Convert Test Suite to Async

**File**: `tests/conftest.py`

**Add Trio pytest plugin**:
```python
import pytest
import trio

pytest_plugins = ['pytest_trio']
```

**Update requirements-dev.txt**:
```
pytest-trio>=0.8.0
```

#### Step 5.2: Update Performance Tests

**File**: `tests/test_performance.py`

**Convert to async**:
```python
@pytest.mark.trio
async def test_large_directory_listing(mount_path):
    start = time.time()
    # Test readdir performance
    entries = await trio.to_thread.run_sync(os.listdir, large_dir_path)
    elapsed = time.time() - start
    
    assert elapsed < 5.0, f"readdir took {elapsed:.1f}s (target: <5s)"
```

**Performance Targets**:
- Small directory (<100 files): <0.5s
- Large directory (3,537 files): <5s (down from 42s)
- ls -al simulation: <5s (down from 42s)
- Cache hit: <0.1s

#### Step 5.3: Functional Test Checklist

**Critical Operations to Verify**:
- [ ] Browse native directories
- [ ] Browse virtual directories with path translation
- [ ] Open and read files
- [ ] Open and read files inside zip archives
- [ ] Write/create files (if supported)
- [ ] Rename/move files
- [ ] Delete files
- [ ] Directory creation
- [ ] Cache persistence across operations
- [ ] SMB access (via Docker container)
- [ ] Web UI browsing

#### Step 5.4: Run Existing Snapshot Tests

```bash
docker exec transfs bash -c "cd /tests && python -m pytest test_filesystem_snapshots.py -v"
```

**Expected**: All snapshots should match (file structure unchanged)

---

### Phase 6: Integration & Deployment (2-3 days)

#### Step 6.1: Replace Old Implementation

Once testing passes:
```bash
# Backup old files
git mv app/passthroughfs.py app/passthroughfs_fusepy.py.bak
git mv app/transfs.py app/transfs_fusepy.py.bak

# Promote new files
git mv app/passthroughfs_pyfuse3.py app/passthroughfs.py
git mv app/transfs_pyfuse3.py app/transfs.py
```

#### Step 6.2: Update Docker Build

**File**: `Dockerfile`

Ensure pyfuse3 and Trio are installed:
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
```

#### Step 6.3: Rebuild and Test Container

```bash
docker-compose down
docker-compose up --build -d
docker logs -f transfs  # Monitor startup

# Test from outside
ls -al /path/to/mount/Native/Amstrad/CPC/Software/Collections/
```

#### Step 6.4: Performance Validation

Run full performance test suite:
```bash
docker exec transfs bash -c "cd /tests && python -m pytest test_performance.py -v"
```

**Success Criteria**:
- ✓ All tests pass
- ✓ Large directory ls -al: <5s (down from 42s)
- ✓ No regressions in functionality
- ✓ SMB clients can browse without timeouts

---

## Code Transformation Rules

### Rule 1: Path-Based → Inode-Based Operations

**Pattern**: Every operation that receives a `path` must be converted to receive an `inode`.

**Transformation**:
```python
# BEFORE (fusepy)
def operation(self, path: str, ...):
    full_path = os.path.join(self.root, path.lstrip('/'))
    # Use full_path...

# AFTER (pyfuse3)
async def operation(self, inode: InodeT, ctx, ...):
    path = self._inode_to_path(inode)
    # Use path...
```

### Rule 2: Generator → Token Callback (readdir)

**Pattern**: `readdir()` changes from generator to token-based callback.

**Transformation**:
```python
# BEFORE (fusepy)
def readdir(self, path: str, fh: int):
    for entry in get_entries(path):
        yield entry

# AFTER (pyfuse3)
async def readdir(self, fh: FileHandleT, start_id: int, token):
    path = self._inode_to_path(fh)  # Use fh as inode for simplicity
    entries = get_entries(path)
    
    for idx, entry in enumerate(entries):
        if idx < start_id:
            continue
        attr = await self.getattr(entry.inode)
        if not pyfuse3.readdir_reply(token, entry.name, attr, idx + 1):
            break  # Buffer full, stop sending
```

### Rule 3: Add async/await

**Pattern**: All operations become async, blocking calls need await.

**Transformation**:
```python
# BEFORE (fusepy)
def read(self, path, size, offset, fh):
    os.lseek(fh, offset, os.SEEK_SET)
    return os.read(fh, size)

# AFTER (pyfuse3)
async def read(self, fh, off, size):
    # os operations are fast enough to run inline, but can wrap if needed:
    return await trio.to_thread.run_sync(
        lambda: os.pread(fh, size, off)
    )
```

### Rule 4: Return Type Changes

**Pattern**: Some operations return different types in pyfuse3.

**Key Changes**:
- `open()`: Returns `FileInfo` object (not just file handle)
- `create()`: Returns `(FileInfo, EntryAttributes)` tuple
- `getattr()`: Returns `EntryAttributes` (not raw stat)

### Rule 5: Context Parameter

**Pattern**: All operations receive `ctx: RequestContext` with user info.

**Usage**:
```python
async def create(self, parent_inode, name, mode, flags, ctx):
    # Use ctx.uid, ctx.gid for ownership
    os.chown(path, ctx.uid, ctx.gid)
```

---

## Rollback Plan

### If Migration Fails

**Quick Rollback**:
```bash
git checkout main
docker-compose up --build -d
```

**Partial Rollback** (keep new code but use old):
```bash
git mv app/passthroughfs_fusepy.py.bak app/passthroughfs.py
git mv app/transfs_fusepy.py.bak app/transfs.py
# Revert requirements.txt to fusepy
docker-compose up --build -d
```

### Known Risk Points

1. **Inode Lifecycle Management**
   - Risk: Memory leaks if reference counting is wrong
   - Mitigation: Extensive testing with file creation/deletion cycles

2. **Virtual Path Translation**
   - Risk: Inode mapping breaks for dynamic virtual paths
   - Mitigation: Keep detailed path→inode debug logging

3. **Zip File Handling**
   - Risk: Files inside zips don't get stable inodes
   - Mitigation: Hash-based inode generation for zip contents

4. **Performance Regression**
   - Risk: Async overhead or poor inode map performance
   - Mitigation: Keep fusepy version as fallback, benchmark both

---

## Progress Tracking

### Current Status: **PHASE 4 - DEBUGGING**

- [x] Phase 1: Setup & Dependencies (Est: 1-2 days) - **COMPLETED**
  - [x] 1.1: Create migration branch
  - [x] 1.2: Update dependencies (pyfuse3, trio, pytest-trio)
  - [x] 1.3: Create backup points (v1.0-fusepy-baseline tag)

- [x] Phase 2: Base Class Rewrite (Est: 3-4 days) - **COMPLETED**
  - [x] 2.1: Create passthroughfs_pyfuse3.py with async operations
  - [x] 2.2: Implemented inode management system

- [x] Phase 3: TransFS Conversion (Est: 5-7 days) - **COMPLETED**
  - [x] 3.1: Convert TransFS class to async
  - [x] 3.2: Handle virtual path translation
  - [x] 3.3: Preserve cache integration

- [x] Phase 4: File Swap & Integration (Est: 1-2 days) - **IN PROGRESS - DEBUGGING**
  - [x] 4.1: Swapped files (fusepy → pyfuse3 versions)
  - [x] 4.2: Container builds and TransFS mounts successfully
  - [⚠️] 4.3: **ISSUE FOUND**: Virtual path lookup failing for nested paths
    - **Symptom**: `/mnt/transfs/MiSTer/Amstrad/` works but `/mnt/transfs/MiSTer/Amstrad/CPC/` fails
    - **Root Cause**: lookup() method needs debugging - inode generation or path mapping issue
    - **Next Steps**: 
      1. Add extensive debug logging to lookup() method
      2. Verify inode generation for virtual paths (hash collision?)
      3. Check _add_path() is being called correctly
      4. Test if parent lookups are succeeding before child lookups

- [ ] Phase 5: Testing & Validation (Est: 3-5 days)
  - [ ] 5.1: Convert test suite to async
  - [ ] 5.2: Update performance tests
  - [ ] 5.3: Run functional tests
  - [ ] 5.4: Run snapshot tests

- [ ] Phase 6: Deployment (Est: 2-3 days)
  - [ ] 6.1: Final validation
  - [ ] 6.2: Performance benchmarks vs fusepy baseline
  - [ ] 6.3: Merge to main branch

**Total Time So Far**: ~6 hours (faster than estimated!)  
**Current Blocker**: Virtual path lookup issue in nested directories

---

## Key Resources

### Documentation
- pyfuse3 API: https://pyfuse3.readthedocs.io/
- pyfuse3 GitHub: https://github.com/libfuse/pyfuse3
- Trio Tutorial: https://trio.readthedocs.io/

### Example Code
- pyfuse3 examples/passthroughfs.py - Main reference
- pyfuse3 examples/tmpfs.py - In-memory filesystem example
- pyfuse3 examples/hello_asyncio.py - Asyncio variant (use Trio instead)

### Internal References
- Current implementation: `app/transfs.py` (fusepy version)
- Cache system: `app/dirlisting.py`
- Performance tests: `tests/test_performance.py`
- Performance baseline: 42s for 3,537 files (ls -al)

---

## Notes for Future Implementation

### When Resuming Work

1. **Check Current Phase**: Look at "Progress Tracking" section above
2. **Review Last Changes**: `git log --oneline -20`
3. **Verify Environment**: `pip list | grep -E "pyfuse3|trio|fusepy"`
4. **Run Tests**: Ensure baseline still works before continuing
5. **Read Context**: Review the specific phase's checklist

### Critical Decision Points

**Decision 1: Trio vs asyncio**
- **Recommendation**: Use Trio (better tested with pyfuse3)
- **Alternative**: asyncio if team has existing expertise
- **Documented in**: Phase 1.2

**Decision 2: Inode Generation for Virtual Paths**
- **Challenge**: Virtual paths don't have real inodes
- **Options**: 
  - A) Hash path to create synthetic inode
  - B) Sequential counter (must persist across restarts)
  - C) Combination approach
- **Recommendation**: Hash-based (deterministic, no state)

**Decision 3: readdirplus() Implementation**
- **Benefit**: Single call returns entries + attributes (huge performance win)
- **Complexity**: Higher implementation effort
- **Recommendation**: Implement in Phase 3 after basic readdir() works

### Performance Expectations

**Conservative Targets** (for validation):
- Small dir (<100 files): <1s
- Medium dir (500 files): <2s  
- Large dir (3,537 files): <5s
- ls -al: <5s

**Stretch Goals** (with readdirplus()):
- Large dir: <2s
- ls -al: <2s

**If Performance Worse**: Check these:
1. Inode map lookup efficiency (should be O(1))
2. Unnecessary await overhead (profile with trio-guest-run)
3. Cache integration broken (check hit rates)

---

## End of Document

**Last Updated**: 2026-01-04  
**Status**: Ready to Begin Phase 1  
**Next Action**: Create migration branch and update dependencies
