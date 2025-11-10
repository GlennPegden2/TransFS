import os
from pathlib import Path
from typing import Any, Optional
import zipfile
from pathutils import get_client, get_system_info, find_software_archive_entry
from filetypes import get_filetype_maps
from ziptutils import get_zip_mapping
from zippath import exists as zippath_exists, isfile as zippath_isfile, listdir as zippath_listdir

def get_source_path(logger, config, root, translated_path: str) -> Optional[Any]:
    """
    Given a translated path (as seen under the FUSE mount), return the corresponding
    source path in the filestore, using the translation logic from TransFS.
    Supports dynamic ...SoftwareArchives... mapping, including zip-as-folder logic and filetype mapping.
    """

    logger.debug(f"DEBUG: get_source_path({translated_path}) called")

    path = Path(translated_path)
    root_parts = Path(root).parts
    rel_parts = path.parts[len(root_parts):]

    if not rel_parts:
        return config.get("filestore", "/mnt/filestorefs")
    if rel_parts[0] == "Native":
        # Map /Native to /mnt/filestorefs/Native
        return os.path.join(config.get("filestore", "/mnt/filestorefs"), "Native", *rel_parts[1:])

    client = get_client(config, rel_parts)
    if not client:
        return None

    if len(rel_parts) == 1:
        return config.get("filestore", "/mnt/filestorefs")

    path_template_parts = Path(client['default_target_path']).parts
    system_info = get_system_info(
        client, list(rel_parts), path_template_parts
    )
    if not system_info:
        return None

    # Try dynamic SoftwareArchives first
    dynamic_result = get_dynamic_source_path(config, system_info, rel_parts)
    if dynamic_result is not None:
        return dynamic_result

    # Handle named maps (including nested paths like MMBs/beeb1_mmb.VHD)
    if len(rel_parts) >= 3:
        # Support nested map names by joining remaining parts
        map_path_parts = rel_parts[2:]
        # Try progressively longer paths to find a matching map
        for i in range(len(map_path_parts), 0, -1):
            map_name = '/'.join(map_path_parts[:i])
            map_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == map_name), None)
            if not map_entry:
                continue
            mapdict = map_entry[map_name]
            # subpath is everything after the matched map name
            subpath = map_path_parts[i:]
            
            # If default_source->source_filename is present, return the mapped file
            ds = mapdict.get('default_source') or {}
            if "source_filename" in ds:
                source_filename = ds["source_filename"]
                # Check if source_filename uses zippath-style notation (path.zip/internal/file)
                zip_match = _parse_zippath_notation(source_filename)
                if zip_match is not None:
                    zip_file, internal_path = zip_match
                    base = os.path.join(
                        config.get("filestore", "/mnt/filestorefs"),
                        "Native",
                        system_info['local_base_path'],
                        zip_file
                    )
                    if zippath_isfile(f"{base}/{internal_path}"):
                        logger.debug(f"Using zippath-style source: {internal_path} in {base}")
                        return (base, internal_path)
                    else:
                        logger.debug(f"zippath-style file {internal_path} not found in {base}")
                    return None
                
                base = os.path.join(
                    config.get("filestore", "/mnt/filestorefs"),
                    "Native",
                    system_info['local_base_path'],
                    source_filename
                )
                unzip = ds.get("unzip", False)
                if base.lower().endswith('.zip') and unzip:
                    zip_internal_file = ds.get("zip_internal_file")
                    if zip_internal_file:
                        # use zippath to test for entry existence
                        if zippath_isfile(f"{base}/{zip_internal_file}"):
                            logger.debug(f"Using explicit zip_internal_file: {zip_internal_file} in {base}")
                            return (base, zip_internal_file)
                        else:
                            logger.debug(f"zip_internal_file {zip_internal_file} not found in {base}")
                        return None
                    else:
                        # fallback to existing mapping helper
                        # Use the last component of map_name for matching
                        match_name = map_name.split('/')[-1]
                        result = get_zip_mapping(logger, base, match_name)
                        logger.debug(f"ZIP mapping result for {map_name} in {base}: {result}")
                        if result:
                            return result
                        return None
                # Only return a real file path if it exists
                if os.path.exists(base):
                    logger.debug(f"Returning named map file path: {base}")
                    return base
                else:
                    logger.debug(f"Named map file {base} does not exist, returning None")
                    return None
            # If we matched a map but it has no source_filename, continue to next iteration
            break

    # Try regular map logic
    regular_result = get_regular_source_path(logger, config, system_info, rel_parts)
    if regular_result is not None:
        return regular_result

    # Fallback: just join filestore, local_base_path, and the rest
    base = os.path.join(
        config.get("filestore", "/mnt/filestorefs"),
        "Native",
        system_info['local_base_path']
    )
    # Always join all remaining rel_parts after the system name
    # Find the index of the system name in rel_parts
    try:
        sys_idx = rel_parts.index(system_info['name'])
    except ValueError:
        sys_idx = 1  # fallback, but should always be present
    subpath = rel_parts[sys_idx+1:]
    return os.path.join(base, *subpath) if subpath else base

def _parse_zippath_notation(path_str: str) -> Optional[tuple[str, str]]:
    """
    Parse zippath-style notation like 'Software/MMB/BEEB2.zip/BEEB.MMB'
    Returns (zip_path, internal_path) if a .zip component is found, else None.
    """
    parts = path_str.split('/')
    for i, part in enumerate(parts):
        if part.lower().endswith('.zip'):
            zip_path = '/'.join(parts[:i+1])
            internal_path = '/'.join(parts[i+1:]) if i+1 < len(parts) else ''
            return (zip_path, internal_path) if internal_path else None
    return None

def get_dynamic_source_path(config, system_info: dict, rel_parts: tuple) -> Optional[Any]:
    """Handle ...SoftwareArchives... dynamic folders with zip logic and filetype mapping."""

# Pretty sure this is redundant now
    if "...SoftwareArchives..." not in [list(m.keys())[0] for m in system_info['maps']]:
        return None

#    if len(rel_parts) < 4:
#        return None
    if len(rel_parts) < 3:
        return None

    map_name = rel_parts[2]
    sa_entry = find_software_archive_entry(system_info)
    if not sa_entry:
        return None

    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])

    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
    source_dir = os.path.join(
        config["filestore"],
        "Native",
        system_info["local_base_path"],
        sa_entry["...SoftwareArchives..."]["source_dir"]
    )
    subpath = rel_parts[3:]
    if not subpath:
        return None

    # If the last component has no extension, treat as a virtual directory
    last = subpath[-1]
    if '.' not in last:
        # Check if any real directory exists for this virtual directory
        for real_ext in real_exts:
            dir_path = os.path.join(source_dir, real_ext, *subpath)
            if os.path.isdir(dir_path):
                return dir_path  # This allows getattr/readdir to work
        # If no real dir, treat as virtual dir (return None, getattr will fake stat)
        return None

    # if is a mapped filetype
    filename = subpath[-1]
    name, virt_ext = os.path.splitext(filename)
    virt_ext = virt_ext[1:].upper()
    for real_ext in real_exts:
        real_filename = f"{name}.{real_ext.lower()}"
        real_path = os.path.join(source_dir, real_ext, *subpath[:-1], real_filename)
        if os.path.exists(real_path):
            return real_path



# Suspect this is not needed now
#         # Check for file in zip files in the real_ext directory
#        parent_dir = os.path.join(source_dir, real_ext, *subpath[:-1])
#        if os.path.isdir(parent_dir):
#            for entry in os.listdir(parent_dir):
#                if entry.lower().endswith('.zip'):
#                    zip_path = os.path.join(parent_dir, entry)
#                    with zipfile.ZipFile(zip_path, 'r') as zf:
#                        for zname in zf.namelist():
#                            if zname.split('/')[-1] == real_filename:
#                                return (zip_path, zname)
    return None

def get_regular_source_path(logger, config, system_info: dict, rel_parts: tuple) -> Optional[Any]:
    """Handle regular map logic."""
    if len(rel_parts) < 3:
        return None
    map_name = rel_parts[2]
    map_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == map_name), None)
    if not map_entry:
        return None
    mapdict = map_entry[map_name]
    subpath = rel_parts[3:]
    if "source_dir" in mapdict:
        base = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system_info['local_base_path'],
            mapdict["source_dir"]
        )
        if not subpath:
            # Only return the real directory if it exists, else treat as virtual
            if os.path.isdir(base):
                logger.debug(f"DEBUG: _get_regular_source_path returns real dir for map root: {base}")
                return base
            else:
                logger.debug(f"DEBUG: _get_regular_source_path returns None for virtual dir (map root): {base}")
                return None
        real_path = os.path.join(base, *subpath)
        if os.path.exists(real_path):
            logger.debug(f"DEBUG: _get_regular_source_path returns real path: {real_path}")
            return real_path
        else:
            logger.debug(f"DEBUG: _get_regular_source_path returns None for missing path: {real_path}")
            return None
    if "source_filename" in mapdict:
        base = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system_info['local_base_path'],
            mapdict["source_filename"]
        )
        unzip = mapdict.get("unzip", False)
        if base.lower().endswith('.zip') and unzip:
            zip_internal_file = mapdict.get("zip_internal_file")
            if zip_internal_file:
                if zippath_isfile(f"{base}/{zip_internal_file}"):
                    logger.debug(f"Using explicit zip_internal_file: {zip_internal_file} in {base}")
                    return (base, zip_internal_file)
                else:
                    logger.debug(f"zip_internal_file {zip_internal_file} not found in {base}")
                return None
            else:
                map_name = rel_parts[2]
                result = get_zip_mapping(logger, base, map_name)
                logger.debug(f"ZIP mapping result for {map_name} in {base}: {result}")
                if result:
                    return result
                return None
        # Only return a real file path if it exists
        real_path = os.path.join(base, *subpath) if subpath else base
        if os.path.exists(real_path):
            logger.debug(f"Returning real file path: {real_path}")
            return real_path
        else:
            logger.debug(f"File {real_path} does not exist, returning None")
            return None

    if "default_source" in mapdict:
        ds = mapdict["default_source"]
        if "source_dir" in ds:
            base = os.path.join(
                config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                ds["source_dir"]
            )
            if not subpath:
                if os.path.isdir(base):
                    logger.debug(f"DEBUG: _get_regular_source_path returns real dir for map root (default_source): {base}")
                    return base
                else:
                    logger.debug(f"DEBUG: _get_regular_source_path returns None for virtual dir (default_source map root): {base}")
                    return None
            real_path = os.path.join(base, *subpath)
            if os.path.exists(real_path):
                logger.debug(f"DEBUG: _get_regular_source_path returns real path (default_source): {real_path}")
                return real_path
            else:
                logger.debug(f"DEBUG: _get_regular_source_path returns None for missing path (default_source): {real_path}")
                return None
        if "source_filename" in ds:
            base = os.path.join(
                config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                ds["source_filename"]
            )
            unzip = ds.get("unzip", False)
            if base.lower().endswith('.zip') and unzip:
                zip_internal_file = ds.get("zip_internal_file")
                if zip_internal_file:
                    if zippath_isfile(f"{base}/{zip_internal_file}"):
                        logger.debug(f"Using explicit zip_internal_file: {zip_internal_file} in {base}")
                        return (base, zip_internal_file)
                    else:
                        logger.debug(f"zip_internal_file {zip_internal_file} not found in {base}")
                    return None
                else:
                    # Try to match by virtual filename
                    map_name = rel_parts[2]
                    result = get_zip_mapping(logger, base, map_name)
                    logger.debug(f"ZIP mapping result for {map_name} in {base}: {result}")
                    if result:
                        return result
                    return None
            # Only return a real file path if it exists AND we are not handling a zip mapping
            if not (base.lower().endswith('.zip') and unzip):
                real_path = os.path.join(base, *subpath) if subpath else base
                if os.path.exists(real_path):
                    logger.debug(f"Returning real file path: {real_path}")
                    return real_path
                else:
                    logger.debug(f"File {real_path} does not exist, returning None")
                    return None
            return None
