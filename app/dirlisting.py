import os
from pathlib import Path
from filetypes import get_filetype_maps
from pathutils import find_software_archive_entry

def parse_trans_path(config,root,full_path: str) -> list:
    """
    Return directory entries for the given virtual path, using get_source_path for translation.
    Supports dynamic expansion of ...SoftwareArchives... maps, including subfolders and zip logic.
    """
    path = Path(full_path)
    root_parts = Path(root).parts
    lev = len(path.parts) - len(root_parts)

    if lev == 0:
        return list_clients(config)
    if lev == 1:
        return list_systems(config, path, root_parts)
    if lev == 2:
        return list_maps(config, path, root_parts)
    return list_dynamic_or_regular(config, path, root_parts)

def list_clients(config) -> list:
    """List all clients."""
    return [client['name'] for client in config['clients']]

def list_systems(config, path: Path, root_parts: tuple) -> list:
    """List all systems for a client."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    return [system['name'] for system in client['systems']]

def list_maps(config, path: Path, root_parts: tuple) -> list:
    """List all maps and dynamic SoftwareArchives for a system."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    system_name = path.parts[len(root_parts) + 1]
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    maps = []
    mapped_names = set()
    for map_entry in system['maps']:
        map_name = list(map_entry.keys())[0]
        mapped_names.add(map_name)
        if map_name == "...SoftwareArchives...":
            filetypes = map_entry[map_name].get("filetypes", [])
            for filetype in filetypes:
                for ft_name in filetype.keys():
                    maps.append(ft_name)
                    mapped_names.add(ft_name)
        else:
            maps.append(map_name)
    # Add any real files/dirs in the real directory that aren't mapped
    real_dir = os.path.join(
        config.get("filestore", "/mnt/filestorefs"),
        "Native",
        system['local_base_path']
    )
    if os.path.isdir(real_dir):
        for entry in os.listdir(real_dir):
            if entry not in mapped_names and not entry.startswith('.'):
                maps.append(entry)
    return maps

def list_dynamic_or_regular(config, path: Path, root_parts: tuple) -> list:
    """List dynamic SoftwareArchives subfolders and their contents, or regular map subfolders."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    system_name = path.parts[len(root_parts) + 1]
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    map_name = path.parts[len(root_parts) + 2]
    sa_entry = find_software_archive_entry(system)
    if sa_entry and is_dynamic_map(config,map_name, sa_entry):
        return list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)
    return list_regular_map(config,path, root_parts, system, map_name)

def is_dynamic_map(config, map_name: str, sa_entry: dict) -> bool:
    """Check if the map is a dynamic ...SoftwareArchives... map."""
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    for filetype in filetypes:
        if map_name in filetype:
            return True
    return False

def list_dynamic_map(
    self, path: Path, root_parts: tuple, system: dict, sa_entry: dict, map_name: str
) -> list:
    """
    List files and directories for a dynamic ...SoftwareArchives... map,
    handling extension mapping and zip flattening.
    """
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
    source_dir = os.path.join(
        self.config["filestore"],
        "Native",
        system["local_base_path"],
        sa_entry["...SoftwareArchives..."]["source_dir"]
    )
    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])
    subpath = path.parts[len(root_parts) + 3:]
    entries = set()
    for real_ext in real_exts:
        dir_path = os.path.join(source_dir, real_ext, *subpath)
        if os.path.isdir(dir_path):
            for entry in os.listdir(dir_path):
                if entry.startswith('.'):
                    continue
                entry_path = os.path.join(dir_path, entry)
                # Handle directories
                if os.path.isdir(entry_path):
                    entries.add(entry)
                # Handle zip files
                elif entry.lower().endswith('.zip'):
                    try:
                        namelist = self._list_zip_file(entry_path)
                        # Only files with the correct extension (case-insensitive)
                        filtered = [
                            n for n in namelist
                            if n.upper().endswith(f".{real_ext.upper()}")
                        ]
                        if len(filtered) == 1:
                            # Flatten: show the file directly in this folder
                            zname = filtered[0]
                            name, ext = os.path.splitext(os.path.basename(zname))
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                        elif len(filtered) > 1:
                            # Show the zip as a folder
                            entries.add(entry)
                    except Exception:
                        # If zip is bad, just show as a file
                        entries.add(entry)
                else:
                    # Regular file: check extension case-insensitively
                    name, ext = os.path.splitext(entry)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
    return sorted(entries)

def list_regular_map(config, path: Path, root_parts: tuple, system: dict, map_name: str) -> list:
    """List contents of a regular map subfolder."""
    map_entry = next((m for m in system['maps'] if list(m.keys())[0] == map_name), None)
    if not map_entry:
        return []
    mapdict = map_entry[map_name]
    if "source_dir" in mapdict:
        base = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system['local_base_path'],
            mapdict["source_dir"]
        )
        subpath = path.parts[len(root_parts) + 3:]
        dir_path = os.path.join(base, *subpath)
        if os.path.isdir(dir_path):
            return sorted(os.listdir(dir_path))
    return []
