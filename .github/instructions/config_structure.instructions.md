---
alwaysApply: true
trigger: always_on
applyTo: "app/config.py"
description: Modular Configuration Architecture
---

# Configuration Structure

## Three-Tier Architecture

TransFS configuration is split into three logical files for scalability and maintainability.

### 1. Application Config (`config/app.yaml`)

**Purpose:** Infrastructure and runtime settings

**Contents:**
- `mountpoint` - FUSE mount point
- `filestore` - Physical storage location  
- `web_api` - API host/port
- `ssl_ignore_hosts` - SSL verification exceptions

**When to modify:** Infrastructure changes, deployment settings

### 2. Clients Config (`config/clients.yaml`)

**Purpose:** How to PRESENT content to different platforms

**Contents:**
- Client definitions (MiSTer, MAME, RetroBat, etc.)
- System mappings per client
- FUSE virtual filesystem structure
- File type mappings

**Key principle:** This is about PRESENTATION, not acquisition

### 3. Sources Config (`config/sources/{Manufacturer}/{System}.yaml`)

**Purpose:** Where to GET content from

**Structure:**
```
config/sources/
├── Acorn/
│   ├── Archimedes.yaml
│   ├── Atom.yaml
│   └── Electron.yaml
├── Nintendo/
│   ├── NES.yaml
│   ├── SNES.yaml
│   └── GameBoy.yaml
└── ...
```

**Contents per file:**
- `base_path` - Base directory for system
- `sources` - Download sources (DDL, torrents, etc.)
- `packs` - Predefined installation bundles

## Configuration Loading (config.py)

### Function Hierarchy

```python
read_app_config()       # Loads config/app.yaml
read_clients_config()   # Loads config/clients.yaml  
read_source_config()    # Loads config/sources/{Manufacturer}/{System}.yaml

read_config()           # Compatibility function - merges all three
```

### Critical Implementation Details

**1. Dynamic Source Discovery**
```python
# Automatically finds all YAML files in sources/ directory
for manufacturer in os.listdir("config/sources/"):
    for file in os.listdir(f"config/sources/{manufacturer}/"):
        if file.endswith(".yaml"):
            # Load and merge into archive_sources
```

**2. Pack Construction**

When loading packs from YAML, MUST include ALL fields:
```python
Pack(
    id=pack_data.get("id"),
    name=pack_data.get("name"),
    description=pack_data.get("description"),
    estimated_size=pack_data.get("estimated_size"),
    sources=pack_data.get("sources", []),
    post_process=pack_data.get("post_process"),
    build_script=pack_data.get("build_script"),
    info_links=pack_data.get("info_links")  # Don't forget this!
)
```

**3. Backward Compatibility**

`read_config()` maintains single-dict structure for legacy code:
```python
{
    "mountpoint": "...",
    "filestore": "...",
    "clients": [...],
    "archive_sources": {
        "Manufacturer": {
            "System": {...}
        }
    }
}
```

## File Naming Conventions

### Source Files

✅ **Correct:** Use canonical system name from clients.yaml
- `Archimedes.yaml` (matches `cananonical_system_name: Archimedes`)
- `BBC Micro.yaml` (includes space if canonical name has space)

❌ **Wrong:** Using client-specific names
- `Archie.yaml` (client name, not canonical)
- `BBCMicro.yaml` (removed space from canonical name)

### Manufacturer Folders

- Must match manufacturer field in clients.yaml
- Case-sensitive
- Examples: `Acorn`, `Nintendo`, `Sega`

## Adding New Systems

**Checklist:**

1. ✅ Create `config/sources/{Manufacturer}/{System}.yaml`
2. ✅ Use canonical system name for filename
3. ✅ Add client mapping in `config/clients.yaml`
4. ✅ Ensure `cananonical_system_name` matches filename
5. ✅ Restart container to reload configuration

**No code changes needed** - configuration is discovered automatically!

## Benefits of This Structure

### Scalability
- Adding system = Create one YAML file
- No 825-line monolithic config
- Easy to find specific system config

### Maintainability  
- Small focused files (17-460 lines)
- Clear separation of concerns
- Reduced merge conflicts in version control

### Flexibility
- Share system configs as individual files
- Copy/paste to add similar systems
- Independent development of different systems

## Common Mistakes to Avoid

❌ Forgetting to add new fields to Pack constructor
❌ Using wrong filename (client name vs canonical name)
❌ Adding sources config to clients.yaml
❌ Hardcoding paths instead of using config_dir parameter

✅ Always update Pack dataclass and constructor together
✅ Match filename to cananonical_system_name exactly
✅ Keep acquisition (sources) and presentation (clients) separate
✅ Pass config_dir for testability
