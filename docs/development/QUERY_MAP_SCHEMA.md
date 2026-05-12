# Query Map Schema (v1)

This schema replaces `...SoftwareArchives...` with explicit **query-based maps** and **file maps**. It is designed to support future metadata fields while remaining safe and extensible.

## 1) Map Types

### A) File Map (single file)
```yaml
- boot.vhd:
    file:
      path: Software/VHD/hoglet67.vhd
      unzip: true            # optional
      zip_internal_file: ... # optional
```

### B) Query Map (dynamic listing)
```yaml
- FDs:
    query:
      source_dir: Software
      extensions: [DSK, DO, PO, 2MG]
      extension_map: { 2MG: DSK }   # optional real->virtual extension mapping
      supports_zip: false           # optional
      supports_zaparoo: true        # optional
      zip_mode: file                # optional: hierarchical | flatten | file
      filters:                      # optional structured filters (AND by default)
        - field: year
          op: ">="
          value: 1990
      logic: and                    # optional: and | or
    transforms:                     # optional (per map)
      2MG:
        - type: two_mg
```

## 2) Query Object

Supported keys (extensible):
- `extensions`: list of extensions ("*" means no extension filter)
- `source_dir`: limit search to `/Native/<system>/<source_dir>/...`
- `extension_map`: remap real extension -> virtual extension in listings
- `filters`: list of `{field, op, value}`
- `logic`: `and` (default) or `or` between filters
- `supports_zip`, `supports_zaparoo`, `zip_mode`: behavior hints

### Supported fields (current)
**files table**: `extension`, `filename`, `source_path`, `virtual_path`, `size`, `mtime`, `system`, `content_type`

**metadata table**: `genre`, `language`, `region`, `year`, `is_prototype`, `is_homebrew`, `is_translation`, `is_hack`, `tags`

### Supported operators (current)
`=`, `!=`, `>`, `>=`, `<`, `<=`, `like`, `in`, `between`

## 3) Notes on Future Metadata
- The query schema is intentionally structured so new fields can be added without changing map definitions.
- For new metadata, add the field to the database and allow it in query validation.
- Avoid raw SQL in config for safety and portability.

## 4) Backward Compatibility
Legacy `...SoftwareArchives...` is still supported in code, but all active configs should move to this schema.
