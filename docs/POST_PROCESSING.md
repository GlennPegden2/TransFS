# Declarative Post-Processing System

## Overview

TransFS now supports declarative post-processing operations in `transfs.yaml`, eliminating the need for bash scripts in 90% of cases. This makes pack definitions more portable, testable, and easier to understand.

## Architecture

- **PostProcessor** (`app/post_process.py`): Python class that executes declarative operations
- **YAML Configuration**: Define operations in `transfs.yaml` under pack `post_process`
- **Legacy Support**: Bash scripts still supported via `build_script` for complex edge cases

## Supported Operations

### 1. Extract Archives

Extract zip, 7z, tar, and tar.gz archives.

```yaml
- extract:
    files: "Collections/4corn/*.zip"  # Glob pattern
    dest: "tmp/extracted"              # Destination directory
    # formats: [zip, 7z, tar, tar.gz] # Optional: limit formats
```

**Features:**
- Automatic format detection
- Deduplication via `.extracted_*` marker files
- Respects `skip_existing` setting

### 2. Create Directories

```yaml
- mkdir:
    paths: ["HDF", "BIOS", "Collections/Games"]
```

### 3. Move Files

Simple move operation with glob patterns.

```yaml
- move:
    from: "tmp/extracted/**/*.rom"
    to: "BIOS/"
    flatten: true  # Remove directory structure
```

**Options:**
- `flatten: true` - Move all files directly to destination (no subdirs)
- `flatten: false` - Preserve directory structure

### 4. Move by Pattern Rules

Organize files based on multiple pattern rules.

```yaml
- move_by_pattern:
    from: "tmp/extracted/TOSEC/**"
    rules:
      - match: "**/*[BAS]*/**"
        dest: "BAS/"
      - match: "**/*[ROM]*/**"
        dest: "ROM/"
      - match: "**/*Games*/**"
        dest: "Games/"
    flatten: true
```

### 5. Copy Files

Like move, but preserves source files.

```yaml
- copy:
    from: "source/*.rom"
    to: "backup/"
```

### 6. Rename

```yaml
- rename:
    from: "tmp/BEEB.MMB"
    to: "MMB/rayharper.mmb"
```

### 7. Cleanup

Remove temporary files/directories.

```yaml
- cleanup: ["tmp/", "cache/"]
# Or with dict format:
- cleanup:
    paths: ["tmp/", "cache/"]
```

## Complete Example

Converting the Archimedes build script:

**Before (bash script):**
```bash
#!/bin/bash
set -e
mkdir -p "$SOFTWARE_DIR/tmp/unzipped_software"
extract_if_needed "$SOFTWARE_DIR/4corn/riscos3_71.zip" "$SOFTWARE_DIR/tmp/unzipped_software"
extract_if_needed "$SOFTWARE_DIR/SIDKiddCROS4.2/CROS42_082620.7z" "$SOFTWARE_DIR/tmp/unzipped_software"
mkdir -p "$SOFTWARE_DIR/../HDF"
mkdir -p "$SOFTWARE_DIR/../BIOS"
move_if_needed "$SOFTWARE_DIR/tmp/unzipped_software/*.hdf" "$SOFTWARE_DIR/../HDF"
move_if_needed "$SOFTWARE_DIR/tmp/unzipped_software/*.rom" "$SOFTWARE_DIR/../BIOS"
rm -rf "$SOFTWARE_DIR/tmp/unzipped_software"
```

**After (YAML):**
```yaml
packs:
  - id: full-collection
    name: Full Software Collection
    sources: [mister-bios, 4corn-bios, SIDKidd-CROS4.2, SIDKidd-Icebird]
    post_process:
      - extract:
          files: "Collections/4corn/riscos3_71.zip"
          dest: "tmp/extracted"
      - extract:
          files: "Collections/SIDKiddCROS4.2/CROS42_082620.7z"
          dest: "tmp/extracted"
      - mkdir:
          paths: ["HDF", "BIOS"]
      - move:
          from: "tmp/extracted/**/*.hdf"
          to: "HDF/"
          flatten: true
      - move:
          from: "tmp/extracted/**/*.rom"
          to: "BIOS/"
          flatten: true
      - cleanup: ["tmp/"]
```

## Advantages

1. **Cross-platform** - Works identically on Windows, Linux, macOS
2. **No bash knowledge required** - Simple YAML syntax
3. **Validated** - YAML schema catches errors before execution
4. **Testable** - Can simulate without executing
5. **Readable** - Clear what will happen
6. **Maintainable** - Easy to modify

## Hybrid Approach

For complex cases, combine both approaches:

```yaml
packs:
  - id: atom-pack
    sources: [hoglet67, blankvhd]
    post_process:
      # Common operations in YAML
      - extract:
          files: "Collections/*.zip"
          dest: "tmp/extracted"
      - mkdir:
          paths: ["HDs"]
    # Complex VHD manipulation still uses bash
    build_script: "build_scripts/MiSTer/Acorn/Atom/vhd_operations.sh"
```

## Migration Guide

### 1. Identify Common Patterns

Look for these in bash scripts:
- `unzip`, `7zr x` → `extract` operation
- `mkdir -p` → `mkdir` operation
- `mv`, file moves → `move` operation
- `rm -rf` → `cleanup` operation

### 2. Convert to YAML

```yaml
# Pattern: Extract archives
unzip "$file" -d "$dest"
# Becomes:
- extract:
    files: "path/to/*.zip"
    dest: "destination/"

# Pattern: Move files by extension
mv *.rom BIOS/
# Becomes:
- move:
    from: "**/*.rom"
    to: "BIOS/"
    flatten: true

# Pattern: Organize by path markers
mv "$UNZIP_DIR/*/*[BAS]*/*" "$SOFTWARE_DIR/BAS"
# Becomes:
- move_by_pattern:
    from: "tmp/extracted/**"
    rules:
      - match: "**/*[BAS]*/**"
        dest: "BAS/"
    flatten: true
```

### 3. Keep Bash for Edge Cases

Keep bash scripts for:
- VHD/image file manipulation (`guestfish`)
- Complex conditional logic
- External tool integrations
- File content transformations

## Logging

Operations provide detailed logging:

```
🔧 Running post-processing operations...
============================================================
[Operation 1/6]
📦 Extracting 1 archive(s) to tmp/extracted
   📦 Extracting: riscos3_71.zip
   ✓ Extracted: riscos3_71.zip
[Operation 2/6]
📁 Creating 2 directory(ies)
   ✓ Created: HDF
   ✓ Created: BIOS
[Operation 3/6]
📁 Moving 15 item(s) to HDF/
   ✓ Moved: CROS42.hdf
   ✓ Moved: ICEBIRD.hdf
   ...
============================================================
✓ Post-processing completed successfully
```

## Error Handling

- Operations fail fast on errors
- Detailed error messages in logs
- `skip_existing` prevents overwriting
- Marker files prevent duplicate extractions

## Performance

- Glob patterns use Python's optimized `glob` module
- Deduplication via marker files (no redundant extractions)
- Parallel-safe with `skip_existing=true`

## Future Enhancements

Potential additions:
- `validate` - Check file integrity (checksums)
- `transform` - Run converters on files
- `filter` - Select files by size/date
- `dedupe` - Remove duplicate files
- Templates for common patterns
