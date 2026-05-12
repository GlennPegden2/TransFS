# Automatic Filename Deduplication

## Overview

When the same ROM/game exists in multiple sources or ROM packs (e.g., DataGhost-Full and RomHunter-Full both containing "Acid Drop.bin"), the filesystem would normally display both files with identical names in the same directory. This violates POSIX filesystem semantics where each file in a directory must have a unique name.

TransFS solves this with automatic filename deduplication at database sync time.

## Default Behavior: Auto-Rename Duplicates

By default (when `preserve_exact_filenames` is omitted or set to `false`), duplicate filenames are automatically renamed with numeric suffixes:

```
Acid Drop.bin        (from DataGhost-Full)
Acid Drop_2.bin      (from RomHunter-Full)
Acid Drop_3.bin      (if a third source also has this file)
```

**Benefits**:
- ✅ Users can access all ROM variants
- ✅ Can choose which source to use
- ✅ Works transparently for most systems
- ✅ Filename differences don't matter (the ROM content is the same)

**Configuration** (default):
```yaml
- ROMs:
    query:
      source_dir: Software
      extensions:
        - BIN
      supports_zip: false
      supports_zaparoo: true
      # preserve_exact_filenames is false by default
```

## Strict Filename Mode: Skip Duplicates

For systems where exact filenames matter (e.g., emulators that read from XML file lists), set `preserve_exact_filenames: true`:

```yaml
- FDs:
    query:
      source_dir: Software
      extensions:
        - FD
      preserve_exact_filenames: true
```

**Behavior**:
- Only the first occurrence of each filename is indexed in the database
- Subsequent duplicates are skipped during sync
- Duplicates are logged for debugging

**Example Use Case**:
- **RetroBAT's FDs map**: Set to `preserve_exact_filenames: true` for lr-mame compatibility
- MAME reads from shipped XML files containing exact expected filenames
- Having multiple files with slightly different names breaks MAME's file matching

## Implementation Details

- **When**: Deduplication happens during database sync (when `python3 -m app.sync_database` runs)
- **What**: Virtual filenames in the database are deduplicated; source files remain unchanged
- **Where**: Users see deduplicated names when browsing `/mnt/transfs/<client>/<system>/<map>/`
- **Cost**: No runtime overhead - deduplication is one-time during sync
- **How**: Track filenames per (client, system, map) directory; rename subsequent duplicates

## Configuration Reference

| Setting | Value | Behavior |
|---------|-------|----------|
| `preserve_exact_filenames` | `false` (default) | Auto-rename duplicates: `file.ext`, `file_2.ext`, `file_3.ext`, etc. |
| `preserve_exact_filenames` | `true` | Skip duplicates: only first file indexed, others logged |

## Examples

### Standard Atari 2600 ROMs (auto-rename)
```yaml
- name: Atari2600
  maps:
    - ROMs:
        query:
          source_dir: Software
          extensions:
            - BIN
          supports_zip: false
          supports_zaparoo: true
          # Duplicates will be auto-renamed
```

### MAME-compatible FDs (preserve filenames)
```yaml
- name: Amstrad
  maps:
    - FDs:
        query:
          source_dir: Software
          extensions:
            - DSK
          supports_zip: true
          supports_zaparoo: true
          zip_mode: file
          preserve_exact_filenames: true  # MAME needs exact names
```

## FAQ

**Q: What if I want to control which duplicate file is kept?**

A: The first file encountered during directory scanning is kept. To control which, organize your ROM sources in the order you prefer (alphabetically). Since most directory scans are alphabetical, sources starting with "A" (e.g., "Amiga") will be preferred over "Z" (e.g., "Zipped").

**Q: Will the original source files be modified?**

A: No. Only the virtual filenames in the database are deduplicated. Source files remain completely unchanged on disk.

**Q: Does this affect performance?**

A: No runtime impact. Deduplication is computed once during sync, not during browsing or file access.

**Q: Can I change this setting after syncing?**

A: Yes. Changing the flag and re-running `python3 -m app.sync_database --full` will re-index with the new behavior.
