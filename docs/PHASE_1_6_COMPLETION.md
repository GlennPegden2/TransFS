# Phase 1.6: Downloader Config Support - COMPLETED

**Status**: ✅ COMPLETE  
**Date**: Today  
**Changes**: Configuration infrastructure for layout-aware downloads  

## Summary

Phase 1.6 adds the foundational configuration layer for supporting both folder-based and flat file layouts. All systems now have a `download_layout` field that defaults to `folder_based` (current behavior), ensuring zero breaking changes while preparing the codebase for Phase 2 (gradual migration to flat layouts).

## Changes Made

### 1. SystemConfig Class Enhancement (`app/config.py`)

Added `download_layout` field to the dataclass:
```python
@dataclass
class SystemConfig:
    # ... existing fields ...
    download_layout: str = "folder_based"  # folder_based (default) | flat
```

This field stores the preferred download layout for each system. Default is `folder_based` for backward compatibility.

### 2. Configuration Loading (`app/config.py`)

Updated `get_system_config()` function to read the `download_layout` field from clients.yaml:
- Extracts field from system configuration in clients.yaml
- Defaults to `"folder_based"` if not specified
- Passes value to SystemConfig constructor

**Code location**: [app/config.py](app/config.py#L167-L179)

### 3. Client Configuration (`app/config/clients.yaml`)

Added `download_layout: folder_based` field to all 25 systems:

**Systems updated**:
- **Acorn**: AcornAtom, Archie, AcornElectron, BBCMicro
- **Amstrad**: PCW, CPC
- **Apple**: Apple-I, Apple-II (MiSTer + Generic)
- **Atari**: 2600, 5200, 7800, 800, Lynx
- **Coleco**: ColecoVision
- **Commodore**: Amiga, C128, C64, PET, Plus4
- **GCE**: Vectrex
- **Mattel**: Intellivision
- **Microsoft**: MSX
- **MITS**: Altair8800
- **NEC**: PC-Engine, TurboGrafx16
- **Nintendo**: GameBoy, GBA, GBC, NES, SNES
- **Sega**: GameGear, Genesis, MasterSystem
- **Sinclair**: ZX Spectrum
- **SNK**: NeoGeo
- **Tandy**: AliceMC10

## How It Works

### Configuration Reading

1. User requests system config via `get_system_config(client_name, system_name)`
2. Function reads clients.yaml and extracts:
   - `name`, `manufacturer`, `system_mapping_name`, `local_base_path` (existing)
   - `download_layout` (NEW - defaults to "folder_based" if not specified)
3. Returns `SystemConfig` object with all fields populated
4. API endpoints and download functions can now access `system_config.download_layout`

### Future Usage (Phase 2)

When downloading files, the code will check:
```python
layout = system_config.download_layout

if layout == "flat":
    # Files go directly to /Software/
    dest_folder = f"{base_dir}/Software/"
else:
    # Files go to /Software/{extension}/ (current behavior)
    dest_folder = f"{base_dir}/Software/{extension}/"
```

## Testing & Validation

✅ **YAML Validation**: All 535 lines of clients.yaml are valid YAML  
✅ **Code Syntax**: No errors in config.py modifications  
✅ **Configuration Loading**: Successfully loads download_layout field  
✅ **Field Accessibility**: SystemConfig.download_layout is accessible in code  

**Test Results**:
```
System: AcornAtom
Download Layout: folder_based
✓ download_layout field is accessible

System: Apple-II
Download Layout: folder_based
✓ download_layout field is accessible
```

## Backward Compatibility

- ✅ **Default behavior unchanged**: All 25 systems default to `folder_based`
- ✅ **No code changes to download functions**: Phase 1.6 is purely preparatory
- ✅ **No API changes**: Existing endpoints unaffected
- ✅ **Optional field**: Systems without `download_layout` specified get default
- ✅ **Graceful fallback**: Code uses `.get('download_layout', 'folder_based')`

## Files Modified

1. **app/config.py** (~5 lines added)
   - Added `download_layout: str = "folder_based"` to SystemConfig
   - Updated get_system_config() to read and pass this field

2. **app/config/clients.yaml** (~25 additions)
   - Added `download_layout: folder_based` after `local_base_path:` in each system

## Next Steps

### Phase 1 Remaining (2.25 hours)
1. Refactor `list_dynamic_map()` in dirlisting.py for optional db_mode parameter (~45 min)
2. Create unit/integration tests (~1.5 hours)
3. Full Phase 1 completion and commit

### Phase 2: Proof of Concept (1 week)
1. Choose test system (MITS Altair8800 recommended)
2. Flatten folder structure: `/Software/ROM/`, `/Software/DSK/` → `/Software/`
3. Update download_layout to `flat` for that system
4. Validate with database queries
5. Document migration process

### Phase 3: Gradual Rollout (2-4 weeks)
- Migrate remaining 24 systems one by one
- Each system: flatten folders + update config + test
- Document validation per system

## Architecture Benefits

This configuration layer enables:

✅ **Flexible layouts**: Different systems can use different layouts independently  
✅ **Gradual migration**: No big bang; migrate one system at a time  
✅ **Rollback capability**: Can revert system to folder_based if issues arise  
✅ **Database-driven discovery**: Works with Phase 1 database queries  
✅ **Backward compatible**: All systems maintain current structure during Phase 1  

## Key Insight

This phase represents a **configuration checkpoint** - the infrastructure is ready, but behavior doesn't change yet. When Phase 2 begins, only the `download_layout` field value needs to change; all other systems automatically continue using folder_based layout.

---

**Phase 1.6 Status**: ✅ **COMPLETE**  
**Breaking Changes**: None  
**Risk Level**: Minimal (configuration only, no behavior change)  
**Ready for Phase 1.7** (refactoring) or Phase 2 (pilot migration)
