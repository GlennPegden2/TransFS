import os
from pathlib import Path
from typing import Any, Optional, Union
import zipfile
from pathutils import (
    get_client,
    get_system_info,
    find_software_archive_entry,
    find_map_entry,
    get_map_config,
    get_map_transforms,
    get_map_extension_map,
    is_query_map,
    get_query_config,
)
from filetypes import get_filetype_maps, get_filetype_transforms
from ziptutils import get_zip_mapping
from zippath import exists as zippath_exists, isfile as zippath_isfile, listdir as zippath_listdir
from transforms import build_transform_pipeline, TransformPipeline


_transform_pipeline_cache: dict[tuple[str, str, str], Optional[TransformPipeline]] = {}


def _get_transform_cache_key(system_info: dict, virtual_folder: str, ext: str) -> tuple[str, str, str]:
    manufacturer = system_info.get("manufacturer", "")
    canonical = system_info.get("system_mapping_name") or system_info.get("cananonical_system_name", "")
    return (f"{manufacturer}/{canonical}", virtual_folder, ext)

def get_transform_pipeline_for_file(
    logger,
    system_info: dict,
    filename: str,
    virtual_folder: str,
    cache_config: Optional[dict] = None,
    full_path: Optional[str] = None,  # Full file path for reading actual file content
) -> Optional[TransformPipeline]:
    """
    Get transformation pipeline for a file based on its extension and virtual folder.
    
    Args:
        logger: Logger instance
        system_info: System configuration dict
        filename: File name (e.g., "game.dsk")
        virtual_folder: Virtual folder name (e.g., "Disks")
    
    Returns:
        TransformPipeline if transforms are configured for this file type, else None
    """
    # Prefer transforms from query map if available
    map_entry = find_map_entry(system_info, virtual_folder)
    map_config = get_map_config(map_entry)
    transform_map = get_map_transforms(map_config)
    if not transform_map:
        # Fallback to legacy SoftwareArchives transforms
        sa_entry = find_software_archive_entry(system_info)
        if not sa_entry:
            return None
        transform_map = get_filetype_transforms(sa_entry)
    if not transform_map:
        return None
    
    cache_config = cache_config or {}
    pipeline_cache_enabled = cache_config.get("transform_pipeline_cache_enabled", True)
    output_size_cache_enabled = cache_config.get("transform_output_size_cache_enabled", True)

    # Extract file extension
    _, ext = os.path.splitext(filename)
    ext = ext[1:].upper()  # Remove dot and uppercase
    
    # Check if transforms are configured for this extension
    if ext not in transform_map:
        return None

    cache_key = None
    # Note: Only use cache for generic pipelines (e.g., during initialization)
    # When we have a real full_path, we need to rebuild to trigger detection
    use_cache = pipeline_cache_enabled and not full_path
    if use_cache:
        cache_key = _get_transform_cache_key(system_info, virtual_folder, ext)
        if cache_key in _transform_pipeline_cache:
            return _transform_pipeline_cache[cache_key]
    
    # Build transform pipeline
    transform_specs = transform_map[ext]
    try:
        # Use full_path if provided for actual file operations, otherwise use filename
        pipeline_path = full_path if full_path else filename
        pipeline = build_transform_pipeline(pipeline_path, transform_specs)
        logger.debug(f"Built transform pipeline for {filename}: {pipeline}")
        if pipeline and output_size_cache_enabled and not hasattr(pipeline, "_output_size_cache"):
            try:
                setattr(pipeline, "_output_size_cache", {})
            except Exception:
                pass
        if use_cache and cache_key:
            _transform_pipeline_cache[cache_key] = pipeline
        return pipeline
    except Exception as e:
        logger.error(f"Failed to build transform pipeline for {filename}: {e}")
        if pipeline_cache_enabled and cache_key:
            _transform_pipeline_cache[cache_key] = None
        return None

def get_source_path(logger, config, root, translated_path: str) -> Optional[Any]:
    """
    Given a translated path (as seen under the FUSE mount), return the corresponding
    source path in the filestore, using the translation logic from TransFS.
    Supports dynamic ...SoftwareArchives... mapping, including zip-as-folder logic and filetype mapping.
    
    Returns:
        - String path for regular files
        - Tuple (zip_path, internal_path) for files inside zips
        - Dict {'path': path, 'transform_pipeline': pipeline} for files with transformations
        - None if not found
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

    # Check if this is a query map directory itself (e.g., /MiSTer/AcornAtom/HDs)
    if len(rel_parts) == 3:
        map_name = rel_parts[2]
        map_entry = find_map_entry(system_info, map_name)
        map_config = get_map_config(map_entry)
        if map_config and is_query_map(map_config):
            # This is a virtual query map directory - return None so GETATTR treats it as virtual
            logger.debug(f"DEBUG: {translated_path} is a query map directory, returning None")
            return None

    # Try dynamic SoftwareArchives first
    dynamic_result = get_dynamic_source_path(logger, config, system_info, rel_parts)
    if dynamic_result is not None:
        # Check if we need to add transformations for dynamic paths
        if len(rel_parts) >= 4 and isinstance(dynamic_result, str):
            virtual_folder = rel_parts[2]
            filename = rel_parts[-1]
            real_filename = os.path.basename(dynamic_result)
            cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
            pipeline = get_transform_pipeline_for_file(
                logger,
                system_info,
                real_filename,
                virtual_folder,
                cache_config,
                full_path=dynamic_result,
            )
            if not pipeline and real_filename != filename:
                pipeline = get_transform_pipeline_for_file(
                    logger,
                    system_info,
                    filename,
                    virtual_folder,
                    cache_config,
                    full_path=dynamic_result,
                )
            if pipeline:
                return {'path': dynamic_result, 'transform_pipeline': pipeline}
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
                # Only return a real file path if it exists (unless for write operations)
                if os.path.exists(base):
                    logger.debug(f"Returning named map file path: {base}")
                    return base
                else:
                    logger.debug(f"Named map file {base} does not exist, returning None")
                    # Store the would-be path for potential write operations
                    # Caller can check this via get_source_path_for_write()
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

def get_dynamic_source_path(logger, config, system_info: dict, rel_parts: tuple) -> Optional[Any]:
    """
    Handle ...SoftwareArchives... dynamic folders with zip logic and filetype mapping.
    Respects zip_mode configuration: hierarchical (default), flatten, or file.
    """

    # Need at least /<client>/<system>/<map>
    if len(rel_parts) < 3:
        return None

    map_name = rel_parts[2]
    map_entry = find_map_entry(system_info, map_name)
    map_config = get_map_config(map_entry)

    if map_config and is_query_map(map_config):
        query_cfg = get_query_config(map_config)
        extensions = query_cfg.get("extensions", [])
        extension_map = get_map_extension_map(map_config)
        extension_map = {str(k).upper(): str(v).upper() for k, v in extension_map.items()}
        supports_zip = query_cfg.get("supports_zip", True)
        zip_mode = query_cfg.get("zip_mode", "hierarchical")

        source_dir = os.path.join(
            config["filestore"],
            "Native",
            system_info["local_base_path"],
            query_cfg.get("source_dir", "Software")
        )

        subpath = rel_parts[3:]
        if not subpath:
            return None

        # ZIP navigation support
        zip_idx = next((i for i, part in enumerate(subpath) if part.lower().endswith('.zip')), None)
        if zip_idx is not None and supports_zip and zip_mode != "file":
            zip_name = subpath[zip_idx]
            inner_parts = subpath[zip_idx + 1:]
            zip_path = os.path.join(source_dir, zip_name)
            if not os.path.isfile(zip_path):
                zip_path = os.path.join(source_dir, "ZIP", zip_name)
            if os.path.isfile(zip_path):
                if inner_parts:
                    return (zip_path, "/".join(inner_parts))
                return zip_path

        last = subpath[-1]
        if '.' not in last:
            return None

        name, virt_ext = os.path.splitext(last)
        virt_ext = virt_ext[1:].upper()
        real_exts = []
        for ext in extensions:
            ext_upper = ext.upper()
            if extension_map.get(ext_upper, ext_upper) == virt_ext:
                real_exts.append(ext_upper)
            elif ext_upper == virt_ext:
                real_exts.append(ext_upper)

        for real_ext in real_exts:
            real_filename = f"{name}.{real_ext.lower()}"

            # Resolve extension directory case-insensitively (e.g., 2mg vs 2MG)
            ext_dir_name = real_ext
            for candidate_dir in (real_ext, real_ext.lower(), real_ext.upper()):
                if os.path.isdir(os.path.join(source_dir, candidate_dir)):
                    ext_dir_name = candidate_dir
                    break

            # Try extension subfolder
            candidate = os.path.join(source_dir, ext_dir_name, *subpath[:-1], real_filename)
            if os.path.exists(candidate):
                return candidate
            # Try flat layout under source_dir
            candidate = os.path.join(source_dir, *subpath[:-1], real_filename)
            if os.path.exists(candidate):
                return candidate
        return None

    # Dynamic ...SoftwareArchives... mappings require the special entry
    if "...SoftwareArchives..." not in [list(m.keys())[0] for m in system_info['maps']]:
        return None

    sa_entry = find_software_archive_entry(system_info)
    if not sa_entry:
        return None

    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])

    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
    zip_mode = sa_entry["...SoftwareArchives..."].get("zip_mode", "hierarchical")
    source_dir = os.path.join(
        config["filestore"],
        "Native",
        system_info["local_base_path"],
        sa_entry["...SoftwareArchives..."]["source_dir"]
    )
    subpath = rel_parts[3:]
    if not subpath:
        # Return the directory path for the virtual directory itself (e.g., HDs -> Software/HDF)
        for real_ext in real_exts:
            dir_path = os.path.join(source_dir, real_ext)
            if os.path.isdir(dir_path):
                return dir_path
        
        # Fallback: if extension folder doesn't exist, try using map_name as folder name
        # This handles semantic folder names like "Collections" when extension is "ZIP"
        alt_dir_path = os.path.join(source_dir, map_name)
        if os.path.isdir(alt_dir_path):
            return alt_dir_path
        
        return None

    last = subpath[-1]

    # ========== FILE MODE ==========
    # ZIPs are opaque files, never treated as containers
    if zip_mode == "file":
        # If the last component is a .zip, return the real zip path as a file
        if last.lower().endswith('.zip'):
            for real_ext in real_exts:
                candidate = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isfile(candidate):
                    return candidate
        
        # If the last component has no extension, treat as a virtual directory
        if '.' not in last:
            for real_ext in real_exts:
                dir_path = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isdir(dir_path):
                    return dir_path
            return None

        # Mapped filetype handling (regular files)
        filename = subpath[-1]
        name, virt_ext = os.path.splitext(filename)
        virt_ext = virt_ext[1:].upper()
        for real_ext in real_exts:
            real_filename = f"{name}.{real_ext.lower()}"
            real_path = os.path.join(source_dir, real_ext, *subpath[:-1], real_filename)
            if os.path.exists(real_path):
                return real_path
        return None

    # ========== HIERARCHICAL MODE (default) ==========
    # ZIPs appear as navigable directories
    if zip_mode == "hierarchical":
        # Check if path contains a .zip component (navigating inside ZIP)
        zip_path_parts = []
        zip_internal_parts = []
        found_zip = False
        
        for i, part in enumerate(subpath):
            if not found_zip:
                zip_path_parts.append(part)
                if part.lower().endswith('.zip'):
                    found_zip = True
            else:
                zip_internal_parts.append(part)
        
        # If we found a .zip in the path and supports_zip is enabled
        if found_zip and supports_zip:
            # Build real ZIP file path
            for real_ext in real_exts:
                zip_file_path = os.path.join(source_dir, real_ext, *zip_path_parts)
                if os.path.isfile(zip_file_path):
                    # If there are parts after the .zip, we're navigating inside
                    if zip_internal_parts:
                        internal_path = '/'.join(zip_internal_parts)
                        # Return tuple for ZIP-internal access
                        if zippath_exists(f"{zip_file_path}/{internal_path}"):
                            return (zip_file_path, internal_path)
                    else:
                        # Accessing the .zip itself as a directory container
                        return zip_file_path
            
            # Fallback: try map_name folder instead of extension folder
            zip_file_path = os.path.join(source_dir, map_name, *zip_path_parts)
            if os.path.isfile(zip_file_path):
                if zip_internal_parts:
                    internal_path = '/'.join(zip_internal_parts)
                    if zippath_exists(f"{zip_file_path}/{internal_path}"):
                        return (zip_file_path, internal_path)
                else:
                    return zip_file_path
        
        # Not inside a ZIP: handle regular filesystem paths
        # If the last component is a .zip file (not yet entered)
        if last.lower().endswith('.zip') and supports_zip:
            for real_ext in real_exts:
                candidate = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isfile(candidate):
                    return candidate
            
            # Fallback: try map_name folder
            candidate = os.path.join(source_dir, map_name, *subpath)
            if os.path.isfile(candidate):
                return candidate

        # If the last component has no extension, treat as a virtual directory
        if '.' not in last:
            for real_ext in real_exts:
                dir_path = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isdir(dir_path):
                    return dir_path
            return None

        # Mapped filetype handling
        filename = subpath[-1]
        name, virt_ext = os.path.splitext(filename)
        virt_ext = virt_ext[1:].upper()
        for real_ext in real_exts:
            real_filename = f"{name}.{real_ext.lower()}"
            real_path = os.path.join(source_dir, real_ext, *subpath[:-1], real_filename)
            if os.path.exists(real_path):
                return real_path
        return None

    # ========== FLATTEN MODE (legacy) ==========
    # ZIP contents are merged into parent directory listing
    if zip_mode == "flatten":
        # Flatten mode behaves like hierarchical for deeper paths
        # The flattening happens in the listing logic, not path resolution
        # So we use the same logic as hierarchical mode here
        
        # If the last component is a .zip, return the real zip path if it exists
        if last.lower().endswith('.zip'):
            for real_ext in real_exts:
                candidate = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isfile(candidate):
                    return candidate

        # If the last component has no extension, treat as a virtual directory
        if '.' not in last:
            for real_ext in real_exts:
                dir_path = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isdir(dir_path):
                    return dir_path
            return None

        # Mapped filetype handling
        filename = subpath[-1]
        name, virt_ext = os.path.splitext(filename)
        virt_ext = virt_ext[1:].upper()
        for real_ext in real_exts:
            # Try both lowercase and uppercase versions of the filename
            for real_ext_case in [real_ext.lower(), real_ext.upper()]:
                real_filename = f"{name}.{real_ext_case}"
                
                # Check regular filesystem first
                if subpath[:-1]:
                    real_path = os.path.join(source_dir, real_ext, *subpath[:-1], real_filename)
                else:
                    real_path = os.path.join(source_dir, real_ext, real_filename)
                if os.path.exists(real_path):
                    return real_path
                
                # In flatten mode, also check inside ZIP files in the real_ext directory
                if supports_zip:
                    real_ext_dir = os.path.join(source_dir, real_ext)
                    if os.path.isdir(real_ext_dir):
                        for entry in os.listdir(real_ext_dir):
                            if entry.lower().endswith('.zip'):
                                zip_path = os.path.join(real_ext_dir, entry)
                                if os.path.isfile(zip_path):
                                    # Check if the file exists inside this ZIP
                                    if zippath_isfile(f"{zip_path}/{real_filename}"):
                                        return (zip_path, real_filename)
        return None

    # Default fallback (shouldn't reach here)
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
    if "file" in mapdict:
        file_spec = mapdict.get("file")
        if isinstance(file_spec, dict):
            file_path = file_spec.get("path")
            unzip = file_spec.get("unzip", False)
            zip_internal_file = file_spec.get("zip_internal_file")
        else:
            file_path = file_spec
            unzip = mapdict.get("unzip", False)
            zip_internal_file = mapdict.get("zip_internal_file")
        if not file_path:
            return None
        base = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system_info['local_base_path'],
            file_path
        )
        if base.lower().endswith('.zip') and unzip:
            if zip_internal_file:
                if zippath_isfile(f"{base}/{zip_internal_file}"):
                    logger.debug(f"Using explicit zip_internal_file: {zip_internal_file} in {base}")
                    return (base, zip_internal_file)
                logger.debug(f"zip_internal_file {zip_internal_file} not found in {base}")
                return None
            else:
                result = get_zip_mapping(logger, base, map_name)
                logger.debug(f"ZIP mapping result for {map_name} in {base}: {result}")
                if result:
                    return result
                return None
        real_path = os.path.join(base, *subpath) if subpath else base
        if os.path.exists(real_path):
            logger.debug(f"Returning real file path: {real_path}")
            return real_path
        logger.debug(f"File {real_path} does not exist, returning None")
        return None
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


def get_source_path_for_write(logger, config, root, translated_path: str) -> Optional[str]:
    """
    Similar to get_source_path, but returns the mapped path even if the file doesn't exist yet.
    This is used for write operations where we need to create new files.
    Only returns regular file paths (strings), not zip mappings (tuples).
    """
    logger.debug(f"DEBUG: get_source_path_for_write({translated_path}) called")

    path = Path(translated_path)
    root_parts = Path(root).parts
    rel_parts = path.parts[len(root_parts):]

    if not rel_parts:
        return None
    
    if rel_parts[0] == "Native":
        return os.path.join(config.get("filestore", "/mnt/filestorefs"), "Native", *rel_parts[1:])

    client = get_client(config, rel_parts)
    if not client:
        return None

    if len(rel_parts) == 1:
        return None

    path_template_parts = Path(client['default_target_path']).parts
    system_info = get_system_info(client, list(rel_parts), path_template_parts)
    if not system_info:
        return None

    # Handle named maps
    if len(rel_parts) >= 3:
        map_path_parts = rel_parts[2:]
        for i in range(len(map_path_parts), 0, -1):
            map_name = '/'.join(map_path_parts[:i])
            map_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == map_name), None)
            if not map_entry:
                continue
            mapdict = map_entry[map_name]
            subpath = map_path_parts[i:]
            
            ds = mapdict.get('default_source') or {}
            if "source_filename" in ds:
                source_filename = ds["source_filename"]
                # Skip zip mappings for write operations (check for archive_internal_path)
                if "archive_internal_path" in ds:
                    logger.debug(f"Skipping zip mapping for write: {source_filename}")
                    return None
                
                base = os.path.join(
                    config.get("filestore", "/mnt/filestorefs"),
                    "Native",
                    system_info['local_base_path'],
                    source_filename
                )
                logger.debug(f"Returning write path (may not exist): {base}")
                return base
            break

    # Fallback to regular path
    local_base = system_info.get('local_base_path', '')
    if local_base:
        result = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            local_base,
            *rel_parts[2:]
        )
        logger.debug(f"Returning fallback write path: {result}")
        return result

    return None
