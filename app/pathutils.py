import os
from pathlib import Path
from typing import Optional

def full_path(root: str, partial: str) -> str:
    """Convert a FUSE path to a full path in the filestore."""
    if partial.startswith("/"):
        partial = partial[1:]
    return os.path.join(root, partial)

def is_flatten_map(map_name: str) -> bool:
    """Check if a map name is '.' (flatten into parent)."""
    return map_name == '.'

def is_parent_level_map(map_name: str) -> bool:
    """Check if a map name starts with '../' (parent-level shared resource)."""
    return map_name.startswith('../')

def get_map_display_name(map_name: str) -> str:
    """
    Get the display name for a map (handling special prefixes).
    
    Examples:
        '.' -> '.' (flattened, no subdirectory)
        '../bios/neogeo.zip' -> 'bios/neogeo.zip' (shown at parent level)
        'FDs' -> 'FDs' (normal map)
    """
    return map_name

def resolve_map_display_level(map_name: str, current_level: int) -> int:
    """
    Resolve the directory level where a map should appear.
    
    Args:
        map_name: The map name (may contain ../ prefix)
        current_level: Current directory level (3 for system root)
    
    Returns:
        Directory level where the map should appear
    
    Examples:
        'FDs' at level 3 -> 3 (show as /Client/System/FDs)
        '../bios' at level 3 -> 2 (show as /Client/bios)
        '.' at level 3 -> 3 (files appear directly in system folder)
    """
    if is_parent_level_map(map_name):
        # Count how many ../ levels
        count = 0
        temp = map_name
        while temp.startswith('../'):
            count += 1
            temp = temp[3:]
        return current_level - count
    return current_level

def normalize_map_name(map_name: str) -> str:
    """
    Normalize a map name, removing special prefixes.
    
    Examples:
        '../bios/neogeo.zip' -> 'bios/neogeo.zip'
        '.' -> '.'
        'FDs' -> 'FDs'
    """
    if is_parent_level_map(map_name):
        # Remove all ../ prefixes
        while map_name.startswith('../'):
            map_name = map_name[3:]
        return map_name
    return map_name

def is_virtual_path(config, root: str, full_path: str) -> bool:
    """Determine if a path is a virtual path based on config."""
    parts = Path(full_path).parts
    rel_parts = parts[len(Path(root).parts):]
    # /Native
    if len(rel_parts) == 1 and rel_parts[0] == "Native":
        return True
    # /MiSTer
    if len(rel_parts) == 1 and any(client.get("name") == rel_parts[0] for client in config.get("clients", [])):
        return True
    # /MiSTer/ARCHIE (or display name like /MiSTer/Apple ][)
    if len(rel_parts) == 2:
        client = next((c for c in config.get("clients", []) if c.get("name") == rel_parts[0]), None)
        if client:
            # Check both actual name and display_name
            found = False
            for sys in client.get("systems", []):
                if sys.get("name") == rel_parts[1] or sys.get("display_name") == rel_parts[1]:
                    found = True
                    break
            if found:
                return True
    # /MiSTer/ARCHIE/FDs or /MiSTer/ARCHIE/HDs (or display name variant)
    if len(rel_parts) >= 3:
        client = next((c for c in config.get("clients", []) if c.get("name") == rel_parts[0]), None)
        if client:
            # Resolve the system name (handles both display_name and actual name)
            system_name = None
            for sys in client.get("systems", []):
                if sys.get("name") == rel_parts[1] or sys.get("display_name") == rel_parts[1]:
                    system_name = sys.get("name")
                    break
            
            if system_name:
                system = next((s for s in client.get("systems", []) if s.get("name") == system_name), None)
                if system:
                    # Build the remaining path after system name
                    remaining_path = '/'.join(rel_parts[2:])
                    
                    # Check for direct map or parent directory of a map
                    for map_entry in system.get("maps", []):
                        map_name = list(map_entry.keys())[0]
                        if map_name == remaining_path:
                            return True
                        # Check if remaining_path is a parent directory of map_name
                        # e.g., "HDs" is parent of "HDs/beeb1_mmb.VHD"
                        if map_name.startswith(remaining_path + '/'):
                            return True
                        # Backward compatibility: ...SoftwareArchives... filetypes
                        if map_name == "...SoftwareArchives...":
                            filetypes = map_entry[map_name].get("filetypes", [])
                            for ft in filetypes:
                                if rel_parts[2] in ft.keys():
                                    return True
    return False

def client_exists(config, name_to_check: str) -> bool:
    """Check if a client exists in the config."""
    return any(client.get("name") == name_to_check for client in config.get("clients", []))

def get_system_info(client: dict, rel_parts: list, path_template_parts: tuple) -> Optional[dict]:
    """Extract system info from the config."""
    systems = client.get('systems', []) if client else []
    if not systems:
        return None
    system_name = None
    if "{system_name}" in path_template_parts:
        idx = path_template_parts.index("{system_name}")
        if len(rel_parts) > idx:
            potential_name = rel_parts[idx]
            # Resolve display name to actual name
            system_name = resolve_system_name(client, potential_name)
    else:
        for sys in systems:
            if sys['name'] in rel_parts or sys.get('display_name') in rel_parts:
                system_name = sys['name']
                break
    return next((s for s in systems if s['name'] == system_name), None)

def get_client(config, rel_parts: tuple) -> Optional[dict]:
    """Return the client dict for the given rel_parts."""
    client_name = rel_parts[0]
    return next((c for c in config.get('clients', []) if c['name'] == client_name), None)

def is_system_root(path):
    """e.g. /MiSTer/ARCHIE or /MiSTer/AcornAtom"""
    parts = path.strip("/").split("/")
    return len(parts) == 2  # ["MiSTer", "ARCHIE"]

def map_virtual_to_real(config, path, filestore_root="/mnt/filestorefs"):
    """Map a virtual path to a real path in the filestore."""
    from pathlib import Path
    import os
    parts = Path(path.lstrip("/")).parts
    if len(parts) < 2:
        return None
    client_name, display_or_actual_name = parts[0], parts[1]
    client = next((c for c in config.get('clients', []) if c['name'] == client_name), None)
    if not client:
        return None
    
    # Resolve display name to actual system name
    system_name = resolve_system_name(client, display_or_actual_name)
    if not system_name:
        return None
    
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return None
    base = os.path.join(
        config.get("filestore", filestore_root),
        "Native",
        system['local_base_path']
    )
    if len(parts) > 2:
        real_path = os.path.join(base, *parts[2:])
        return real_path
    return base

def find_software_archive_entry(system_info: dict) -> Optional[dict]:
    """Find the ...SoftwareArchives... entry in a system's maps."""
    return next((m for m in system_info['maps'] if list(m.keys())[0] == "...SoftwareArchives..."), None)

def find_map_entry(system_info: dict, map_name: str) -> Optional[dict]:
    """Find a map entry by map name."""
    return next((m for m in system_info.get('maps', []) if list(m.keys())[0] == map_name), None)

def get_map_config(map_entry: Optional[dict]) -> Optional[dict]:
    """Return the config dict for a map entry."""
    if not map_entry:
        return None
    key = list(map_entry.keys())[0]
    return map_entry.get(key)

def is_query_map(map_config: Optional[dict]) -> bool:
    """Check whether a map is a query-based map."""
    return isinstance(map_config, dict) and "query" in map_config

def get_query_config(map_config: Optional[dict]) -> dict:
    """Return query config for a map (if present)."""
    if not isinstance(map_config, dict):
        return {}
    return map_config.get("query", {}) or {}

def get_map_transforms(map_config: Optional[dict]) -> dict:
    """Return transform config for a map (if present)."""
    if not isinstance(map_config, dict):
        return {}
    if "transforms" in map_config and isinstance(map_config["transforms"], dict):
        return map_config["transforms"]
    query_cfg = map_config.get("query", {}) if isinstance(map_config, dict) else {}
    if isinstance(query_cfg, dict) and "transforms" in query_cfg:
        return query_cfg.get("transforms") or {}
    return {}

def get_map_extension_map(map_config: Optional[dict]) -> dict:
    """Return extension remap dict (real->virtual) for a map if present."""
    if not isinstance(map_config, dict):
        return {}
    if "extension_map" in map_config and isinstance(map_config["extension_map"], dict):
        return map_config["extension_map"]
    query_cfg = map_config.get("query", {}) if isinstance(map_config, dict) else {}
    if isinstance(query_cfg, dict) and "extension_map" in query_cfg:
        return query_cfg.get("extension_map") or {}
    return {}

def resolve_system_name(client: dict, potential_name: str) -> Optional[str]:
    """
    Resolve a display name back to the actual system name.
    If the name matches display_name or name, return the actual name.
    """
    if not client:
        return None
    
    for system in client.get('systems', []):
        # Check both display_name and name
        if (system.get('display_name') == potential_name or 
            system.get('name') == potential_name):
            return system.get('name')
    
    return None

def get_system_identifier(system_info: dict) -> Optional[str]:
    """Return system identifier in Manufacturer/System format for database lookups."""
    if not system_info:
        return None
    manufacturer = system_info.get("manufacturer") or ""
    canonical = system_info.get("system_mapping_name") or system_info.get("cananonical_system_name") or system_info.get("name") or ""
    if not manufacturer or not canonical:
        return None
    return f"{manufacturer}/{canonical}"
