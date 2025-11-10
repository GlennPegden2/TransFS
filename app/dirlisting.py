import os
from pathlib import Path
from filetypes import get_filetype_maps
from pathutils import find_software_archive_entry
# from ziptutils import list_zip_file
from zippath import listdir as zippath_listdir, exists as zippath_exists, isfile as zippath_isfile


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
    # Track top-level virtual directories (e.g., "MMBs" from "MMBs/beeb1_mmb.VHD")
    virtual_dirs = set()
    # Track source directories used by ...SoftwareArchives... to exclude them from listing
    excluded_dirs = set()
    
    # Find SoftwareArchives source_dir
    sa_entry = find_software_archive_entry(system)
    if sa_entry:
        source_dir = sa_entry["...SoftwareArchives..."].get("source_dir")
        if source_dir:
            excluded_dirs.add(source_dir)
    
    for map_entry in system['maps']:
        map_name = list(map_entry.keys())[0]
        # If map_name contains '/', extract the top-level directory
        if '/' in map_name:
            top_dir = map_name.split('/')[0]
            virtual_dirs.add(top_dir)
            mapped_names.add(top_dir)
        else:
            mapped_names.add(map_name)
        if map_name == "...SoftwareArchives...":
            filetypes = map_entry[map_name].get("filetypes", [])
            for filetype in filetypes:
                for ft_name in filetype.keys():
                    maps.append(ft_name)
                    mapped_names.add(ft_name)
        else:
            # Only add top-level entries (not nested paths)
            if '/' not in map_name:
                maps.append(map_name)
    # Add virtual directories
    maps.extend(virtual_dirs)
    # Add any real files/dirs in the real directory that aren't mapped
    real_dir = os.path.join(
        config.get("filestore", "/mnt/filestorefs"),
        "Native",
        system['local_base_path']
    )
    if os.path.isdir(real_dir):
        for entry in os.listdir(real_dir):
            if entry not in mapped_names and entry not in excluded_dirs and not entry.startswith('.'):
                maps.append(entry)
    return maps

def list_nested_map_entries(config, path: Path, root_parts: tuple, system: dict, parent_path: str) -> list:
    """
    List entries within a virtual directory that contains nested maps.
    E.g., for /MiSTer/BBCMicro/MMBs, list beeb1_mmb.VHD, beeb2_mmb.VHD
    """
    entries = []
    prefix = parent_path + '/'
    for map_entry in system['maps']:
        map_name = list(map_entry.keys())[0]
        if map_name.startswith(prefix):
            # Extract the immediate child name
            remainder = map_name[len(prefix):]
            if '/' in remainder:
                # It's a nested path; add the directory component
                entries.append(remainder.split('/')[0])
            else:
                # It's a direct child file
                entries.append(remainder)
    return sorted(set(entries))

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
    
    # Check if this is a virtual directory containing nested maps
    nested = list_nested_map_entries(config, path, root_parts, system, map_name)
    if nested:
        return nested
    
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
    config, path: Path, root_parts: tuple, system: dict, sa_entry: dict, map_name: str
) -> list:
    """
    List files and directories for a dynamic ...SoftwareArchives... map,
    handling extension mapping and zip flattening.
    """
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
    source_dir = os.path.join(
        config["filestore"],
        "Native",
        system["local_base_path"],
        sa_entry["...SoftwareArchives..."]["source_dir"]
    )
    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])
    subpath = path.parts[len(root_parts) + 3:]
    entries = set()

    # Include explicit 'files' entries from the YAML for this map (e.g. HDs: MMB/...zip/.../BEEB.MMB)
    for file_spec in sa_entry["...SoftwareArchives..."].get("files", []):
        items = []
        if isinstance(file_spec, dict):
            for k, v in file_spec.items():
                # If the dict key targets this map, prefer those entries first
                if k == map_name:
                    if isinstance(v, list):
                        items.extend(v)
                    else:
                        items.append(v)
                else:
                    # also accept values even if key != map_name (robustness)
                    if isinstance(v, list):
                        items.extend(v)
                    else:
                        items.append(v)
        elif isinstance(file_spec, str):
            items.append(file_spec)

        for item in items:
            try:
                base = os.path.basename(item)
                name, ext = os.path.splitext(base)
                if ext:
                    ext_no = ext[1:]
                    # Normalize extension using reverse_map if it matches one of this map's real_exts
                    matched = False
                    for real_ext in real_exts:
                        if ext_no.upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                            matched = True
                            break
                    if not matched:
                        entries.add(base)
                else:
                    entries.add(base)
            except Exception:
                # be tolerant of malformed YAML entries
                continue

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
                        # use zippath layer to list contents of the zip
                        namelist = zippath_listdir(entry_path)
                        # Only files with the correct extension (case-insensitive)
                        filtered = [
                            n for n in namelist
                            if n.upper().endswith(f".{real_ext.upper()}")
                        ]
                        # Flatten: show each file directly in this folder
                        for zname in filtered:
                            name, ext = os.path.splitext(os.path.basename(zname))
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
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
