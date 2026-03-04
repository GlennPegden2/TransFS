# Split-Path Native Bypass Architecture

## Overview

TransFS now supports **dual access patterns** through a single SMB share. Users can access the same content through two different paths with fundamentally different characteristics:

| Path | Layer | Use Case | Performance | Features |
|------|-------|----------|-------------|----------|
| `TransFS/` | FUSE Virtual FS | Normal browsing, file access | Metadata-cached | Transforms, filtering, virtual structures |
| `TransFS/Native/` | Direct Filesystem | Bulk import/export/delete | Direct FS speed | No virtual layer, no transforms |

## Technical Architecture

### Kernel Bind Mount

The implementation uses a **recursive kernel bind mount** that connects `/mnt/transfs/Native` directly to the physical `/mnt/filestorefs/Native` directory:

```
SMB Client Request → Samba → /mnt/transfs/Native/*
                                    ↓ (Kernel VFS interception)
                      /mnt/filestorefs/Native/* (Physical filesystem)
                      
                    ✗ FUSE daemon NOT involved
                    ✗ No virtual layer processing
                    ✓ Direct kernel filesystem operations
```

**Key advantage**: The kernel's Virtual Filesystem layer intercepts operations at `/mnt/transfs/Native` and routes them directly to the physical filesystem, completely bypassing the FUSE daemon. This is different from a symbolic link—it's a low-level filesystem redirect.

### Mount Configuration

In `docker-compose.yml`, the entrypoint creates this mount after FUSE initialization:

```bash
mount --rbind /mnt/filestorefs/Native /mnt/transfs/Native
```

The `--rbind` flag means "recursive bind mount"—all subdirectories and submounts are included.

## Usage Guidelines

### Discoverable Through SMB Browse

When clients browse the TransFS SMB share, they see:

```
TransFS/
  ├── Generic/
  ├── Mame/
  ├── MiSTer/
  ├── RetroBat/
  ├── RetroPie/
  └── Native/  ← New top-level directory
      ├── Clients/
      └── Systems/
```

**Native** appears as a discoverable folder alongside the virtual system hierarchies, making it obvious to users that it's available.

### When to Use Each Path

**Use `TransFS/` (FUSE Layer)**:
- ✓ Browsing content in RetroBat/MiSTer/RetroPie virtual hierarchies
- ✓ Accessing transformed/filtered views of content
- ✓ Normal file reads and occasional file writes
- ✓ Accessing virtual collections and metadata-based organization
- ✓ When you need transform processing (ZIP extraction, ROM renaming, etc.)

**Use `TransFS/Native/` (Direct Bypass)**:
- ✓ Bulk importing large amounts of new content (thousands of files)
- ✓ Bulk deleting or cleaning up entire directories
- ✓ Direct access to raw ROM files by system/folder structure
- ✓ When performance is critical and transforms aren't needed
- ✓ Administrative/maintenance operations
- ✓ Backup/restore operations on the physical filestore

### Performance Expectations

**Bulk Import (1000+ files)**:
- `TransFS/` (FUSE): ~500ms-2s per file (metadata processing, cache updates)
- `TransFS/Native/` (Direct): ~50-100ms per file (direct filesystem calls)
- **Expected improvement**: 5-10x faster for bulk operations

**Bulk Delete (1000+ files)**:
- `TransFS/` (FUSE): Risk of operation stalls during metadata sync
- `TransFS/Native/` (Direct): Consistent, predictable performance
- **Expected improvement**: Eliminates stalls, 3-5x faster

### Important Limitations

⚠️ **Database Sync Lag**
- Changes made via `TransFS/Native/` are NOT immediately visible in `TransFS/`
- Changes appear after the next database sync cycle (default: ~5-10 minutes)
- For fast feedback, trigger a manual sync via the API or restart the metadata scanner

⚠️ **No Virtual Transforms**
- Files accessed via `TransFS/Native/` appear in their raw physical state
- No ROM transforms, no ZIP extraction, no virtual directory rewriting
- You see exactly what's on disk

⚠️ **Concurrent Access**
- Accessing the same file simultaneously through both paths is not recommended
- The kernel will handle basic locking, but metadata consistency isn't guaranteed until sync
- For safe concurrent operations, use only one path at a time

⚠️ **No Symlinks Between Paths**
- Do not create symlinks from `/mnt/transfs/Native/` back to `/mnt/transfs/`
- Circular references could cause client access issues
- Keep the two paths completely separate

## Practical Examples

### Example 1: Adding New Retro Systems Content

**Scenario**: You have 5GB of new Atari800 ROMs to import.

```
1. Via Explorer: \\server\TransFS\Native\Systems\Atari
2. Copy 5GB of ROM files into subdirectories
3. Wait for database sync (~5-10 min)
4. Files now appear in \\server\TransFS\Atari (virtual view)
5. Benefit: Copy operation runs at native network speed, no FUSE overhead
```

### Example 2: Cleaning Up Corrupted Files

**Scenario**: Previous import left 200 corrupted files mixed throughout the collection.

```
1. Via Explorer or script: \\server\TransFS\Native\Systems\Acorn\
2. Delete corrupted files using Native path directly
3. No stalls, operations complete in seconds
4. Database sync removes references from virtual views
5. Benefit: Fast, predictable cleanup without FUSE bottlenecks
```

### Example 3: Backup/Restore

**Scenario**: Backing up the entire physical filestore.

```
Backup:
$ tar czf archive.tar.gz /mnt/transfs/Native/

Restore:
$ tar xzf archive.tar.gz -C /mnt/transfs/Native/
(Then trigger database sync)

Benefit: Direct filesystem speed, no virtual layer processing
```

## Monitoring Database Sync Status

To see when changes become visible in the FUSE view:

```bash
# Check last sync time
curl http://localhost:8000/api/sync/status

# Manually trigger sync (if exposed)
curl -X POST http://localhost:8000/api/sync/trigger
```

## Troubleshooting

### Changes Made via Native Not Visible in FUSE

**Cause**: Database hasn't synced yet  
**Solution**: Wait for next sync cycle, or trigger manual sync

### Files Appear in Both Paths with Different Timestamps

**Cause**: Metadata cache hasn't been invalidated  
**Solution**: This is normal after bulk Native operations—database sync will reconcile

### Performance Still Slow on Native Path

**Likely causes**:
1. Network bottleneck (SMB/NIC limited)
2. Disk I/O bound (USB drive, slow NAS)
3. Antivirus scanning files during copy

**Verification**:
```bash
# Direct network throughput test
iperf3 -c <server>

# Direct disk speed test
dd if=/dev/zero of=/mnt/transfs/Native/test.bin bs=1M count=1000
```

## Architecture Decision Rationale

### Why Not Just Use Direct Access?

The FUSE layer (`TransFS/`) provides value for:
- **Transform Processing**: Extracting archived content, filtering results
- **Metadata Caching**: Fast browsing of large collections
- **Virtual Organization**: RetroBat/MiSTer/RetroPie hierarchies
- **Unified Access**: Single hierarchy for diverse content sources

### Why Not Make Everything Go Through FUSE?

FUSE introduces O(N) overhead for N files:
- Each file operation triggers LOOKUP, GETATTR, and potentially READDIR on parent
- Serialization of metadata for logging/processing
- Database queries for virtual structure resolution
- For bulk operations (thousands of files), this becomes prohibitive

### The Hybrid Model

By offering **both paths**, users get:
- ✓ Normal browsing: FUSE's smart transforms and caching
- ✓ Bulk operations: Direct filesystem's raw speed
- ✓ Single share: No client configuration needed, just pick the right path

## Future Enhancements

- [ ] HTTP upload API that accepts bulk ZIP files and imports to Native path
- [ ] Automatic sync trigger on Native path modifications (inotify-based)
- [ ] Native path performance metrics in monitoring dashboard
- [ ] Configurable sync interval per directory
- [ ] Selective sync for specific subdirectories

## Summary

The split-path architecture gives you the best of both worlds:
- **FUSE path** (`TransFS/`) for sophisticated virtual filesystem features
- **Native path** (`TransFS/Native/`) for raw, fast bulk operations
- **Single SMB share** for unified client access
- **Kernel-level bypass** that's transparent and efficient

Choose the path that matches your workload. For bulk operations, Native is always the right choice.
