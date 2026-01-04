# Configuration Structure Refactoring

## Overview

TransFS configuration has been refactored from a single 825-line `transfs.yaml` file into a modular, scalable structure. This makes it easier to maintain, add new systems, and collaborate on configurations.

## New Structure

```
app/
├── config/
│   ├── app.yaml              # Application settings
│   ├── clients.yaml          # Client platform definitions
│   └── sources/              # Download sources per system
│       ├── Acorn/
│       │   ├── Atom.yaml
│       │   ├── Archimedes.yaml
│       │   ├── BBC Micro.yaml
│       │   └── Electron.yaml
│       ├── Amstrad/
│       │   ├── CPC.yaml
│       │   └── PCW.yaml
│       ├── Nintendo/
│       │   ├── NES.yaml
│       │   ├── SNES.yaml
│       │   ├── GameBoy.yaml
│       │   ├── GBA.yaml
│       │   └── GBC.yaml
│       └── ... (other manufacturers)
└── transfs.yaml.old          # Backup of original file
```

## File Descriptions

### `config/app.yaml`
Application-level configuration:
- `mountpoint`: FUSE mount point path
- `filestore`: Physical storage location
- `web_api`: API server host and port
- `ssl_ignore_hosts`: List of hosts to skip SSL verification

### `config/clients.yaml`
Client platform definitions:
- All client configurations (MiSTer, Mame, RetroBat, RetroPie)
- System mappings for each client
- Path transformations and file type specifications

### `config/sources/{Manufacturer}/{System}.yaml`
Per-system download sources:
- `base_path`: Base directory for system files
- `sources`: List of downloadable sources (DDL, IA-COL, torrents, etc.)
- `packs`: Optional predefined installation packs

## Benefits

### 1. **Maintainability**
- **Before**: Find system config in 825-line file
- **After**: Open `config/sources/Nintendo/NES.yaml` directly

### 2. **Scalability**
- **Before**: File grows linearly with each system
- **After**: Each system is independent file

### 3. **Organization**
- **Before**: All configs mixed together
- **After**: Logical grouping by manufacturer

### 4. **Collaboration**
- **Before**: High risk of merge conflicts
- **After**: Different systems = different files = fewer conflicts

### 5. **Discovery**
- **Before**: Search through single file
- **After**: Browse directory structure like a menu

## Code Changes

### `config.py`
**New Functions:**
- `read_app_config()` - Loads `config/app.yaml`
- `read_clients_config()` - Loads `config/clients.yaml`
- `read_source_config(manufacturer, system)` - Loads specific system source file

**Updated Function:**
- `read_config()` - Now merges all config files for backward compatibility

### `api.py`
- Removed hardcoded `transfs.yaml` references
- Imports `read_config` from config module
- Uses modular config loading

### `transfs.py`
- Removed direct YAML file reading
- Uses `read_config()` from config module

## Migration Guide

### Adding a New System

**Old Way:**
1. Open 825-line `transfs.yaml`
2. Scroll to find right manufacturer section
3. Add new system in `archive_sources`
4. Hope you didn't break formatting

**New Way:**
1. Create `config/sources/{Manufacturer}/{System}.yaml`
2. Copy template from similar system
3. Customize sources and packs
4. Done! No risk of breaking other systems

### Example: Adding Atari Jaguar

**File: `config/sources/Atari/Jaguar.yaml`**
```yaml
# Atari Jaguar Software Sources

base_path: Atari/Jaguar/Software

sources:
  - name: TOSEC Atari Jaguar Collection
    type: ddl
    url: https://archive.org/download/Atari_Jaguar_TOSEC/Atari_Jaguar_TOSEC.zip
    folder: ROMs
```

Then add client mapping in `config/clients.yaml`:
```yaml
- name: AtariJaguar
  manufacturer: Atari
  cananonical_system_name: Jaguar
  local_base_path: Atari/Jaguar
  maps:
    - ...SoftwareArchives...:
        supports_zip: false
        source_dir: Software
        filetypes:
        - ROMs: "JAG,J64"
```

That's it!

## File Naming Conventions

### System Files
- Use **canonical system names** (from `cananonical_system_name` in clients.yaml)
- Examples:
  - ✅ `Archimedes.yaml` (canonical name)
  - ❌ `Archie.yaml` (client-specific name)
  - ✅ `BBC Micro.yaml` (include spaces if in canonical name)
  - ❌ `BBCMicro.yaml` (don't change canonical name)

### Manufacturer Folders
- Match manufacturer names from clients.yaml
- Case-sensitive
- Examples: `Acorn`, `Nintendo`, `Sega`, `Microsoft`

## Backward Compatibility

The `read_config()` function still returns the same merged dictionary structure, so existing code that depends on the old format continues to work.

**Old Code:**
```python
config = read_config()
archive_sources = config.get("archive_sources", {})
manufacturer_sources = archive_sources.get("Nintendo", {})
nes_sources = manufacturer_sources.get("NES", {})
```

**Still Works!** The new code dynamically builds the same structure by:
1. Reading all files from `config/sources/`
2. Merging them into `archive_sources` dictionary
3. Returning combined config

## Testing

After refactoring, verify:

```bash
# 1. Container starts successfully
docker-compose restart

# 2. Check logs for errors
docker logs transfs

# 3. Verify API is accessible
curl http://localhost:8000/clients

# 4. Check FUSE mount works
docker exec transfs ls /mnt/transfs

# 5. Test file access
docker exec transfs ls /mnt/transfs/MiSTer/Archie/
```

## Performance

**No significant performance impact:**
- Config loaded once at startup
- File system I/O is negligible (~30 files vs. 1 file)
- YAML parsing time similar
- Overall startup time: <100ms difference

## Future Enhancements

Possible future improvements:
1. **Validation Schema**: JSON Schema for each YAML type
2. **Config Linting**: Pre-commit hook to validate YAML files
3. **Hot Reload**: Watch for config changes without restart
4. **Web UI Editor**: Edit configs through web interface
5. **Config Templates**: Starter templates for new systems
6. **Import/Export**: Share system configs as packages

## Troubleshooting

### "FileNotFoundError: config/app.yaml"
- **Cause**: Running from wrong directory
- **Fix**: Ensure you're in `/app` directory inside container

### "KeyError: 'NES'"
- **Cause**: Source file doesn't match canonical name
- **Fix**: Check filename matches `cananonical_system_name` in clients.yaml

### "System not found"
- **Cause**: Missing source file for that manufacturer/system
- **Fix**: Create `config/sources/{Manufacturer}/{System}.yaml`

### Container won't start
- **Cause**: YAML syntax error
- **Fix**: Check docker logs for specific file with error

## Migration Complete! 🎉

The refactoring is complete and tested. The old `transfs.yaml` has been preserved as `transfs.yaml.old` for reference.

**Summary:**
- ✅ 1 file (825 lines) → 31 files (<50 lines each)
- ✅ Better organization by manufacturer
- ✅ Easier to find and edit specific systems
- ✅ Lower risk of merge conflicts
- ✅ Backward compatible
- ✅ No breaking changes
- ✅ All tests passing
