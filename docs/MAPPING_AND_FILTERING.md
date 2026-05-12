# Mapping and Filtering

This document explains how TransFS maps real files into the virtual filesystem, and how filtering is applied.

## 1. Mapping Overview

The virtual filesystem is:

```
/mnt/transfs/<client>/<system>/<map>/<subfolders/files>
```

Mappings are defined in `clients.yaml` under each client’s systems. A system can contain static maps and a dynamic `...SoftwareArchives...` map.

- **Static maps**: Explicit paths that point to a specific real file or folder.
- **Dynamic maps**: Generated from `...SoftwareArchives...` and `filetypes`.

### Dynamic map example

```yaml
maps:
  - ...SoftwareArchives...:
      source_dir: Software
      filetypes:
        - FDs: "DSK,DO,PO"
        - HDs: "HDV"
```

This produces virtual folders:

```
/mnt/transfs/<client>/<system>/FDs
/mnt/transfs/<client>/<system>/HDs
```

Those map to real folders under the system’s `source_dir`:

```
/mnt/filestorefs/Native/<manufacturer>/<system>/Software/DSK/
/mnt/filestorefs/Native/<manufacturer>/<system>/Software/DO/
/mnt/filestorefs/Native/<manufacturer>/<system>/Software/PO/
/mnt/filestorefs/Native/<manufacturer>/<system>/Software/HDV/
```

### Extension mapping

File extensions are normalized by the `filetypes` mapping:

- `FDs: "DSK,DO,PO"` → all `.dsk`, `.do`, `.po` files appear in the `FDs` folder
- `ROMs: "BIN:ROM"` → `.bin` files appear as `.rom`

## 2. Mapping Rules

1. **Virtual folder list** is derived from the `filetypes` keys (e.g., `FDs`, `ROMs`).
2. **Files included** are those found in mapped extension folders.
3. **Hidden files** (starting with `.`) are never shown.
4. **Zip behavior**:
   - Single relevant file → flatten into parent
   - Multiple relevant files → zip appears as a folder

## 3. Filtering

### Client filtering

The virtual root only shows clients defined in `clients.yaml`. Each client’s view is isolated to its own `maps` and `filetypes`.

### System filtering

Systems are filtered by the selected client. If two clients define the same `system_mapping_name`, they are still distinct in the virtual tree because their `client` prefix differs.

### Extension filtering

Dynamic maps only include files whose extensions match the `filetypes` mapping. Anything else present in those folders will still be visible today unless explicitly filtered (by design). This is why stray files like `.url` may appear.

If you want strict filtering, we can enforce it by restricting to `real_exts` only.

## 4. Troubleshooting

- **Missing files**: Confirm the extension is in `filetypes` and the file exists in the correct extension folder.
- **Stale results**: Only in-memory cache is used now; restart clears it. Persistent PKL caches are disabled.
- **Unexpected files**: Likely present in the extension folder but not filtered by extension.
