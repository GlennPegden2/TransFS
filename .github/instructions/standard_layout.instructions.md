---
alwaysApply: false
trigger: configuring new systems
applyTo: "app/config/**"
description: Standard Folder Layout and Configuration Pattern
---

# Standard TransFS Folder Layout and Configuration Pattern

## Overview
This document defines the standard folder structure and configuration pattern for TransFS systems. Following this pattern ensures consistency, predictable behavior, and easier troubleshooting.

## Physical Filesystem Layout (Native)

```
content/Native/
└── {Manufacturer}/
    └── {System}/
        └── Software/
            ├── {EXTENSION1}/     # e.g., MMB, SSD, ADF, HDF, UEF, etc.
            │   └── file1.ext
            │   └── file2.ext
            ├── {EXTENSION2}/
            │   └── file3.ext
            └── BIOS/             # Optional: BIOS/ROM files
                └── rom.bin
```

**Example (BBC Micro):**
```
content/Native/Acorn/BBC_B/Software/
├── MMB/
│   ├── higgy_mmbeeb-v1.2.zip
│   └── BEEB.mmb
├── SSD/
│   ├── Elite.ssd
│   ├── ChuckieEgg.ssd
│   └── Thrust.ssd
└── BIOS/
    └── boot.rom
```

## Virtual Filesystem Layout (MiSTer/Client)

```
/mnt/transfs/
└── {Client}/              # e.g., MiSTer
    └── {SystemName}/      # e.g., BBCMicro
        ├── boot.vhd       # Optional: Default boot file
        ├── FDs/           # Virtual folder: Floppy Disks
        │   └── game.ssd   # Files aggregated from multiple extensions
        ├── HDs/           # Virtual folder: Hard Disks
        │   └── image.mmb  # Files aggregated from multiple extensions
        └── Tapes/         # Virtual folder: Tapes (if applicable)
            └── program.uef
```

**Key Principle:** Virtual folders (FDs, HDs, Tapes) aggregate files by **usage type**, not by physical extension. The mapping configuration determines which extensions appear in which virtual folders.

## Configuration Pattern

### 1. clients.yaml Configuration

```yaml
clients:
  - name: MiSTer
    systems:
      - name: {SystemName}          # e.g., BBCMicro
        manufacturer: {Manufacturer}  # e.g., Acorn
        cananonical_system_name: {CanonicalName}  # e.g., BBC Micro
        local_base_path: {Manufacturer}/{System}/  # e.g., Acorn/BBC_B/
        maps:
          - boot.vhd:                # Optional: Default boot file
              default_source:
                source_filename: Software/MMB/boot.mmb
          - ...SoftwareArchives...:
              supports_zip: false
              source_dir: Software   # Points to Software subdirectory
              filetypes:
              - FDs: SSD,DSD         # Virtual folder FDs shows SSD and DSD files
              - HDs: MMB,VHD         # Virtual folder HDs shows MMB and VHD files
              - Tapes: UEF           # Virtual folder Tapes shows UEF files
```

**Critical Rules:**
- `local_base_path` must be `{Manufacturer}/{System}/` (NO "Software/")
- `source_dir` must be `Software` to point to the Software subdirectory
- Virtual folder names (FDs, HDs, Tapes) are **user-defined** and should reflect usage
- Extension lists are **comma-separated, case-insensitive**

### 2. sources/{Manufacturer}/{System}.yaml Configuration

```yaml
# {System} Software Sources

base_path: {Manufacturer}/{System}/  # MUST match local_base_path from clients.yaml

sources:
  - name: example_download
    type: ddl
    url: https://example.com/file.zip
    folder: {EXTENSION}     # e.g., MMB, SSD - creates Software/{EXTENSION}/ subdirectory
    extract: true           # Optional: Auto-extract archives

packs:
  - id: example_pack
    name: Example Pack
    description: Description of the pack
    estimated_size: 100MB
    sources: [example_download]
    build_script: MiSTer/{Manufacturer}/{System}/build.sh  # Optional
```

**Critical Rules:**
- `base_path` MUST exactly match `local_base_path` from clients.yaml
- `folder` specifies the extension-based subdirectory under Software/
- Downloads will be placed at: `{filestore}/Native/{base_path}/Software/{folder}/`

### 3. Build Scripts (Optional)

Located at: `app/build_scripts/{Client}/{Manufacturer}/{System}/build.sh`

**Environment Variables Available:**
- `BASE_PATH`: Full path to system's base directory (e.g., `/mnt/filestorefs/Native/Acorn/BBC_B/`)
- `PACK_ID`: ID of the pack being installed
- `PACK_NAME`: Name of the pack
- `SKIP_EXISTING`: "1" if skip_existing is enabled, "0" otherwise

**Standard Pattern:**
```bash
#!/bin/bash
set -e

echo "Build Script for {System}"

SOFTWARE_DIR="${BASE_PATH}Software/"
echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Your build logic here
# Files are already downloaded to $SOFTWARE_DIR/{EXTENSION}/
```

## Path Resolution Examples

### Example 1: BBC Micro

**clients.yaml:**
```yaml
local_base_path: Acorn/BBC_B/
source_dir: Software
```

**BBC Micro.yaml:**
```yaml
base_path: Acorn/BBC_B/
sources:
  - name: beeb_games
    folder: SSD
```

**Download Destination:**
```
/mnt/filestorefs/Native/Acorn/BBC_B/Software/SSD/
```
Calculation: `{filestore}/Native/{base_path}Software/{folder}/`

**Virtual Filesystem Lookup:**
```
/mnt/transfs/MiSTer/BBCMicro/FDs/game.ssd
```
Maps to physical: `/mnt/filestorefs/Native/Acorn/BBC_B/Software/SSD/game.ssd`
Calculation: `{filestore}/Native/{local_base_path}{source_dir}/SSD/`

### Example 2: Acorn Atom

**clients.yaml:**
```yaml
local_base_path: Acorn/Atom/
source_dir: Software
```

**Atom.yaml:**
```yaml
base_path: Acorn/Atom/
sources:
  - name: hoglet67
    folder: VHD
```

**Download Destination:**
```
/mnt/filestorefs/Native/Acorn/Atom/Software/VHD/
```

**Virtual Filesystem Lookup:**
```
/mnt/transfs/MiSTer/AcornAtom/HDs/hoglet.vhd
```
Maps to physical: `/mnt/filestorefs/Native/Acorn/Atom/Software/VHD/hoglet.vhd`

## Common Issues and Solutions

### Issue: Physical subdirectories (MMB, SSD) showing in virtual filesystem
**Cause:** `source_dir` set to `.` instead of `Software`, causing physical structure to leak through
**Solution:** Set `source_dir: Software` in clients.yaml

### Issue: Downloads going to wrong location (outside Software/)
**Cause:** `base_path` in sources yaml doesn't match `local_base_path` in clients.yaml
**Solution:** Ensure both values are identical (without "Software/")

### Issue: Virtual folders empty despite files existing
**Cause:** Files in wrong physical location, or source_dir pointing to wrong place
**Solution:** 
1. Verify files are in `{Manufacturer}/{System}/Software/{EXTENSION}/`
2. Verify `source_dir: Software` in clients.yaml
3. Restart container to refresh filesystem

### Issue: Build script receives wrong BASE_PATH
**Cause:** `local_base_path` misconfigured
**Solution:** Verify `local_base_path` ends with `/` and doesn't include "Software/"

## Validation Checklist

When configuring a new system, verify:

- [ ] Physical files are in `content/Native/{Manufacturer}/{System}/Software/{EXTENSION}/`
- [ ] `clients.yaml` has `local_base_path: {Manufacturer}/{System}/`
- [ ] `clients.yaml` has `source_dir: Software`
- [ ] `{System}.yaml` has `base_path: {Manufacturer}/{System}/`
- [ ] `base_path` matches `local_base_path` exactly
- [ ] Sources specify `folder: {EXTENSION}` to create proper subdirectories
- [ ] Virtual filesystem shows only virtual folders (FDs, HDs, Tapes), not physical ones (MMB, SSD, etc.)
- [ ] Files appear in virtual folders when browsing `/mnt/transfs/{Client}/{SystemName}/`

## Non-Standard Configurations

While the above represents the standard pattern, alternative configurations are possible:

**Alternative: Flat Structure (Not Recommended)**
- `local_base_path: {Manufacturer}/{System}/Software/`
- `source_dir: .`
- Creates flat structure but exposes physical subdirectories in virtual filesystem

**Alternative: Custom Virtual Folder Names**
- Virtual folder names (FDs, HDs, Tapes) can be customized per system
- Example: `Disks`, `Images`, `Cartridges` instead of generic names

## Summary

**Standard Pattern Formula:**

1. **Physical:** `Native/{Manufacturer}/{System}/Software/{EXTENSION}/`
2. **Virtual:** `{Client}/{SystemName}/{VirtualFolder}/`
3. **Config Alignment:** `base_path` == `local_base_path` == `{Manufacturer}/{System}/`
4. **Source Directory:** Always `source_dir: Software` in clients.yaml
5. **Folder Mapping:** Sources specify `folder: {EXTENSION}` to create subdirectories

Following this pattern ensures predictable behavior across all systems and simplifies troubleshooting.
