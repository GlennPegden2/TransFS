import os
from pathlib import Path
from typing import Optional

def full_path(root: str, partial: str) -> str:
    """Convert a FUSE path to a full path in the filestore."""
    if partial.startswith("/"):
        partial = partial[1:]
    return os.path.join(root, partial)

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
    # /MiSTer/ARCHIE
    if len(rel_parts) == 2:
        client = next((c for c in config.get("clients", []) if c.get("name") == rel_parts[0]), None)
        if client and any(sys.get("name") == rel_parts[1] for sys in client.get("systems", [])):
            return True
    # /MiSTer/ARCHIE/FDs or /MiSTer/ARCHIE/HDs
    if len(rel_parts) >= 3:
        client = next((c for c in config.get("clients", []) if c.get("name") == rel_parts[0]), None)
        if client:
            system = next((s for s in client.get("systems", []) if s.get("name") == rel_parts[1]), None)
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
                    # Check for ...SoftwareArchives... filetypes
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
    system_name = None
    if "{system_name}" in path_template_parts:
        idx = path_template_parts.index("{system_name}")
        if len(rel_parts) > idx:
            system_name = rel_parts[idx]
    else:
        for sys in client['systems']:
            if sys['name'] in rel_parts:
                system_name = sys['name']
                break
    return next((s for s in client['systems'] if s['name'] == system_name), None)

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
    client_name, system_name = parts[0], parts[1]
    client = next((c for c in config.get('clients', []) if c['name'] == client_name), None)
    if not client:
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
