# Pack-Based Software Distribution System

## Overview
TransFS now supports flexible, user-selectable software "packs" for each system. Users can install combinations of packs (minimal, curated, full collection, region-specific, etc.) via the web UI.

## Configuration

### Web API Settings
**File:** `app/transfs.yaml`

Configure the web UI/API host and port:
```yaml
mountpoint: /mnt/transfs
filestore: /mnt/filestorefs

# Web UI/API Configuration
web_api:
  host: "0.0.0.0"  # Bind address (0.0.0.0 = all interfaces)
  port: 8000       # Port for web UI and API endpoints
```

**Note:** If you change the port in `transfs.yaml`, also update the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "8000:8000"  # Change first 8000 to match your configured port
```

The web API configuration is read by:
- `run_local.sh` (for local development)
- `Dockerfile` CMD (for standalone Docker)
- `docker-compose.yml` entrypoint (for Docker Compose)
- `main.py` (when running directly with Python)

## Implementation Summary

### Architecture

**Key Principle:** Packs are defined in `archive_sources` (content acquisition) rather than `clients` (content presentation). This allows multiple clients (MiSTer, MAME, etc.) to share the same downloadable content with different FUSE mappings.

- **`archive_sources`** - Defines where content comes from and what packs are available
- **`clients`** - Defines how to present/map that content via FUSE

### 1. YAML Configuration Schema
**File:** `app/transfs.yaml`

Packs are now defined in `archive_sources` by manufacturer and system:
```yaml
archive_sources:
  Acorn:
    Archimedes:
      base_path: Acorn/Archimedes/Software
      packs:
        - id: minimal
          name: Minimal Starter Set
          description: Essential BIOS files and a few demo applications
          estimated_size: 10MB
          sources: [mister-bios]  # Downloads only BIOS
          build_script: build_scripts/MiSTer/Acorn/Archimedes/build_minimal.sh
        - id: best-of-best
          name: Best of the Best
          description: Curated collection of most acclaimed games
          estimated_size: 250MB
          sources: [mister-bios, 4corn-bios, SIDKidd-CROS4.2]  # Multiple sources
          build_script: build_scripts/MiSTer/Acorn/Archimedes/build_best.sh
        - id: full-collection
          name: Full Software Collection
          description: Complete archive of all available software
          estimated_size: 3.2GB
          sources: [mister-bios, 4corn-bios, SIDKidd-CROS4.2, SIDKidd-Icebird]
          build_script: build_scripts/MiSTer/Acorn/Archimedes/build.sh
      sources:
        - name: 4corn-bios
          type: ddl
          url: https://www.4corn.co.uk/archive//roms/riscos3_71.zip
        - name: mister-bios
          type: ddl
          url: https://github.com/.../riscos.rom
        - name: SIDKidd-CROS4.2
          type: ddl
          url: https://www.dropbox.com/.../CROS42_082620.7z
        - name: SIDKidd-Icebird
          type: ddl
          url: https://www.dropbox.com/.../ICEBIRD.7z

clients:
  - name: MiSTer
    systems:
      - name: Archie
        manufacturer: Acorn
        cananonical_system_name: Archimedes
        maps:
          - riscos.rom:
              default_source:
                source_filename: Software/BIOS/riscos.rom
```

This architecture means:
- **Same packs, different clients**: MiSTer and MAME can download the same Archimedes software
- **Different mappings**: Each client presents the downloaded content differently via FUSE
- **Centralized content**: One source of truth for downloadable content per system
- **Declarative downloads**: Packs declare which sources they need; API orchestrates the downloads

### Pack Installation Workflow

When a user installs a pack via the web UI:

1. **User Selection** - User checks pack(s) in web UI and clicks "Install Packs"
2. **Download Phase** - For each pack:
   - API reads the `sources` array from pack definition
   - Downloads each referenced source (DDL, torrent, mega, etc.)
   - Saves to `filestore/Native/{base_path}/{platform}/`
   - Skips files that already exist if `skip_existing: true`
3. **Build Phase** (optional) - For each pack with a `build_script`:
   - Runs the pack's `build_script` with environment variables:
     - `BASE_PATH` - Base directory for system files
     - `PACK_ID` - Pack identifier
     - `PACK_NAME` - Pack display name
     - `SKIP_EXISTING` - "1" to skip existing files
   - Build script extracts, organizes, and transforms downloaded content
   - **If no build_script**: Skip this phase, downloaded files are used as-is
4. **Complete** - Content is ready in filestore for FUSE to present to clients

**Benefits:**
- Downloads are automatic - no manual wget/curl in build scripts
- Build scripts only when needed (unzip, rename, convert, etc.)
- Many simple packs need zero build logic
- Downloads can be reused across multiple packs
- Clear separation: packs = what to get, build scripts = how to organize it
- Easy to add new packs by referencing existing sources

**Key Features:**
- `id`: Unique identifier for the pack
- `name`: Display name for UI
- `description`: User-facing description
- `estimated_size`: Human-readable size estimate
- `sources`: Array of source names to download (references `sources` definitions)
- `build_script`: **Optional** - Only needed if downloaded files require post-processing

**Build Script Usage:**
Build scripts are **optional** and only used when downloaded content needs transformation:
- ✅ **Use build scripts for**: Extracting archives, renaming files, organizing into directories, converting formats, inserting into disk images
- ❌ **Don't use build scripts for**: Simple file downloads that can be used as-is
- 💡 **Many systems don't need build scripts** - if the downloaded files are already in the correct format and location, omit the `build_script` field

**How it works:**
1. User selects packs in web UI
2. **Download Phase (automatic)**: System downloads all sources referenced by selected packs
3. **Build Phase (optional)**: If `build_script` is specified, runs to process downloaded files (extract, organize, transform)
4. Content is ready in the filestore for FUSE to present

### 2. Configuration Parsing
**File:** `app/config.py`

Added dataclasses and parsing:
```python
@dataclass
class Pack:
    id: str
    name: str
    description: str
    estimated_size: str
    build_script: Optional[str] = None

@dataclass
class SystemConfig:
    name: str
    manufacturer: str
    canonical_name: str
    local_base_path: str
    packs: list[Pack]

def get_system_config(client_name: str, system_name: str, path="transfs.yaml") -> Optional[SystemConfig]:
    # Parses YAML and returns system with packs
```

### 3. API Endpoints
**File:** `app/api.py`

#### GET `/api/clients/{client_name}/systems/{system_name}/packs`
Returns available packs for a system:
```json
{
  "system": "Archie",
  "manufacturer": "Acorn",
  "canonical_name": "Archimedes",
  "packs": [
    {
      "id": "minimal",
      "name": "Minimal Starter Set",
      "description": "Essential BIOS files...",
      "estimated_size": "10MB",
      "has_build_script": true
    }
  ]
}
```

#### POST `/api/clients/{client_name}/systems/{system_name}/install-packs`
Installs selected packs (streams output):
```json
{
  "client": "MiSTer",
  "system": "Archie",
  "pack_ids": ["minimal", "best-of-best"],
  "skip_existing": true
}
```

**Response:** Streaming text/plain with build script output

### 4. Web UI
**File:** `app/templates/index.html`

Added third column for pack selection:
- Shows packs when client + system selected
- Checkboxes for multi-select
- Displays name, description, and size
- "Install Packs" button triggers installation
- XSS protection via `escapeHtml()` function

**UX Flow:**
1. User selects one client
2. User selects one system
3. Packs auto-load in third column
4. User checks multiple packs
5. User clicks "Install Packs"
6. Progress streams to log window

### 5. Build Scripts
**Files:** `app/build_scripts/MiSTer/Acorn/Archimedes/`

Created example scripts demonstrating pack pattern:
- `build_minimal.sh` - Minimal pack
- `build_best.sh` - Best of the Best pack
- `build.sh` - Full collection (updated with deduplication)

**Environment Variables Provided:**
- `BASE_PATH` - Base directory for system files
- `PACK_ID` - ID of pack being installed
- `PACK_NAME` - Name of pack
- `SKIP_EXISTING` - "1" to skip existing files, "0" to overwrite

**Deduplication Pattern:**
```bash
download_if_needed() {
    local url="$1"
    local dest="$2"
    
    if [ "$SKIP_EXISTING" = "1" ] && [ -f "$dest" ]; then
        echo "⏭ Skipping (exists): $(basename "$dest")"
        return 0
    fi
    
    echo "⬇ Downloading: $(basename "$dest")"
    wget -q -O "$dest" "$url"
}
```

## Pack Design Principles

### 1. Independent Packs
Packs are not necessarily incremental. Examples:
- Regional: "EU titles", "JP titles", "US titles"
- Curated: "Minimal", "Best of the Best", "Hidden Gems"
- Complete: "Full Collection", "Everything"

### 2. Multi-Select Support
Users can install multiple packs simultaneously:
- Install "Minimal" to test, then add "Best of the Best" later
- Install "EU titles" + "JP titles" together
- Mix any combination

### 3. Optional Build Scripts
- Each pack can have 0 or 1 build script
- Packs without scripts are metadata-only (for future use)
- Multiple packs can share the same build script if needed

### 4. Optional Deduplication
- Build scripts check `SKIP_EXISTING` environment variable
- When "1", skip files that already exist
- When "0", overwrite existing files
- Prevents re-downloading when installing multiple packs

## Security

### XSS Protection
All user-facing data is sanitized via `escapeHtml()`:
- Client names
- System names
- Pack names, descriptions, sizes

### Backend Security Notes
Added security notice in `api.py`:
- Path Traversal: Paths from trusted YAML config
- SSRF: URLs from trusted archive_sources config
- SSL Verification: May be disabled for legacy sources
- **DO NOT expose to untrusted networks**

## Testing Recommendations

1. **Unit Tests:**
   - `get_system_config()` parsing
   - Pack dataclass validation
   - API endpoint responses

2. **Integration Tests:**
   - Multi-pack installation
   - Deduplication behavior
   - Build script environment variables

3. **UI Tests:**
   - Pack loading on selection
   - Multi-select functionality
   - Progress streaming

## Future Enhancements

1. **Pack Dependencies:**
   - `requires: ["minimal"]` in YAML
   - Auto-select dependencies in UI

2. **Download Progress:**
   - Per-pack progress bars
   - Total size calculations

3. **Pack Verification:**
   - Checksums in YAML
   - Verify after installation

4. **Pack Marketplace:**
   - Community-contributed packs
   - Ratings and reviews

## Migration Path

Existing systems without `packs` defined continue to work with legacy download/build endpoints. To migrate:

1. Add `packs` array to system definition in YAML
2. Create pack-specific build scripts (or reuse existing)
3. Test pack installation via UI
4. Document pack descriptions and sizes

## Example: Adding Packs to New System

Add packs sources: [boot-rom]
          build_script: build_scripts/MiSTer/NewManufacturer/NewSystem/starter.sh
        - id: games-action
          name: Action Games
          description: Fast-paced arcade action
          estimated_size: 150MB
          sources: [action-games-pack]
          # No build_script - downloaded files are already organized correctly!
        - id: games-rpg
          name: RPG Games
          description: Role-playing adventures
          estimated_size: 300MB
          sources: [rpg-games-pack, dlc-pack]
          build_script: build_scripts/MiSTer/NewManufacturer/NewSystem/rpg.sh
      sources:
        - name: boot-rom
          type: ddl
          url: https://example.com/newsystem-bios.zip
        - name: action-games-pack
          type: ddl
          url: https://example.com/action-games.zip
        - name: rpg-games-pack
          type: ddl
          url: https://example.com/rpg-games.zip
        - name: dlc-pack
          type: ddl
          url: https://example.com/dlc
          description: Fast-paced arcade action
          estimated_size: 150MB
          build_script: build_scripts/MiSTer/NewManufacturer/NewSystem/action.sh
        - id: games-rpg
          name: RPG Games
          description: Role-playing adventures
          estimated_size: 300MB
          build_script: build_scripts/MiSTer/NewManufacturer/NewSystem/rpg.sh
      sources:
        - name: archive-site
          type: ddl
          url: https://example.com/newsystem.zip

clients:
  - name: MiSTer
    systems:
      - name: NewSystem
        manufacturer: NewManufacturer
        cananonical_system_name: "New System"
        local_base_path: NewManufacturer/NewSystem
        maps:
          - boot.rom:
              default_source:
                source_filename: Software/BIOS/boot.rom
```

Then create corresponding build scripts that check `SKIP_EXISTING` and download/extract appropriate files.

## Virtual Directory Mapping with `...SoftwareArchives...`

### Overview
The `...SoftwareArchives...` mapping creates virtual directories based on file type extensions. This allows different clients to see only the file types they support, even when the physical filesystem contains many different formats.

### How It Works

**Physical Layout:**
```
Native/Acorn/Archimedes/Software/
├── HDF/           # Hard disk files
│   └── game.hdf
├── ADF/           # Floppy disk files
│   └── app.adf
└── ROM/           # ROM files
    └── system.rom
```

**Client Configuration:**
```yaml
- name: Archie
  maps:
    - ...SoftwareArchives...:
        source_dir: Software     # Base directory for all software
        supports_zip: false
        filetypes:
          - HDs: HDF            # Virtual "HDs" dir shows files from Software/HDF/
          - FDs: ADF            # Virtual "FDs" dir shows files from Software/ADF/
```

**Virtual Filesystem Result:**
```
/mnt/transfs/MiSTer/Archie/
├── HDs/           # Maps to Software/HDF/
│   └── game.hdf
└── FDs/           # Maps to Software/ADF/
    └── app.adf
```

### Key Principles

1. **Virtual Name → Physical Extension**: Each filetype entry maps a virtual directory name (e.g., `HDs`) to a physical file extension (e.g., `HDF`)

2. **Path Construction**: The system constructs paths as:
   ```
   source_dir / PHYSICAL_EXTENSION / [subpath/]filename.PHYSICAL_EXTENSION
   ```
   For example: `Software/HDF/game.hdf` appears as `HDs/game.hdf`

3. **Client-Specific Views**: Different clients can have different filetype mappings for the same physical files:
   ```yaml
   # MiSTer sees HDF as "HDs"
   - HDs: HDF
   
   # Another emulator might see HDF as "Disks"
   - Disks: HDF
   ```

4. **Empty Subpath Handling**: When accessing just the virtual directory (e.g., `/MiSTer/Archie/HDs`), the system checks if the physical directory (`Software/HDF/`) exists and returns it as the source path.

### Important Notes

- **Don't confuse with direct directory mapping**: This is NOT a simple directory rename. It's a dynamic mapping based on file extensions.
- **Multiple extensions**: A virtual directory can map to multiple physical extensions if needed
- **The physical directories must exist**: Create `Software/HDF/`, `Software/ADF/`, etc. in your source configuration
- **Case matters**: File extensions in `filetypes` are converted to uppercase for matching (e.g., `HDF` not `hdf`)

### Debugging

If a virtual directory doesn't appear:
1. Check FUSE logs: `docker logs transfs | grep readdir`
2. Verify physical directory exists: `docker exec transfs ls /mnt/filestorefs/Native/{path}/Software/HDF`
3. Confirm mapping syntax: Virtual name before colon, extension after
4. Restart container to reload configuration: `docker-compose restart`

