# Multiple URLs per Source Feature

## Overview

TransFS now supports downloading multiple files from a single source definition, with flexible per-URL configuration options. This feature is particularly useful for:

- Multi-part archive collections from the same site
- Regional BIOS files from different sources
- Large collections split across multiple download links
- Combining files from different locations into one system

## Backward Compatibility

✅ **All existing single-URL configurations continue to work without modification.**

## Configuration Options

### Option 1: Legacy Single URL (unchanged)
```yaml
- name: Single ROM Collection
  type: ddl
  url: https://example.com/roms.zip
  folder: ROMs
  extract_from_archive:
    - specific.rom
```

### Option 2: Simple URL List
All URLs share the same source-level settings (folder, extract_from_archive, etc.)

```yaml
- name: Three-Part Collection
  type: ddl
  urls:  # Changed from 'url' to 'urls'
    - https://example.com/part1.zip
    - https://example.com/part2.zip
    - https://example.com/part3.zip
  folder: Collections/Parts
  extract_from_archive:
    - file.rom
```

**Behavior:**
- Each URL is downloaded to `Collections/Parts`
- `file.rom` is extracted from each archive (if present)
- Progress shows "File 1/3", "File 2/3", etc.

### Option 3: Rich URL Objects
Each URL can have its own folder and extraction rules.

```yaml
- name: Regional BIOS Files
  type: ddl
  folder: BIOS  # Default folder (optional)
  urls:
    - url: https://example.com/usa-bios.zip
      folder: BIOS/USA
      extract_from_archive:
        - usa.rom
    
    - url: https://example.com/eur-bios.zip
      folder: BIOS/EUR
      extract_from_archive:
        - eur.rom
    
    - url: https://example.com/jpn-bios.zip
      folder: BIOS/JPN
      extract_from_archive:
        - jpn.rom
```

**Behavior:**
- Each URL downloads to its specified folder
- Each URL extracts only its specified files
- Source-level `folder` is used as default if URL doesn't specify one

### Option 4: Mixed Simple Strings and Rich Objects
You can mix simple URLs with rich objects in the same list.

```yaml
- name: Mixed Collection
  type: ddl
  folder: Software/Games  # Default for simple URLs
  urls:
    - https://example.com/games-a-m.zip  # Simple: uses default folder
    
    - url: https://example.com/games-n-z.zip
      folder: Software/Games/NtoZ  # Rich: overrides folder
    
    - https://example.com/updates.zip  # Simple: uses default folder
    
    - url: https://example.com/special.zip
      folder: Software/Special
      extract_from_archive:
        - special.rom
```

## Settings Inheritance

### Priority Order (highest to lowest):
1. **URL-level** settings (in rich URL object)
2. **Source-level** settings (at the source root)
3. **Defaults** (empty string for folder, None for extract_from_archive)

### Example:
```yaml
- name: Inheritance Example
  type: ddl
  folder: Downloads  # Source-level default
  extract_from_archive:  # Source-level default
    - common.rom
  urls:
    - url: https://example.com/file1.zip
      # Uses: folder="Downloads", extract="common.rom"
    
    - url: https://example.com/file2.zip
      folder: Special
      # Uses: folder="Special", extract="common.rom"
    
    - url: https://example.com/file3.zip
      extract_from_archive:
        - special.rom
      # Uses: folder="Downloads", extract="special.rom"
```

## Source-Level Operations

Operations like `rename` run **after all URLs** are downloaded and extracted.

```yaml
- name: Download and Relocate
  type: ddl
  folder: Temp
  urls:
    - https://example.com/archive1.zip
    - https://example.com/archive2.zip
  extract_from_archive:
    - bios.rom
    - config.dat
  rename:
    - from: bios.rom
      to: ../../BIOS/system-bios.rom
    - from: config.dat
      to: ../../Config/system.cfg
```

**Processing order:**
1. Download archive1.zip → Temp/
2. Extract bios.rom, config.dat from archive1.zip
3. Download archive2.zip → Temp/
4. Extract bios.rom, config.dat from archive2.zip (may overwrite)
5. Rename/move bios.rom → BIOS/system-bios.rom
6. Rename/move config.dat → Config/system.cfg

## Supported Source Types

| Type | Multiple URLs | Notes |
|------|---------------|-------|
| `ddl` | ✅ Yes | Direct download - fully supported |
| `mega` | ✅ Yes | Mega.nz links - fully supported |
| `IA-COL` | ⚠️ No | Internet Archive collections use single URL by nature |
| `tor` | ⚠️ No | Torrents use single magnet/file |

## Progress Reporting

### Single URL (legacy behavior):
```
📥 Downloading 'ROM Collection' (ddl)...
   ✓ Downloaded 'roms.zip' (1024000 bytes)
```

### Multiple URLs:
```
📥 Downloading 'Multi-Part Collection' (ddl) - 3 file(s)...
   📄 File 1/3: https://example.com/part1.zip
      10% 20% 30% ... 100%
      ✓ Downloaded 'part1.zip' (500000 bytes)
   📄 File 2/3: https://example.com/part2.zip
      10% 20% 30% ... 100%
      ✓ Downloaded 'part2.zip' (600000 bytes)
   📄 File 3/3: https://example.com/part3.zip
      10% 20% 30% ... 100%
      ✓ Downloaded 'part3.zip' (400000 bytes)
```

## Error Handling

- If one URL fails, processing continues with the remaining URLs
- Failed downloads are reported but don't block the entire source
- Extract operations only fail for that specific archive

```
📥 Downloading 'Collection' (ddl) - 3 file(s)...
   📄 File 1/3: https://example.com/part1.zip
      ✓ Downloaded 'part1.zip'
   📄 File 2/3: https://example.com/part2.zip
      ✗ Download failed: 404 Not Found
   📄 File 3/3: https://example.com/part3.zip
      ✓ Downloaded 'part3.zip'
```

## Implementation Details

### Code Changes

**New Function:** `normalize_source_urls(source, default_folder="")`
- Converts all URL formats to a consistent list of dicts
- Handles backward compatibility with single `url` field
- Supports both simple strings and rich objects in `urls` list
- Returns: `[{url, folder, extract_from_archive}, ...]`

**Updated Endpoints:**
- `/packs/install` - Pack installation with multiple URLs
- `/download` - Legacy download endpoint with multiple URLs

### Usage Example in Code:
```python
source = {
    "urls": [
        "https://example.com/file1.zip",
        {"url": "https://example.com/file2.zip", "folder": "Special"}
    ],
    "folder": "Default"
}

url_entries = normalize_source_urls(source)
# Returns:
# [
#   {"url": "https://example.com/file1.zip", "folder": "Default", "extract_from_archive": None},
#   {"url": "https://example.com/file2.zip", "folder": "Special", "extract_from_archive": None}
# ]
```

## Real-World Use Cases

### Use Case 1: Multi-Part Archive
Some collections are distributed as multiple split archives:
```yaml
- name: Complete ROM Set
  type: ddl
  urls:
    - https://example.com/roms-part1.zip
    - https://example.com/roms-part2.zip
    - https://example.com/roms-part3.zip
  folder: ROMs
```

### Use Case 2: Regional BIOS Files
Collect different BIOS versions from separate sources:
```yaml
- name: System BIOS Collection
  type: ddl
  urls:
    - url: https://usa-source.com/bios.zip
      folder: BIOS/USA
    - url: https://eur-source.com/bios.zip
      folder: BIOS/EUR
    - url: https://jpn-source.com/bios.zip
      folder: BIOS/JPN
```

### Use Case 3: Different File Types
Download different components to different locations:
```yaml
- name: System Package
  type: ddl
  urls:
    - url: https://example.com/bios.zip
      folder: BIOS
      extract_from_archive: [system.rom]
    - url: https://example.com/games.zip
      folder: Games
    - url: https://example.com/demos.zip
      folder: Demos
```

### Use Case 4: Mirror Fallback (future enhancement)
While not currently implemented, the structure supports future fallback logic:
```yaml
- name: ROM with Mirrors
  type: ddl
  urls:
    - url: https://primary.com/rom.zip  # Try first
    - url: https://mirror1.com/rom.zip  # Fallback if first fails
    - url: https://mirror2.com/rom.zip  # Last resort
  folder: ROMs
```

## Migration Guide

### From Separate Sources to Multi-URL

**Before (verbose):**
```yaml
sources:
  - name: Collection Part 1
    type: ddl
    url: https://example.com/part1.zip
    folder: Collection
  - name: Collection Part 2
    type: ddl
    url: https://example.com/part2.zip
    folder: Collection
  - name: Collection Part 3
    type: ddl
    url: https://example.com/part3.zip
    folder: Collection
```

**After (concise):**
```yaml
sources:
  - name: Complete Collection
    type: ddl
    urls:
      - https://example.com/part1.zip
      - https://example.com/part2.zip
      - https://example.com/part3.zip
    folder: Collection
```

### Benefits:
- ✅ Less repetition in configuration
- ✅ Clearer that files are related
- ✅ Single source name in pack definitions
- ✅ Better progress reporting
- ✅ Grouped operations (rename applies to all)

## Testing

To test this feature without modifying production configs:

1. Create a test source in `archive_sources`:
```yaml
"Test":
  "MultiURL":
    base_path: Test/MultiURL
    sources:
      - name: Test Multi-URL
        type: ddl
        urls:
          - url: https://httpbin.org/bytes/1024
            folder: Test1
          - url: https://httpbin.org/bytes/2048
            folder: Test2
        folder: TestDefault
```

2. Use the Web UI to trigger download
3. Check logs for proper file tracking
4. Verify files land in correct folders

## Security Considerations

- URLs still respect `ssl_ignore_hosts` configuration
- All URLs must be in trusted `archive_sources` configuration
- Path traversal protection applies to all folder specifications
- Same security model as single-URL sources

## Future Enhancements

Potential future additions:
- Mirror fallback logic (try URLs in order until success)
- Parallel downloads for multiple URLs
- Conditional downloads (only if file doesn't exist)
- Checksum verification per URL
- Bandwidth limiting per source
