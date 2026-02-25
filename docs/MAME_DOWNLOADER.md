# MAME Software Downloader

TransFS includes an integrated MAME Software List downloader that automatically downloads verified software from the Internet Archive based on official MAME hash files.

## Overview

The MAME downloader:
- **Parses official MAME hash XMLs** from the MAME GitHub repository
- **Downloads individual files** from the 70GB Internet Archive MAME collection
- **Verifies checksums** (SHA1) to ensure file integrity
- **Filters software** by publisher, year, and support status
- **Caches hash files** locally to minimize GitHub requests
- **Integrates seamlessly** with existing pack/downloader system

## Configuration

### App-Level Configuration

In `app/config/app.yaml`:

```yaml
mame:
  # GitHub repository for MAME hash files
  hash_repo_url: https://raw.githubusercontent.com/mamedev/mame/master/hash
  hash_repo_branch: master
  
  # Internet Archive MAME Software List collection (NOT arcade ROMs)
  # Files are stored in nested ZIP structure: archive.zip/{softwarelist}/{software}.zip
  archive_base_url: https://archive.org/download/MAME_0.228_Software_List_ROMs_merged/MAME_0.228_Software_List_ROMs_merged.zip
  
  # Local download directory
  download_root: /mnt/filestorefs/Downloads/MAME
  
  # Checksum verification
  verify_checksums: true
  
  # Performance tuning
  max_concurrent_downloads: 3
  
  # Cache hash XMLs locally
  cache_hash_files: true
```

### System-Level Configuration

In system source YAML files (e.g., `app/config/sources/default/Acorn/Atom.yaml`):

```yaml
sources:
  # Regular DDL sources
  - name: MameBIOSroms
    type: ddl
    urls:
      - "https://example.com/atom.zip"
    folder: Software/BIOS
    extract: false

  # MAME Software List source
  - name: "Atom MAME Software"
    type: mame
    system: "atom"  # Matches atom_*.xml hash files from MAME repo
    
    media_types:
      - type: "cass"  # Downloads from atom_cass.xml
        target_folder: "Software/MAME/Cassettes"
      
      - type: "flop"  # Downloads from atom_flop.xml
        target_folder: "Software/MAME/Floppies"
      
      - type: "rom"   # Downloads from atom_rom.xml
        target_folder: "Software/MAME/ROMs"
    
    filters:
      # Only download from specific publishers
      publishers: ["Acornsoft", "Bug Byte", "Program Power"]
      
      # Skip unsupported software (supported="no" in XML)
      exclude_unsupported: true
      
      # Year range filter
      year_range: [1980, 1990]
```

The MAME source integrates with the existing `sources` array using `type: mame`, allowing consistent management alongside DDL, torrent, and other source types.

## Hash File Format

MAME hash files are XML files containing software metadata. Example from `atom_cass.xml`:

```xml
<software name="galaxian" supported="no">
  <description>Galaxian (12K)</description>
  <year>1981</year>
  <publisher>Bug Byte</publisher>
  <part name="cass1" interface="atom_cass">
    <dataarea name="cass" size="4106">
      <rom 
        name="galaxian(bugbyte).hq.uef" 
        size="4106" 
        crc="da761b61" 
        sha1="88fd7efe9a4defa2e593ec713070081e30dfad8f"
      />
    </dataarea>
  </part>
</software>
```

Each `<software>` entry contains:
- **Unique ID** (`name` attribute)
- **Description** (human-readable name)
- **Year** and **Publisher** (optional)
- **Support status** (`supported="no"` means untested/non-working)
- **ROM files** with `name`, `size`, `crc`, and `sha1` for verification

## API Endpoints

### Get Configured Systems

```http
GET /mame/systems
```

Returns all systems with MAME sources configured:

```json
{
  "systems": [
    {
      "config_file": "/app/config/sources/default/Acorn/Atom.yaml",
      "system_path": "Acorn",
      "mame_sources": [...]
    }
  ],
  "total": 1
}
```

### Get Download Status

```http
GET /mame/status
```

Returns download directory statistics:

```json
{
  "exists": true,
  "download_root": "/mnt/filestorefs/Downloads/MAME",
  "total_files": 1234,
  "total_size_bytes": 52428800,
  "total_size_mb": 50.0
}
```

### Download Specific Software

```http
POST /mame/download
Content-Type: application/json

{
  "system": "atom",
  "media_type": "cass",
  "target_folder": "Software/MAME/Cassettes",
  "filters": {
    "publishers": ["Acornsoft"],
    "exclude_unsupported": true,
    "year_range": [1980, 1990]
  }
}
```

Response:

```json
{
  "status": "completed",
  "stats": {
    "total_entries": 94,
    "filtered_entries": 12,
    "total_files": 12,
    "downloaded": 8,
    "already_existed": 4,
    "failed": 0,
    "downloaded_bytes": 52428800
  }
}
```

### Download All Configured

```http
POST /mame/download-all
```

Downloads all software defined in `mame_sources` across all systems.

### Preview Hash File Entries

```http
GET /mame/hash/atom/cass
```

Returns parsed software entries without downloading:

```json
{
  "system": "atom",
  "media_type": "cass",
  "total_entries": 94,
  "entries": [
    {
      "software_name": "galaxian",
      "description": "Galaxian (12K)",
      "year": "1981",
      "publisher": "Bug Byte",
      "supported": false,
      "interface": "atom_cass",
      "rom_files": [
        {
          "name": "galaxian(bugbyte).hq.uef",
          "size": 4106,
          "crc": "da761b61",
          "sha1": "88fd7efe9a4defa2e593ec713070081e30dfad8f"
        }
      ]
    }
  ]
}
```

## Usage Examples

### Download Acorn Atom Cassettes

1. **Configure** in `Atom.yaml`:
   ```yaml
   sources:
     - name: "Atom Cassettes"
       type: mame
       system: "atom"
       media_types:
         - type: "cass"
           target_folder: "Software/MAME/Cassettes"
       filters:
         exclude_unsupported: true
   ```

2. **Trigger download** via API:
   ```bash
   curl -X POST http://localhost:8000/api/mame/download \
     -H "Content-Type: application/json" \
     -d '{
       "system": "atom",
       "media_type": "cass",
       "target_folder": "Software/MAME/Cassettes",
       "filters": {"exclude_unsupported": true}
     }'
   ```

3. **Files downloaded** to:
   ```
   /mnt/filestorefs/Downloads/MAME/Software/MAME/Cassettes/
   ├── galaxian(bugbyte).hq.uef
   ├── adventure(programpower).hq.uef
   └── ...
   ```

### Filter by Publisher

Download only Acornsoft titles:

```yaml
filters:
  publishers: ["Acornsoft"]
  exclude_unsupported: true
```

### Filter by Year Range

Download classic era software:

```yaml
filters:
  year_range: [1980, 1985]
```

## Checksum Verification

All downloads are verified using:
1. **Size check** (fast) - compares file size to expected size
2. **SHA1 checksum** (thorough) - verifies file integrity

If verification fails, the file is deleted and marked as failed in statistics.

## Caching

Hash files are cached in `app/config/mame_cache/` to minimize GitHub requests:
- First request fetches from GitHub
- Subsequent requests use cached copy
- Configure with `cache_hash_files: true` in `app.yaml`

## Finding Hash Files

All MAME hash files are in the official repository:
https://github.com/mamedev/mame/tree/master/hash

File naming convention: `{system}_{media_type}.xml`

Examples:
- `atom_cass.xml` - Acorn Atom cassettes
- `atom_flop.xml` - Acorn Atom floppies
- `atom_rom.xml` - Acorn Atom ROM cartridges
- `apple2_flop_clcracked.xml` - Apple II cracked disks
- `bbc_cass.xml` - BBC Micro cassettes

## Integration with TransFS

Downloaded MAME software integrates seamlessly:

1. **Database Sync**: Downloaded files are automatically added to the database during sync
2. **Virtual Filesystem**: Files appear in TransFS mount points
3. **Metadata**: Can apply metadata rulesets like regular sources
4. **Client Filtering**: Works with client-specific maps and filtering

## Troubleshooting

### Hash File Not Found

Error: `Hash file not found for {system}_{media_type}`

**Solution**: Check that the hash file exists in the MAME repository:
https://github.com/mamedev/mame/tree/master/hash

Not all systems have all media types (e.g., `atom_cart.xml` doesn't exist).

### Download Fails

Error: `Download failed for {filename}`

**Possible causes**:
1. File doesn't exist in Internet Archive collection
2. Network connectivity issues
3. Archive URL changed

**Solution**: Verify archive URL in `app.yaml` is current.

### Checksum Mismatch

Warning: `SHA1 mismatch for {filename}`

**Cause**: Downloaded file is corrupt or archive version doesn't match hash file version.

**Solution**: 
1. Delete cached hash file: `rm app/config/mame_cache/{system}_{media_type}.xml`
2. Re-download

## Limitations

- **Archive version**: Hash files and archive must match versions (both MAME 0.228 in default config)
- **Large downloads**: Some systems have 100s of files - downloads may take time
- **Internet Archive quirks**: Direct file access inside zip archives works but isn't officially documented

## Future Enhancements

Potential improvements:
- **Resume support**: Resume interrupted downloads
- **Parallel downloads**: Download multiple files simultaneously (currently sequential)
- **Progress tracking**: Real-time progress updates via WebSocket
- **UI integration**: Web UI for browsing and triggering downloads
- **Auto-update**: Periodic hash file refresh to get new software

## Technical Details

### Module Structure

```
app/mame/
├── __init__.py         # Package exports
├── hash_parser.py      # Parse MAME hash XML files
├── downloader.py       # Download and verify files
└── manager.py          # Orchestrate downloads, manage state
```

### Download Flow

1. **Fetch hash file** from GitHub (or cache)
2. **Parse XML** to extract software entries and software list name
3. **Apply filters** (publisher, year, support status)
4. **Check existing files** (skip already downloaded)
5. **Download nested ZIP** from Internet Archive (`{softwarelist}/{software}.zip`)
6. **Extract ROM files** from downloaded ZIP
7. **Verify checksums** (size + SHA1)
8. **Report statistics** (downloaded, existing, failed)

### Internet Archive URL Pattern

The MAME Software List archive uses a **nested ZIP structure**:

```
MAME_0.228_Software_List_ROMs_merged.zip/
  ├── atom_cass/
  │   ├── 747.zip              (contains: 747(bugbyte).hq.uef)
  │   ├── adventre.zip          (contains: adventure(programpower).hq.uef)
  │   └── ...
  ├── atom_flop/
  └── ...
```

The downloader:
1. Builds URL to nested ZIP: `{archive_base_url}/{softwarelist}%2F{software}.zip`
2. Downloads the ZIP file into memory
3. Extracts individual ROM files from the ZIP
4. Verifies checksums on extracted files

Example URL:
```
https://archive.org/download/MAME_0.228_Software_List_ROMs_merged/MAME_0.228_Software_List_ROMs_merged.zip/atom_cass%2F747.zip
```

This downloads the `atom_cass/747.zip` file, which contains the actual ROM file `747(bugbyte).hq.uef`.

## References

- **MAME Hash Files**: https://github.com/mamedev/mame/tree/master/hash
- **Internet Archive MAME Collection**: https://archive.org/details/MAME_0.228_Software_List_ROMs_merged
- **MAME Documentation**: https://docs.mamedev.org/
