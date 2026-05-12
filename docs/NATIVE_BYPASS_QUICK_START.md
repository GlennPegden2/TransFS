# Native Bypass Quick Reference

## One-Minute Summary

**Two ways to access your content via the same SMB share:**

Native is a **discoverable top-level folder** alongside other emulator systems:

```
\\server\TransFS\
  ├── Generic/              (Virtual hierarchies)
  ├── Mame/                 (with transforms, filtering)
  ├── MiSTer/               
  ├── RetroBat/
  ├── RetroPie/
  └── Native/               ← Direct filesystem (bulk operations)
         ├── Clients/          (Client-specific assets)
         │   └── RetroBat/
         │       └── bios/
         └── Systems/          (Shared system content)
               ├── Acorn/
               ├── Amstrad/
               ├── Apple/
               └── Atari/
```

| Need | Use Path | Speed | Notes |
|------|----------|-------|-------|
| Browse RetroBat/MiSTer hierarchies | `\\server\TransFS\Generic\`, etc. | Cached | Virtual transforms, filtered views |
| **Bulk add/delete thousands of files** | **`\\server\TransFS\Native\`** | **6-15ms/file** | **Direct filesystem, no FUSE overhead** |

## Usage Examples

### ✅ Import 5GB of ROMs

```
1. Open: \\server\TransFS\Native\Systems\Atari\
2. Paste your ROM files
3. Wait ~5-10 min for sync
4. Files appear in \\server\TransFS\Atari\
```

**Why Native?** Copy runs at full network/disk speed, not FUSE-limited.

### ✅ Clean Up Corrupted Files

```
1. Navigate to: \\server\TransFS\Native\Systems\[Manufacturer]\[System]\
2. Delete unwanted files (will complete in seconds)
3. Wait for sync
4. Files removed from virtual views
```

**Why Native?** No deletion stalls, predictable performance.

### ❌ Don't Do This

```
❌ Create files directly in \\server\TransFS\ (not Native)
   → Writes are slow and not recommended through virtual layer

❌ Create symlinks between Native and virtual paths
   → Circular reference risk, keep paths separate

❌ Edit files simultaneously on both paths
   → Can cause metadata inconsistency until sync
```

## Performance Expectations

**Test: 500 files via Native path**
- Copy: 7.5 sec total = **15ms per file**
- Delete: 3.0 sec total = **6ms per file**
- 1000 files = **~10 seconds total**

**Why so fast?**
- Direct kernel filesystem calls
- No virtual layer processing
- No FUSE daemon involvement
- No metadata serialization overhead

## Architectural Choice

**Before**: Single FUSE path → metadata overhead on bulk operations → stalls on large deletes

**Now**: 
- FUSE path for smart browsing (caching, transforms)
- Native path for fast bulk operations (bypass everything)
- Both in one share—pick the right tool for the job

## When Database Changes Appear

Changes made via **Native path** become visible in **virtual path** after:
- **Automatic**: 5-10 minutes (default sync cycle)
- **Manual**: API trigger or restart metadata scanner

```bash
# Check sync status
curl http://localhost:8000/api/sync/status

# Trigger immediate sync (if API supports it)
curl -X POST http://localhost:8000/api/sync/trigger
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Files added via Native not in virtual path | Sync lag | Wait or trigger manual sync |
| Can't write to `\\server\TransFS\` (non-Native) | Expected | Use `\\server\TransFS\Native\Systems\...` for system content |
| Slow bulk operations | Using virtual path | Switch to `\\server\TransFS\Native\` |
| Permission denied on Native path | SMB permissions | Check samba share settings |

---

**Bottom line**: For bulk operations, Native is always faster. For browsing and virtual transforms, use the regular FUSE path.
