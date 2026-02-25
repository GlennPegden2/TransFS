# MAME Downloader Configuration Status

## Issue Summary

The MAME Software List downloader was reporting "network error" but the actual issue was a **configuration problem**, not a network issue.

## Root Causes Identified

### 1. **Overly Aggressive Filter** ✓ FIXED
**Problem:** The `exclude_unsupported: true` filter in `Atom.yaml` was filtering out ALL 44 software entries.

**Why:** In MAME hash files, `supported="no"` refers to whether the software is fully emulated in MAME itself, not whether files are available for download. All Atom cassette entries are marked `supported="no"` because MAME's Atom emulation is incomplete.

**Fix:** Changed to `exclude_unsupported: false` in `app/config/sources/default/Acorn/Atom.yaml`

**Result:** Filter now allows all 44 entries through

### 2. **Incorrect Archive URL** ⚠️ NEEDS CONFIGURATION
**Problem:** The `archive_base_url` points to a MAME ROM collection, not a Software List collection.

**Current URL:**
```
https://archive.org/download/mame-merged/mame-merged
```

**Issue:** This URL may not contain the Software List files referenced in hash files like:
- `747(bugbyte).hq.uef`
- `adventure(programpower).hq.uef`
- etc.

All downloads are failing with **404 Not Found** errors.

## What Works

✅ Network connectivity is fine (container can reach GitHub and Internet Archive)
✅ Hash file fetching works (atom_cass.xml downloaded and parsed successfully)
✅ Hash file parsing works (44 entries extracted)
✅ Filter logic works (when set to `false`, all 44 entries pass through)
✅ Pack installation flow works (MAME sources detected and processed correctly)

## What Needs Fixing

❌ **Archive URL must point to correct Internet Archive collection**

The files referenced in MAME hash files are in a specific Internet Archive collection. You need to:

1. **Find the correct Internet Archive collection:**
   - Search archive.org for: "MAME Software List"
   - Look for collections containing `.uef` files (Acorn tape images)
   - Example search: https://archive.org/search?query=mame%20software%20list

2. **Update the archive_base_url in app.yaml:**
   ```yaml
   mame:
     archive_base_url: https://archive.org/download/COLLECTION_NAME/ARCHIVE_NAME
   ```

3. **URL Format:**
   Internet Archive allows accessing files inside ZIP archives using:
   ```
   https://archive.org/download/collection/archive.zip/filename
   ```
   
   Your downloader will append filenames to the base URL.

## Testing

To test the MAME downloader after updating the URL:

```bash
# Copy test script to container
docker cp test_mame_no_filter.py transfs:/tmp/test.py

# Run test
docker exec transfs python /tmp/test.py
```

Successful output should show:
```
Downloaded: N (where N > 0)
Failed: 0
```

Instead of all failures.

## Alternative Solutions

If you can't find the correct Internet Archive collection:

### Option 1: Disable Checksum Verification
In `app.yaml`:
```yaml
mame:
  verify_checksums: false
```

This allows downloads from any source URL you configure, but won't verify file integrity.

### Option 2: Use Local Files
Point `archive_base_url` to a local file server or directory where you've already downloaded the MAME Software List files.

### Option 3: Manual Download
1. Download files manually from MAME sites
2. Place in `/mnt/filestorefs/Downloads/MAME/Software/MAME/Cassettes/`
3. Files will be detected as "already existed" and skipped in future downloads

## Next Steps

1. Find the correct Internet Archive collection URL for MAME Software Lists
2. Update `app.yaml` with the correct `archive_base_url`
3. Rebuild container: `docker compose restart transfs`
4. Test pack installation again
5. Verify files appear in `/mnt/transfs/RetroBat/Atom/Software/MAME/Cassettes/`

## Additional Notes

- The MAME downloader caches hash files in `/app/config/mame_cache/`
- Hash files are only fetched once, then cached locally
- To force refetch, delete cached files: `rm -rf /app/config/mame_cache/*.xml`
- Downloaded files go to: `/mnt/filestorefs/Downloads/MAME/Software/MAME/Cassettes/`
