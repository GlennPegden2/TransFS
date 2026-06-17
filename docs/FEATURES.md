# FEATURES.md

## TransFS: Feature & Behavior Reference

## VFS Documentation Index

- [docs/VFS_CONTENTS.md](VFS_CONTENTS.md)
- [docs/MAPPING_AND_FILTERING.md](MAPPING_AND_FILTERING.md)

### 1. Virtual Filesystem Structure

- The FUSE mount presents a virtual filesystem at `/mnt/transfs`.
- Structure:
  ```
  /mnt/transfs/<client>/<system>/<map>/<subfolders/files>
  ```
  - `<client>`: As defined in YAML (`name` field).
  - `<system>`: As defined in YAML (`name` field under `systems`).
  - `<map>`: Either a static map name or a dynamic map (e.g. `...SoftwareArchives...` creates virtual folders like `ROM`, `Tape`, etc).

---

### 2. Dynamic ...SoftwareArchives... Maps

- **Virtual folders** (e.g. `ROM`, `Tape`) are created based on the `filetypes` mapping in YAML.
- Each virtual folder can map to one or more real file extensions, and can also remap extensions (e.g. `BIN:ROM` means `.BIN` files appear as `.ROM`).
- **Subfolders** under these virtual folders are mapped to real subfolders under the corresponding extension directory.

---

### 3. File and Folder Listing

- **Directories**: All real subdirectories under the mapped real extension directory are shown as virtual subdirectories.
- **Files**: All files with the mapped real extension are shown, with their extension replaced by the virtual extension if needed.
- **Zip files**:
  - If a zip contains only one relevant file, the file is shown directly in the virtual folder (flattened).
  - If a zip contains multiple relevant files, the zip is shown as a virtual folder. Entering this folder lists the files inside the zip.
- **Hidden files** (starting with `.`) are shown by default (matching standard filesystem behavior). This can be disabled by setting `show_hidden_files: false` in `app.yaml` to hide metadata files like `.DS_Store`, `.git`, etc.

---

### 4. File Access

- **Opening/Stat-ing a virtual file**:
  - If the file is a real file, it is opened directly.
  - If the file is inside a zip, it is extracted to a temp file and opened.
- **Opening/Stat-ing a virtual directory**:
  - If the directory exists in any mapped real extension directory, it is treated as a real directory.
  - Otherwise, a fake stat is returned to allow navigation.

---

### 5. Extension Mapping

- If a `filetypes` entry is `BIN:ROM`, then:
  - All `.BIN` files are shown as `.ROM` in the virtual folder.
  - Opening `TEST.ROM` will open the real file `TEST.BIN`.
- If a `filetypes` entry is just `UEF`, then `.UEF` files are shown as `.UEF`.

---

### 6. Zip Handling

- **Flattening**: If a zip contains only one relevant file, the file appears directly in the virtual folder.
- **Zip as folder**: If a zip contains multiple relevant files, the zip appears as a folder. Entering it lists the files inside.
- **Opening files in zips**: When a virtual file corresponds to a file inside a zip, it is extracted to a temp file for access.

---

### 7. Fallbacks

- If a virtual directory or file does not exist in the real filesystem, a fake stat is returned for directories (to allow navigation), and file access fails as expected for files.

---

### 8. Examples

- `/mnt/transfs/MiSTer/AcornElectron/Tape/Apps/` lists all subfolders and `.UEF` files (real or inside zips) in `/mnt/filestorefs/Native/Acorn/Electron/Software/UEF/Apps/`.
- `/mnt/transfs/MiSTer/AcornElectron/ROM/TEST.ROM` could be backed by `ROM/TEST.ROM`, `BIN/TEST.BIN`, or `HEX/TEST.HEX` in the real filesystem, depending on mapping.

---

### 9. Known Limitations

- Only single-level extension mapping is supported (e.g. `BIN:ROM`).
- Only files with mapped extensions are shown in virtual folders.
- Only zip files in mapped extension directories are handled as described.

---

### 10. Environment 

- Runs on both linux bare metal and as a docker container (wont' run natively on Windows because of reliance on FUSE and wanting to create an SMB server on 445). Samba sharing may not work in Windows-Hosted docker.

---

### 11. Setup Clients Assistant (Web UI)

- A dedicated **Setup Clients** tab provides SMB setup guidance for clients.
- Data is sourced from `/api/setup/connection-profile` and includes:
  - Advertised SMB host/port/share
  - UNC path
  - Windows PowerShell mapping command
  - MiSTer mount example
  - Download link for `setup_windows.ps1`
- Endpoint values can be explicitly overridden via environment variables:
  - `SMB_ADVERTISE_HOST`
  - `SMB_ADVERTISE_PORT`
  - `SMB_ADVERTISE_SHARE`

### 11.1 Native Direct Path Architecture

- Native bypass now uses explicit layers under the SMB `Native` folder:
  - `Native/Systems/<Manufacturer>/<System>/...` for shared system content.
  - `Native/Clients/<Client>/...` for client-specific assets.
- RetroBat BIOS setup script now targets `Native/Clients/RetroBat/bios` (not the virtual FUSE RetroBat path).
- `local_base_path` and source `base_path` values are normalized at load time to `Systems/...` for compatibility.
- Legacy paths under `Native/<Manufacturer>/<System>` are supported during migration through config normalization and staged data move.

### 11.1.1 Browse Native Mount Diagnostics

- **Browse Native now annotates symlinks and native mount-backed folders** directly in the name column.
- A non-clickable `🔗` icon is shown for:
  - real symlinks, with tooltip `Symlink target: ...`
  - direct native mounts, with tooltip `Mount source: ...`
  - ancestor folders that contain a configured descendant native mount, with tooltip `Contains mount source: ...`
- A non-clickable `⚠` icon is shown when a configured native mount has not come up successfully but still affects a visible folder in `Browse Native`.
- Failed mount tooltips include both the configured source and the current error, for example missing credentials or auth failures.
- This works for RetroNAS bridge-backed paths as well as plain filestore-native paths, so `Native/...` browse views still expose mount diagnostics even when the underlying configured target lives outside the visible bridge root.

### 11.1.2 RetroNAS Native Bridge

- In RetroNAS-oriented runtimes, TransFS can create a bridge symlink from the configured filestore root to the RetroNAS canonical Native tree:
  - `/mnt/filestorefs/Native -> /data/retronas/Native`
- This keeps `Browse Native` and TransFS-managed SMB access aligned with the RetroNAS data root without bypassing the native browse model.
- The bridge is created at startup when the target Native directory exists and the link does not already point elsewhere.

### 11.2 Metadata Scanner + Browser (Web UI)

- **Scan workflow moved to Browse Native**: The scanner now runs directly from the **Browse Native** tab so users scan the folder they are already browsing.
- Browse Native includes a **Scan Metadata** toggle panel with:
  - provider selection
  - recursive option
  - **Preview** and **Apply** actions
- The **Metadata** tab is now a metadata-first browser view (database-backed), with:
  - metadata coverage summary
  - search and filter controls
  - paginated metadata entries list
  - inline entry editing for both file context and metadata fields, including:
    - file context: source path, virtual path, original extension, system/client/map/content type, archive flags
    - metadata fields: title, media type, genre, app type, release metadata, publisher/region/language, revision/prototype/homebrew
    - provenance and linkage: metadata provider/source, metadata tags, and pack names
  - advanced safety toggle: core file fields (paths/system/client/map/archive flags) are hidden by default and only editable when **Show advanced file fields** is enabled
- Initial provider types:
  - `filename_ruleset` (existing filename parsing/ruleset behavior)
  - `dat_xml_lookup` (DAT/XML lookup; initial adapter supports MAME software-list XML)
  - `imported_dat_lookup` (manual DAT imports stored in the database and then re-used as scan/apply providers)
- DAT/XML matching strategy in phase 1 is **filename first**, then **checksum fallback** (`sha1`, `crc32`).

### 11.2.1 Manual DAT Importer

- The **Metadata** tab now includes an explicit **DAT Importer** panel.
- Default import root is `/mnt/filestorefs/Native/DATs`, but any readable DAT/XML path can be entered manually.
- The importer:
  - lists DAT/XML files in the selected folder
  - highlights files that are **new** or **changed** since the last import
  - lets the user choose an `xml_format`
  - records imported catalogs in the database
  - stores per-entry filename/path, normalized filename, checksums, and extracted metadata
  - shows live polling-based import logs in the UI while parsing/writing entries
- Imported catalogs become selectable metadata providers via `imported_dat_lookup`.
- This keeps DAT ingestion explicit and reviewable rather than silently re-parsing in the background.

### 11.2.2 DAT-Driven Client Config Generation

- Imported DAT catalogs can generate a new client config file under `config/clients/<config_set>/`.
- Path-bearing DAT entries (for example MiSTer Organizer-style ROM names) are grouped by top-level folder.
- Each top-level path segment becomes a generated `query` map.
- Generated maps use:
  - `source_dir: Software/<top-level-folder>`
  - discovered extensions from the imported DAT
  - `preserve_structure: true`
- The UI prompts for the config set name and target system details before writing the client YAML.

### 11.3 Metadata APIs

- `GET /api/metadata/providers` - List available metadata providers for the active source config set.
- `GET /api/metadata/xml-formats` - List XML/DAT format definitions exposed to the manual importer.
- `GET /api/metadata/dat-files` - List DAT/XML candidates and indicate whether each file is new, changed, or already imported.
- `GET /api/metadata/dat-imports` - List DAT/XML catalogs already imported into the database.
- `POST /api/metadata/dat-import/start` - Start a tracked DAT/XML import job.
- `GET /api/metadata/dat-import/jobs/{job_id}` - Poll live DAT/XML import status and logs.
- `POST /api/metadata/dat-imports/generate-client-config` - Generate/update a client config set from imported DAT path structure.
- `POST /api/metadata/scan-preview` - Preview metadata matches for a selected folder/provider.
- `POST /api/metadata/apply` - Apply metadata matches for a selected folder/provider.
- `GET /api/metadata/stats` - Metadata coverage totals and provider breakdown.
- `GET /api/metadata/entries` - Paginated metadata entry browser with optional filters (`search`, `publisher`, `year`, `tag`, `provider`), returning file context + metadata + tags + pack lineage fields.
- `POST /api/metadata/entry/update` - Update editable metadata/file fields for a single record, including metadata tags and file-pack memberships.

Provider definitions are loaded from:
- `config/metadata/providers/<active_source_config>.yaml` (preferred)
- fallback `config/metadata/providers/default.yaml`

XML format templates are loaded from:
- `config/metadata/xml_formats/<active_source_config>.yaml` (preferred)
- fallback `config/metadata/xml_formats/default.yaml`

Each format entry can declaratively define:
- top-level `item_path` for XML records
- `metadata` field mappings (child paths/attributes, fallback values, value maps, type casts)
- `match.filename` source and normalization strategy
- `match.checksums` nodes and checksum attribute names (`sha1_attr`, `crc_attr`)
- static tags to append to matched metadata

---

### 12. Large-File Read Performance (SMB/FUSE)

- TransFS now supports configurable memory-mapped reads for large files to improve SMB/CIFS performance without bypassing the virtual FUSE layer.
- Configuration keys in `app/config/app.yaml`:
  - `performance.use_mmap_for_reads` (default `true`)
  - `performance.mmap_threshold_bytes` (default `10485760`, i.e. 10MB)
- Read path behavior:
  - Files above threshold use mmap-backed reads.
  - Small files and mmap failures automatically fall back to the safe `os.read()` loop path.
- This keeps the architecture principle intact: download once, present through many virtual layouts.
- Real-world validation completed on MiSTer cores: Acorn Atom, Acorn Archimedes, and Atari 5200.

---

### 12. Database-Only Architecture (Query Maps)

**Overview**: For query map directories (maps defined with `query` configuration), TransFS uses an optimized database-driven file access path that completely bypasses expensive filesystem scanning.

**Supported Operations**:
- **Readdir** (Directory Listing): `query_files_by_client_system_and_map()` returns paginated results from database
  - Example: `ls /mnt/transfs/MiSTer/Apple-II/FDs` queries database for all FD-format files
  - Support: 76+ file pagination, extension filtering, sorted alphabetically
  
- **Getattr** (File Stats): `query_file_by_client_system_map_and_name()` returns file metadata
  - Provides: mtime, size, file mode (read-only), permissions
  - Optimization: Size adjusted for transformed files (e.g., 2MG → DO/HDV conversions)
  
- **Open/Read** (File Access): Database lookup → transform pipeline → source file open
  - Resolves source_path from database record
  - Applies configured transforms (e.g., 2MG header stripping)
  - Direct file handle to underlying source file for reads

**Performance Benefits**:
- Eliminates parse_trans_path overhead (expensive config/filesystem traversal)
- Direct SQLite queries instead of directory scanning
- Cached transform pipeline detection
- Significantly faster for large query maps (420+ file HDs directory)

**Query Map Configuration Example**:
```yaml
maps:
  - FDs:
      query:
        source_dir: Software
        extensions:
          - DSK
          - DO
          - PO
          - 2MG
```

**Verification**: 
- 76 Apple-II FDs files successfully listed and stat'd
- 420 Apple-II HDs files (2MG format) successfully listed and opened
- File integrity test: 143KB file copied bit-for-bit match
- Transform pipelines: 2MG files correctly converted to DO/HDV formats

**Fallback Behavior**: If database query fails, gracefully falls back to filesystem-based resolution (cache/parse_trans_path)

---

### 12. Automatic Filename Deduplication

**Problem**: When the same ROM exists in multiple sources (e.g., DataGhost-Full and RomHunter-Full both containing "Acid Drop.bin"), the filesystem would display duplicate filenames in the same directory, violating POSIX semantics where each file must have a unique name.

**Solution**: TransFS automatically deduplicates filenames at database sync time, ensuring each virtual filename in a directory is unique.

**Default Behavior** (`preserve_exact_filenames: false`): Duplicates are auto-renamed with numeric suffixes:
- `Acid Drop.bin` (from DataGhost-Full)
- `Acid Drop_2.bin` (from RomHunter-Full)
- `Acid Drop_3.bin` (if third source exists)

**Strict Mode** (`preserve_exact_filenames: true`): Only the first occurrence is indexed; duplicates are skipped.
- Useful for systems like MAME that require exact filenames from XML file lists
- Example: RetroBAT FDs map configured with `preserve_exact_filenames: true`

**Configuration**:
```yaml
maps:
  - ROMs:
      query:
        source_dir: Software
        extensions: [BIN]
        # preserve_exact_filenames defaults to false (auto-rename)
  
  - FDs:
      query:
        source_dir: Software
        extensions: [DSK]
        preserve_exact_filenames: true  # MAME-compatible: exact names only
```

**Benefits**:
-  Users can access all ROM variants (default mode)
-  All files remain accessible (renamed, not hidden)
-  Works transparently with no runtime overhead
-  System-specific naming requirements supported (strict mode)
-  Original source files unchanged on disk

**Implementation Details**:
- **When**: During `python3 -m app.sync_database` execution
- **Where**: Virtual filenames in database are deduplicated; source files untouched
- **Cost**: One-time computation during sync, zero runtime overhead
- **Algorithm**: Track filenames per (client, system, map) directory; rename subsequent duplicates with `_N` suffix

**See Also**: [DEDUPLICATION_FEATURE.md](DEDUPLICATION_FEATURE.md) for detailed configuration examples and FAQ.

---

### 13. Query Map Structure Preservation

**Overview**: Query maps can optionally preserve the source directory structure from the database, creating virtual subdirectories instead of flattening all files to the map root.

**Default Behavior** (`preserve_structure: false`): All files are flattened
- Example: `Software/Sources/hoglet67/AA/GALAXIAN.atm` becomes `FDs/GALAXIAN.atm`
- Simple flat file listing, fastest performance
- Best for: Simple ROM collections without meaningful subdirectories

**Structure Preservation Mode** (`preserve_structure: true`): Virtual directories are created from source paths
- Example: `Software/Sources/hoglet67/AA/GALAXIAN.atm` appears as `FDs/Sources/hoglet67/AA/GALAXIAN.atm`
- Directory structure extracted from database `source_path` field
- Shows organized file hierarchy in virtual filesystem
- Best for: Collections organized by author, region, or other meaningful categories

**How It Works**:
1. FUSE reads the `source_path` field from each database record (e.g., `/path/to/Software/Sources/hoglet67/AA/GALAXIAN.atm`)
2. Extracts relative path components based on `source_dir` setting (e.g., `Sources/hoglet67/AA/`)
3. Creates virtual directory entries with proper filesystem attributes (st_mode 0o040555)
4. Files appear with correct parent directories (st_mode 0o100444)

**Configuration Example**:
```yaml
FDs:
  query:
    source_dir: Software
    extensions: [ATM]
    preserve_structure: true  # Enable directory structure preservation
    # Sources, hoglet67, AA are created as virtual directories
    # Files show as FDs/Sources/hoglet67/AA/FILENAME.atm
    
HDs:
  query:
    source_dir: Software
    extensions: [VHD]
    # preserve_structure defaults to false
    # All VHD files flatten to HDs/FILENAME.vhd (no subdirectories)
```

**Performance**:
- Directory structure: 3,197 files → 3,669 total entries (472 virtual directories)
- API response includes both directory and file type indicators
- Traversal still uses database queries, maintaining database-only performance benefits

---

### 14. Runtime Config Reload (No Container Restart)

**Overview**: TransFS supports hot-reloading of configuration changes without unmounting the filesystem or restarting the container. Changes to client/source configuration YAML files can take effect in real-time via API endpoints.

**Two-Tier Reload System**:

1. **Web Service Config Reload** (`/api/config/reload`)
   - Reloads configuration in the web API service only
   - Clears config cache and re-reads YAML files on next request
   - Immediate effect for all HTTP API responses
   - Scope: Web service setup UI, metadata operations, diagnostics

2. **FUSE Process Config Reload** (`/api/fuse/reload-config`)
   - Reloads configuration in the running FUSE filesystem process
   - Sends SIGHUP signal to trigger safe in-process reapply
   - Updates client/source mappings, clears filesystem caches, reinitializes data providers
   - No filesystem unmount or operation disruption
   - Scope: Virtual filesystem node assignments, file path mappings, database settings

**How It Works**:
1. Client modifies YAML configuration files (typically via mounted config volume in Docker)
2. Client calls `/api/config/reload` (web service) and/or `/api/fuse/reload-config` (FUSE)
3. Configuration is re-read from disk and validated
4. FUSE process:
   - Clears all readdir and path caches
   - Resets virtual-to-real path mappings
   - Reinitializes data provider if database settings changed
   - Logs all changes for debugging
5. Active filesystem operations continue without interruption

**Use Cases**:
- **Rapid development**: Test config changes without `docker compose restart`
- **Multi-client setup**: Switch between active client configurations via API
- **Dynamic filtering**: Update include/exclude patterns mid-session
- **Database mode toggle**: Switch between hybrid/enabled/disabled without restart (if supported)

**API Endpoints**:
- `POST /api/config/reload` - Reload web service config
- `POST /api/fuse/reload-config` - Reload FUSE process config with hot-apply via SIGHUP signal

**Limitations**:
- Changes only take effect for *new* filesystem operations
- Files already open by clients may continue using old metadata/paths until closed and reopened
- Source path changes apply only to newly traversed directories (existing cached hierarchy holds old paths temporarily until TTL expires)

**Benefits**:
- Users see organized file hierarchies in the virtual filesystem
- Maintains source directory structure without copying/reorganizing actual files
- Works transparently with file transforms and ZIP handling
- Web UI and mount both reflect the directory structure accurately

**Implementation Details**:
- **Extraction**: Uses `source_dir` from query config as the root reference point
- **Virtual Entries**: Directory nodes created on-demand for each intermediate path
- **File Type Detection**: Sets appropriate inode modes based on path depth and entry type
- **Caching**: Directory listings cached per-map for performance

---

### 12. MAME Software List Downloader

**Overview**: TransFS includes an integrated downloader for MAME Software List ROMs from the Internet Archive, automatically downloading verified software based on official MAME hash files.

**Key Features**:
- **Official MAME hash files** from GitHub for metadata
- **Nested ZIP extraction** from Internet Archive MAME Software List collection
- **SHA1 checksum verification** to ensure file integrity
- **Configurable filters** by publisher, year, and support status
- **Hash file caching** to minimize GitHub requests
- **RESTful API** for programmatic access

**How It Works**:
The Internet Archive stores MAME Software Lists in a nested ZIP structure:
```
MAME_0.228_Software_List_ROMs_merged.zip/
  ├── atom_cass/
  │   ├── 747.zip              (contains: 747(bugbyte).hq.uef)
  │   ├── adventre.zip          (contains: adventure(programpower).hq.uef)
  │   └── ...
```

The downloader:
1. Downloads the specific software ZIP (e.g., `atom_cass/747.zip`)
2. Extracts individual ROM files from within the ZIP
3. Verifies SHA1 checksums on extracted files
4. Only downloads what you need (not the entire 70GB archive)

**Configuration** (in source YAML files):
```yaml
sources:
  - name: "Atom MAME Software"
    type: mame
    system: "atom"  # Matches atom_*.xml hash files
    media_types:
      - type: "cass"  # atom_cass.xml
        target_folder: "Software/MAME/Cassettes"
      - type: "flop"  # atom_flop.xml  
        target_folder: "Software/MAME/Floppies"
      - type: "rom"   # atom_rom.xml
        target_folder: "Software/MAME/ROMs"
    filters:
      publishers: ["Acornsoft", "Bug Byte"]  # Optional
      exclude_unsupported: false  # Include unsupported software (emulation status, not availability)
      year_range: [1980, 1990]  # Optional
```

**Important Notes**:
- The `supported="no"` attribute in MAME hash files refers to **emulation status** in MAME, not file availability
- Set `exclude_unsupported: false` to download all software, regardless of MAME emulation status
- Many systems have incomplete MAME emulation but fully functional files

**API Endpoints**:
- `GET /api/mame/systems` - List systems with MAME sources configured
- `GET /api/mame/status` - Download directory statistics
- `POST /api/mame/download` - Download specific system/media type
- `POST /api/mame/download-all` - Download all configured software
- `GET /api/mame/hash/{system}/{media_type}` - Preview without downloading

**Download Process**:
1. Fetch MAME hash XML from GitHub (e.g., `atom_cass.xml`)
2. Parse software entries (description, publisher, year, checksums)
3. Apply configured filters
4. Download nested ZIP for each software entry from Internet Archive
5. Extract ROM files from the ZIP
6. Verify SHA1 checksums on extracted files
7. Report statistics (downloaded, existing, failed)

**Integration**:
- Downloaded files automatically appear in database sync
- Works with existing virtual filesystem maps
- Supports metadata rulesets like regular sources
- Client filtering applies normally

**Documentation**: See [MAME_DOWNLOADER.md](MAME_DOWNLOADER.md) for full details.

---
