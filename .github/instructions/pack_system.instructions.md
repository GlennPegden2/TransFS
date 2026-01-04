---
alwaysApply: true
trigger: always_on
applyTo: "app/{api,config}.py"
description: Pack-Based Software Distribution System
---

# Pack System Architecture

## Design Principles

### 1. Separation of Concerns

**Sources (archive_sources)** = WHAT content exists and WHERE to get it
**Packs** = WHICH sources to download together
**Clients** = HOW to present content via FUSE

```
Sources → Downloaded by Packs → Presented by Clients
```

### 2. Configuration Location

✅ **Packs defined in:** `config/sources/{Manufacturer}/{System}.yaml`
❌ **Not in:** `config/clients.yaml` (that's for presentation only)

**Why:** Multiple clients can use same packs with different FUSE mappings.

### 3. Source-Level Extraction

**Modern Pattern (Preferred):**
```yaml
sources:
  - name: game-pack
    url: https://example.com/games.7z
    folder: Software/HDF
    extract: "*.hdf"        # Auto-extract matching files, remove archive
```

**Benefits:**
- Downloads and extracts in single operation
- No post_process steps needed
- Archive automatically removed after extraction
- Simpler configuration

**Options:**
- `extract: true` - Extract entire archive
- `extract: "*.ext"` - Extract files matching pattern
- `extract_from_archive: [file1, file2]` - Extract specific files (legacy)

### 4. Pack Structure

```yaml
packs:
  - id: unique-id                    # Unique identifier
    name: Display Name               # Shown in UI
    description: User description    # What's included
    estimated_size: 250MB            # Human-readable size
    sources: [source1, source2]      # Which sources to download
    info_links:                      # Optional documentation links
      - label: Link Name
        url: https://...
    post_process: [...]              # Optional: Only if extraction isn't enough
```

### 5. Info Links Feature

**Purpose:** Provide documentation/context for pack content

**Configuration:**
```yaml
info_links:
  - label: "Setup Guide"
    url: "https://docs.example.com/setup"
  - label: "Source Project"  
    url: "https://github.com/..."
```

**Display:** Renders as clickable links below pack description in UI

**Implementation:**
- Stored in Pack dataclass (`app/config.py`)
- Passed through API (`app/api.py` line ~180)
- Rendered in UI (`app/templates/index.html`)

### 6. Pack Installation Flow

```
User selects packs → API reads sources → Download files → Extract (if configured) → Ready
```

**No build_script needed** if:
- Files download to correct location
- Source-level extraction handles archives
- No format conversion required

**Use post_process only** for:
- Complex multi-step operations
- Moving files between directories
- Operations beyond simple extraction

### 7. API Integration

**Key Functions (app/config.py):**
```python
get_system_config(client, system)  # Returns SystemConfig with packs
  → Loads from config/sources/{Manufacturer}/{System}.yaml
  → Creates Pack objects with all fields (including info_links)
```

**Key Endpoints (app/api.py):**
```python
GET  /clients/{client}/systems/{system}/packs  # List available packs
POST /clients/{client}/systems/{system}/install-packs  # Install selected packs
```

### Common Mistakes to Avoid

❌ Defining packs in clients.yaml (wrong location)
❌ Using post_process for simple extraction (use source-level extract)
❌ Forgetting to pass info_links through Pack constructor
❌ Hardcoding paths instead of using base_path

✅ Define packs in sources YAML files
✅ Use source-level extract: "*.ext" for automatic extraction
✅ Include all Pack fields when constructing from YAML
✅ Use relative paths and let system resolve base_path

### Testing Packs

1. Check API returns pack with all fields:
   ```bash
   curl http://localhost:8000/api/clients/MiSTer/systems/Archie/packs
   ```

2. Verify info_links appear in response

3. Test installation and check FUSE mount shows files

4. Verify extraction worked and archives removed (if using extract)
