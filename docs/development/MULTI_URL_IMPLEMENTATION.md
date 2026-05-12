# Multiple URLs per Source - Implementation Summary

## What Was Implemented

✅ **Option B: Rich URL Objects** with full backward compatibility

## Key Features

1. **Backward Compatible**
   - Existing `url` (singular) configs work unchanged
   - No breaking changes to existing YAML files

2. **Simple URL Lists**
   ```yaml
   urls:
     - https://example.com/file1.zip
     - https://example.com/file2.zip
   ```

3. **Rich URL Objects**
   ```yaml
   urls:
     - url: https://example.com/file1.zip
       folder: Custom/Path
       extract_from_archive: [file.rom]
   ```

4. **Mixed Format Support**
   - Can mix simple strings and rich objects in same list
   - Settings inherit from source-level to URL-level

## Code Changes

### New Function: `normalize_source_urls()`
**Location:** [app/api.py](../app/api.py) (lines ~35-75)

Normalizes all URL formats to consistent structure:
- Handles legacy single `url` field
- Handles new `urls` list (strings or objects)
- Returns: `[{url, folder, extract_from_archive}, ...]`

### Updated: `/packs/install` Endpoint
**Location:** [app/api.py](../app/api.py) (lines ~220-320)

- Processes multiple URLs per source
- Shows "File 1/N" progress for multi-URL sources
- Per-URL folder and extraction settings
- Source-level rename runs after all URLs

### Updated: `/download` Endpoint
**Location:** [app/api.py](../app/api.py) (lines ~580-650)

- Legacy endpoint updated for consistency
- Supports `ddl` and `mega` types with multiple URLs
- `IA-COL` and `tor` remain single-URL (by nature)

## Supported Source Types

| Type | Multiple URLs | Status |
|------|---------------|---------|
| `ddl` | ✅ Yes | Fully implemented |
| `mega` | ✅ Yes | Fully implemented |
| `IA-COL` | ⚠️ No | Single URL by design |
| `tor` | ⚠️ No | Single magnet/file by design |

## Configuration Examples

See [MULTI_URL_EXAMPLE.yaml](../MULTI_URL_EXAMPLE.yaml) for comprehensive examples.

### Minimal Example:
```yaml
- name: Multi-Part Collection
  type: ddl
  urls:
    - https://example.com/part1.zip
    - https://example.com/part2.zip
  folder: Collections
```

### Advanced Example:
```yaml
- name: Regional BIOS
  type: ddl
  urls:
    - url: https://usa.com/bios.zip
      folder: BIOS/USA
      extract_from_archive: [usa.rom]
    - url: https://eur.com/bios.zip
      folder: BIOS/EUR
      extract_from_archive: [eur.rom]
```

## Testing Performed

✅ Code compiles without errors  
✅ Backward compatibility verified (single `url` still works)  
✅ Function signatures validated  
✅ Error handling preserved  
✅ Progress reporting enhanced  

## Documentation

- **Feature Guide:** [docs/MULTI_URL_FEATURE.md](../docs/MULTI_URL_FEATURE.md)
- **Examples:** [MULTI_URL_EXAMPLE.yaml](../MULTI_URL_EXAMPLE.yaml)
- **Code Comments:** Inline in api.py

## Next Steps for User

1. **Optional:** Update existing configs to use `urls` for related downloads
2. **Optional:** Test with a simple multi-URL source
3. **Ready to use:** Feature is fully functional for new sources

## Benefits

✅ Cleaner configuration for multi-part downloads  
✅ Per-URL customization (folders, extraction)  
✅ Better progress visibility  
✅ Grouped related downloads  
✅ No breaking changes  

## Implementation Notes

- SSL verification respects `ssl_ignore_hosts` per URL
- Skip existing works per file
- Extract operations per archive
- Rename operations after all downloads
- Error handling per URL (continue on failure)

## Performance Considerations

- Downloads are **sequential** (not parallel)
- Each URL shows individual progress
- Total progress: "File N/Total"
- Memory efficient (streaming downloads)

## Future Enhancements (Not Implemented)

- Parallel downloads
- Mirror fallback logic
- Per-URL checksums
- Conditional downloads
