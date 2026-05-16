import os
import time
import logging
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
    resolve_virtual_base_path,
    format_virtual_base_path,
)
from filetypes import get_filetype_maps, get_filetype_transforms
from ziptutils import get_zip_mapping
from zippath import is_supported_archive_name, exists as zippath_exists, isfile as zippath_isfile, listdir as zippath_listdir
from transforms import build_transform_pipeline, TransformPipeline
from retronas_support import resolve_retronas_support_source_path, retronas_support_not_applicable

logger = logging.getLogger(__name__)

_transform_pipeline_cache: dict[tuple[str, str, str], Optional[TransformPipeline]] = {}
_recursive_filename_index_cache: dict[str, tuple[float, dict[str, str]]] = {}
_RECURSIVE_FILENAME_INDEX_TTL = 900.0  # 15 minutes - expensive to rebuild (5000+ file scans take 8+ seconds)


def _adjust_source_dir_for_layout(source_dir: str, system_info: dict) -> str:
    layout = system_info.get("download_layout") if system_info else None
    if layout != "legacy_source_based":
        return source_dir
    normalized = (source_dir or "").replace("\\", "/").strip("/").lower()
    if "sources" in normalized:
        return source_dir
    if "bios" in normalized.split("/"):
        return source_dir
    return os.path.join(source_dir, "Sources")


def _find_file_recursive(base_dir: str, filename: str) -> Optional[str]:
    if not os.path.isdir(base_dir):
        return None
    for root, _, files in os.walk(base_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None


def _find_file_recursive_indexed(base_dir: str, filename: str) -> Optional[str]:
    """
    Find a file by name recursively with directory-level caching.
    
    Builds an index of all filenames under base_dir (cached per directory mtime).
    This is much faster than repeated os.walk() calls for flattened query maps.
    """
    if not os.path.isdir(base_dir):
        return None

    now = os.path.getmtime(base_dir)
    cache_entry = _recursive_filename_index_cache.get(base_dir)
    index = None
    if cache_entry:
        cached_mtime, cached_index = cache_entry
        if (time.time() - cached_mtime) <= _RECURSIVE_FILENAME_INDEX_TTL and cached_index.get("__dir_mtime__") == str(now):
            index = cached_index
            logger.info(f"Recursive index cache HIT for {base_dir}")

    if index is None:
        logger.info(f"Recursive index cache MISS for {base_dir} - scanning directory tree...")
        scan_start = time.time()
        index = {"__dir_mtime__": str(now)}
        file_count = 0
        for root, _, files in os.walk(base_dir):
            for item in files:
                key = item.lower()
                if key not in index:
                    index[key] = os.path.join(root, item)
                file_count += 1
        scan_elapsed = time.time() - scan_start
        logger.info(f"Recursive index built: {file_count} files in {scan_elapsed:.2f}s - cached for {_RECURSIVE_FILENAME_INDEX_TTL}s")
        _recursive_filename_index_cache[base_dir] = (time.time(), index)

    return index.get(filename.lower())


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
    logger.info(f"get_transform_pipeline_for_file: filename={filename}, virtual_folder={virtual_folder}, transform_map keys={list(transform_map.keys()) if transform_map else None}")
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
    
    logger.info(f"get_transform_pipeline_for_file: extracted ext='{ext}', checking if in transform_map keys={list(transform_map.keys())}")
    
    # Check if transforms are configured for this extension
    if ext not in transform_map:
        logger.info(f"get_transform_pipeline_for_file: ext '{ext}' NOT in transform_map, returning None")
        return None

    cache_key = None
    # Note: Only use cache for generic pipelines (e.g., during initialization)
    # When we have a real full_path, we need to rebuild to trigger detection
    use_cache = pipeline_cache_enabled and not full_path
    logger.info(f"get_transform_pipeline_for_file: use_cache={use_cache}, full_path={full_path is not None}")
    if use_cache:
        cache_key = _get_transform_cache_key(system_info, virtual_folder, ext)
        if cache_key in _transform_pipeline_cache:
            logger.info(f"get_transform_pipeline_for_file: returning cached pipeline")
            return _transform_pipeline_cache[cache_key]
    
    # Build transform pipeline
    transform_specs = transform_map[ext]
    logger.info(f"get_transform_pipeline_for_file: building pipeline with specs={transform_specs}")
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

    projected_source = resolve_retronas_support_source_path(config, root, translated_path, for_write=False)
    if not retronas_support_not_applicable(projected_source):
        return projected_source

    client = get_client(config, rel_parts)
    if not client:
        return None

    if len(rel_parts) == 1:
        return config.get("filestore", "/mnt/filestorefs")

    # Check client-level maps (global maps under client root, e.g. /RetroBat/bios/*)
    if len(rel_parts) >= 2:
        filestore_root = config.get("filestore", "/mnt/filestorefs")
        client_local_base = client.get('local_base_path', '')
        translated_norm = str(path).replace('\\', '/').rstrip('/')
        client_name = client.get('name', '')

        if client_local_base:
            for map_entry in (client.get('maps') or []):
                map_name = list(map_entry.keys())[0]
                map_config = map_entry.get(map_name, {})
                if not isinstance(map_config, dict):
                    continue

                pseudo_system = {
                    'name': '_ClientShared',
                    'category_paths': {},
                }
                try:
                    base_path_template = resolve_virtual_base_path(client, pseudo_system, map_config)
                    virtual_base = format_virtual_base_path(base_path_template, client_name, '_ClientShared')
                except Exception:
                    continue

                full_virtual_base = os.path.join(root, virtual_base).replace('\\', '/').rstrip('/')
                if not translated_norm.startswith(full_virtual_base + '/'):
                    continue

                sub_virtual_path = translated_norm[len(full_virtual_base) + 1:]

                map_subpath = sub_virtual_path
                if map_name and map_name != '.':
                    if map_subpath == map_name:
                        map_subpath = ''
                    elif map_subpath.startswith(map_name + '/'):
                        map_subpath = map_subpath[len(map_name) + 1:]
                    else:
                        continue

                if 'file' in map_config:
                    file_spec = map_config.get('file')
                    if isinstance(file_spec, dict):
                        source_file_path = file_spec.get('path', '')
                    else:
                        source_file_path = str(file_spec)

                    full_path = os.path.join(
                        filestore_root,
                        "Native",
                        client_local_base,
                        source_file_path,
                    )
                    if os.path.exists(full_path):
                        return full_path

                if is_query_map(map_config):
                    query_cfg = get_query_config(map_config) or {}
                    source_dir = query_cfg.get('source_dir', 'Software')
                    full_path = os.path.join(
                        filestore_root,
                        "Native",
                        client_local_base,
                        source_dir,
                        map_subpath,
                    )
                    if map_subpath and os.path.exists(full_path):
                        return full_path

    path_template_parts = Path(client['default_target_path']).parts
    system_info = get_system_info(
        client, list(rel_parts), path_template_parts
    )
    if not system_info:
        # Fallback for category paths that intentionally omit {system_name}
        # (e.g. shared BIOS at /RetroBat/bios/* backed by a specific system map).
        translated_norm = str(path).replace('\\', '/')
        filestore_root = config.get("filestore", "/mnt/filestorefs")
        client_name = client.get('name', '')

        for candidate_system in client.get('systems', []):
            local_base_path = candidate_system.get('local_base_path')
            if not local_base_path:
                continue

            for map_entry in (candidate_system.get('maps') or []):
                map_name = list(map_entry.keys())[0]
                map_config = map_entry.get(map_name, {})
                if not isinstance(map_config, dict):
                    continue

                try:
                    base_path_template = resolve_virtual_base_path(client, candidate_system, map_config)
                    virtual_base = format_virtual_base_path(base_path_template, client_name, candidate_system.get('name', ''))
                except Exception:
                    continue

                full_virtual_base = os.path.join(root, virtual_base).replace('\\', '/').rstrip('/')
                if not translated_norm.startswith(full_virtual_base + '/'):
                    continue

                sub_virtual_path = translated_norm[len(full_virtual_base) + 1:]
                if not sub_virtual_path:
                    continue

                # Direct file map under shared category path
                if 'file' in map_config and sub_virtual_path == map_name:
                    file_spec = map_config.get('file')
                    if isinstance(file_spec, dict):
                        source_file_path = file_spec.get('path', '')
                    else:
                        source_file_path = str(file_spec)
                    full_path = os.path.join(
                        filestore_root,
                        "Native",
                        candidate_system['local_base_path'],
                        source_file_path,
                    )
                    return full_path

                # Flatten query map under shared category path
                if map_name == '.' and is_query_map(map_config):
                    query_cfg = get_query_config(map_config) or {}
                    source_dir = _adjust_source_dir_for_layout(query_cfg.get('source_dir', 'Software'), candidate_system)
                    full_path = os.path.join(
                        filestore_root,
                        "Native",
                        candidate_system['local_base_path'],
                        source_dir,
                        sub_virtual_path,
                    )
                    if os.path.exists(full_path):
                        return full_path

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

    # Check for nested file maps (e.g., FDs/bios/atom.zip)
    # These appear as virtual nested paths like /RetroBat/AcornAtom/FDs/bios/atom.zip
    if len(rel_parts) >= 4:
        # Construct the map path from all parts after the system
        map_parts = rel_parts[2:]  # e.g., ['FDs', 'bios', 'atom.zip']
        map_path = '/'.join(map_parts)  # e.g., 'FDs/bios/atom.zip'
        
        # Check if there's a map entry matching this path
        map_entry = find_map_entry(system_info, map_path)
        if map_entry:
            map_config = get_map_config(map_entry)
            if map_config and 'file' in map_config:
                file_spec = map_config['file']
                if isinstance(file_spec, dict):
                    source_file_path = file_spec.get('path', '')
                    filestore_root = config.get("filestore", "/mnt/filestorefs")
                    # Construct full path: /mnt/filestorefs/Native/{path}
                    # The path in config already includes the full path from Native/
                    full_path = os.path.join(filestore_root, "Native", source_file_path)
                    logger.debug(f"DEBUG: nested file map {map_path} -> {full_path}")
                    
                    # zip_mode: file means treat as opaque file, not browsable directory
                    # Return as string path so it's treated as a regular file
                    return full_path

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

    # Handle flattened maps (.) - files appear directly in system folder
    # Support nested subpaths under flattened maps (e.g., /RetroBat/bios/mame/ini/mame.ini)
    if len(rel_parts) >= 3:
        flatten_map_entry = next((m for m in (system_info.get('maps') or []) if list(m.keys())[0] == '.'), None)
        if flatten_map_entry:
            flatten_config = flatten_map_entry['.']
            # Determine file subpath from remaining virtual path components
            # For category paths this is typically rel_parts[2:] or rel_parts[3:]
            # depending on whether system name appears in the virtual path.
            file_subpath_parts = rel_parts[3:] if len(rel_parts) >= 4 else rel_parts[2:]
            if system_info.get('name') in rel_parts:
                try:
                    system_idx = rel_parts.index(system_info.get('name'))
                    file_subpath_parts = rel_parts[system_idx + 1:]
                except ValueError:
                    pass

            if not file_subpath_parts:
                return None

            file_subpath = os.path.join(*file_subpath_parts)
            
            # Use query-based lookup for flattened maps
            if 'query' in flatten_config:
                query_cfg = flatten_config['query']
                source_dir = query_cfg.get('source_dir', 'Software')
                logger.debug(f"Found flattened map (.), using source_dir={source_dir} for file={file_subpath}")
                
                # Build the full path in the filesystem
                base_path = os.path.join(
                    config.get("filestore", "/mnt/filestorefs"),
                    "Native",
                    system_info['local_base_path'],
                    source_dir
                )
                full_path = os.path.join(base_path, file_subpath)
                
                if os.path.exists(full_path):
                    logger.debug(f"Flattened map: Found file {full_path}")
                    return full_path
                else:
                    logger.debug(f"Flattened map: File {full_path} does not exist")
            # Flattened file maps could be added here if needed
            return None

    # Handle named maps (including nested paths like MMBs/beeb1_mmb.VHD)
    if len(rel_parts) >= 3:
        # Support nested map names by joining remaining parts
        map_path_parts = rel_parts[2:]
        # Try progressively longer paths to find a matching map
        for i in range(len(map_path_parts), 0, -1):
            map_name = '/'.join(map_path_parts[:i])
            map_entry = next((m for m in (system_info.get('maps') or []) if list(m.keys())[0] == map_name), None)
            if not map_entry:
                continue
            mapdict = map_entry[map_name]
            # subpath is everything after the matched map name
            subpath = map_path_parts[i:]
            
            # Handle file-based map (new format: file: {path: ...})
            if 'file' in mapdict:
                file_config = mapdict.get('file') or {}
                file_path = file_config.get('path')
                if file_path:
                    # Resolve the file path relative to local_base_path
                    base = os.path.join(
                        config.get("filestore", "/mnt/filestorefs"),
                        "Native",
                        system_info['local_base_path'],
                        file_path
                    )
                    
                    # Check if this is a zip file that needs to be extracted
                    unzip = file_config.get('unzip', False)
                    zip_internal_file = file_config.get('zip_internal_file')
                    
                    if base.lower().endswith('.zip') and (unzip or zip_internal_file):
                        if zip_internal_file:
                            # use zippath to test for entry existence
                            if zippath_isfile(f"{base}/{zip_internal_file}"):
                                logger.debug(f"File-based map: Using zip_internal_file: {zip_internal_file} in {base}")
                                return (base, zip_internal_file)
                            else:
                                logger.debug(f"File-based map: zip_internal_file {zip_internal_file} not found in {base}")
                            return None
                        else:
                            # fallback to existing mapping helper
                            match_name = map_name.split('/')[-1]
                            result = get_zip_mapping(logger, base, match_name)
                            logger.debug(f"File-based map: ZIP mapping result for {map_name}: {result}")
                            if result:
                                return result
                            return None
                    
                    # For regular files, check if they exist and return the path
                    if os.path.exists(base):
                        logger.debug(f"File-based map: Returning file path: {base}")
                        return base
                    else:
                        logger.debug(f"File-based map: File {base} does not exist")
                        return None
            
            # If default_source->source_filename is present, return the mapped file (legacy format)
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
    
    # Handle nested maps like bios/atom.zip accessed as a virtual directory (e.g., path .../bios)
    # When user accesses /mnt/transfs/RetroBat/AcornAtom/bios but only bios/atom.zip exists
    if len(rel_parts) >= 3:
        requested_dir = rel_parts[2]
        # Look for any map that starts with requested_dir/
        nested_maps = [m for m in (system_info.get('maps') or []) if list(m.keys())[0].startswith(f"{requested_dir}/")]
        if nested_maps:
            # Found nested maps under this directory
            # Return the first nested map as a virtual directory
            first_nested_map_name = list(nested_maps[0].keys())[0]
            logger.debug(f"Found nested maps under '{requested_dir}': {[list(m.keys())[0] for m in nested_maps]}")
            # For a virtual directory pointing to nested maps, return None so FUSE treats it as a virtual directory
            # The actual file resolution will happen when accessing specific files within
            return None

    # Handle parent-level maps (../) - shared resources accessible from systems
    if len(rel_parts) >= 3:
        from pathutils import is_parent_level_map, normalize_map_name
        map_path_parts = rel_parts[2:]
        # Try progressively longer paths to find a matching parent-level map
        for i in range(len(map_path_parts), 0, -1):
            potential_path = '/'.join(map_path_parts[:i])
            # Check all maps for one with ../ prefix that matches after normalization
            for map_entry in (system_info.get('maps') or []):
                map_name = list(map_entry.keys())[0]
                if is_parent_level_map(map_name):
                    normalized = normalize_map_name(map_name)
                    if normalized == potential_path:
                        logger.debug(f"Found parent-level map: {map_name} -> {normalized}")
                        mapdict = map_entry[map_name]
                        subpath = map_path_parts[i:]
                        
                        # Handle file-based parent-level maps
                        if 'file' in mapdict:
                            file_config = mapdict.get('file') or {}
                            file_path = file_config.get('path')
                            if file_path:
                                base = os.path.join(
                                    config.get("filestore", "/mnt/filestorefs"),
                                    "Native",
                                    system_info['local_base_path'],
                                    file_path
                                )
                                if os.path.exists(base):
                                    logger.debug(f"Parent-level file map: returning {base}")
                                    return base
                        # Handle query-based parent-level maps if needed
                        # For now, file-based is the main use case (bios files)
                        return None

    # Try regular map logic
    regular_result = get_regular_source_path(logger, config, system_info, rel_parts)
    if regular_result is not None:
        return regular_result

    # If this is a file path under a query map and resolution failed,
    # do not fall back to joining virtual map names as physical folders
    # (e.g., /.../HDs/file.vhd -> .../Atom/HDs/file.vhd).
    try:
        system_idx = rel_parts.index(system_info['name'])
    except ValueError:
        system_idx = 1
    if len(rel_parts) > system_idx + 2:
        query_map_name = rel_parts[system_idx + 1]
        query_map_entry = next(
            (m for m in (system_info.get('maps') or []) if list(m.keys())[0] == query_map_name),
            None,
        )
        query_map_config = get_map_config(query_map_entry)
        if query_map_config and is_query_map(query_map_config):
            logger.debug(
                f"DEBUG: query map resolution failed for {translated_path}; returning None instead of generic fallback"
            )
            return None

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
    Parse archive-style notation like 'Software/MMB/BEEB2.zip/BEEB.MMB'.
    Returns (archive_path, internal_path) if a supported archive component is found, else None.
    """
    parts = path_str.split('/')
    for i, part in enumerate(parts):
        if is_supported_archive_name(part):
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
        transform_zip = query_cfg.get("transform_zip", True)
        zip_mode = query_cfg.get("zip_mode", "hierarchical")

        raw_source_subdir = query_cfg.get("source_dir", "Software")
        adjusted_source_subdir = _adjust_source_dir_for_layout(raw_source_subdir, system_info)
        source_subdirs = [adjusted_source_subdir]
        if raw_source_subdir not in source_subdirs:
            source_subdirs.append(raw_source_subdir)

        source_dirs = [
            os.path.join(
                config["filestore"],
                "Native",
                system_info["local_base_path"],
                source_subdir,
            )
            for source_subdir in source_subdirs
        ]

        subpath = rel_parts[3:]
        if not subpath:
            return None

        # Archive navigation support
        zip_idx = next((i for i, part in enumerate(subpath) if is_supported_archive_name(part)), None)
        if zip_idx is not None and transform_zip and zip_mode != "file":
            zip_name = subpath[zip_idx]
            inner_parts = subpath[zip_idx + 1:]
            for source_dir in source_dirs:
                zip_path = os.path.join(source_dir, zip_name)
                if not os.path.isfile(zip_path):
                    zip_path = os.path.join(source_dir, "ZIP", zip_name)
                if not os.path.isfile(zip_path):
                    zip_path = _find_file_recursive(source_dir, zip_name)
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

        for source_dir in source_dirs:
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

                recursive_match = _find_file_recursive(source_dir, real_filename)
                if recursive_match:
                    return recursive_match
        
        # REVERSE MAPPING: If not found, check if this extension is a transform output
        # E.g., requesting Game.hdv might actually be Game.2mg with two_mg transform
        transform_map = get_map_transforms(map_config)
        if transform_map and virt_ext:
            for source_ext, transform_specs in transform_map.items():
                # Check if this transform outputs the requested extension
                # Try to find a file with the source extension
                real_filename = f"{name}.{source_ext.lower()}"
                
                # Resolve extension directory case-insensitively
                ext_dir_name = source_ext
                for candidate_dir in (source_ext, source_ext.lower(), source_ext.upper()):
                    if os.path.isdir(os.path.join(source_dir, candidate_dir)):
                        ext_dir_name = candidate_dir
                        break
                
                # Try extension subfolder
                candidate = os.path.join(source_dir, ext_dir_name, *subpath[:-1], real_filename)
                if os.path.exists(candidate):
                    logger.info(f"REVERSE MAPPING: found {candidate} for requested {last}")
                    # Build transform pipeline for this file
                    from pathutils import get_client, get_system_info
                    cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                    pipeline = get_transform_pipeline_for_file(
                        logger,
                        system_info,
                        real_filename,
                        map_name,
                        cache_config,
                        full_path=candidate,
                    )
                    if pipeline:
                        return {'path': candidate, 'transform_pipeline': pipeline}
                    return candidate
                    
                # Try flat layout
                candidate = os.path.join(source_dir, *subpath[:-1], real_filename)
                if os.path.exists(candidate):
                    logger.info(f"REVERSE MAPPING: found {candidate} for requested {last}")
                    # Build transform pipeline for this file
                    cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                    pipeline = get_transform_pipeline_for_file(
                        logger,
                        system_info,
                        real_filename,
                        map_name,
                        cache_config,
                        full_path=candidate,
                    )
                    if pipeline:
                        return {'path': candidate, 'transform_pipeline': pipeline}
                    return candidate
        
        return None

    # Dynamic ...SoftwareArchives... mappings require the special entry
    if "...SoftwareArchives..." not in [list(m.keys())[0] for m in (system_info.get('maps') or [])]:
        return None

    sa_entry = find_software_archive_entry(system_info)
    if not sa_entry:
        return None

    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])

    transform_zip = sa_entry["...SoftwareArchives..."].get("transform_zip", True)
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
        if transform_map and virt_ext:
            for source_dir in source_dirs:
                for source_ext, transform_specs in transform_map.items():
                    # Check if this transform outputs the requested extension
                    # Try to find a file with the source extension
                    real_filename = f"{name}.{source_ext.lower()}"
                    
                    # Resolve extension directory case-insensitively
                    ext_dir_name = source_ext
                    for candidate_dir in (source_ext, source_ext.lower(), source_ext.upper()):
                        if os.path.isdir(os.path.join(source_dir, candidate_dir)):
                            ext_dir_name = candidate_dir
                            break
                    
                    # Try extension subfolder
                    candidate = os.path.join(source_dir, ext_dir_name, *subpath[:-1], real_filename)
                    if os.path.exists(candidate):
                        # Build transformation pipeline for this source file
                        cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                        pipeline = get_transform_pipeline_for_file(
                            logger,
                            system_info,
                            real_filename,
                            map_name,
                            cache_config,
                            full_path=candidate,
                        )
                        if pipeline:
                            return {'path': candidate, 'transform_pipeline': pipeline}
                    
                    # Try flat layout under source_dir
                    candidate = os.path.join(source_dir, *subpath[:-1], real_filename)
                    if os.path.exists(candidate):
                        cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                        pipeline = get_transform_pipeline_for_file(
                            logger,
                            system_info,
                            real_filename,
                            map_name,
                            cache_config,
                            full_path=candidate,
                        )
                        if pipeline:
                            return {'path': candidate, 'transform_pipeline': pipeline}
                    
                    recursive_match = _find_file_recursive(source_dir, real_filename)
                    if recursive_match:
                        cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                        pipeline = get_transform_pipeline_for_file(
                            logger,
                            system_info,
                            real_filename,
                            map_name,
                            cache_config,
                            full_path=recursive_match,
                        )
                        if pipeline:
                            return {'path': recursive_match, 'transform_pipeline': pipeline}
        
        # If we found a .zip in the path and transform_zip is enabled
        if found_zip and transform_zip:
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
        if last.lower().endswith('.zip') and transform_zip:
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
                if transform_zip:
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

    # Determine map position relative to the resolved system segment.
    # Supports both /<client>/<system>/<map>/... and category paths like
    # /<client>/<category>/<system>/<map>/...
    try:
        system_idx = rel_parts.index(system_info['name'])
    except ValueError:
        system_idx = 1

    if len(rel_parts) <= system_idx + 1:
        return None

    map_name = rel_parts[system_idx + 1]
    map_entry = next((m for m in (system_info.get('maps') or []) if list(m.keys())[0] == map_name), None)
    if not map_entry:
        return None
    mapdict = map_entry[map_name]
    subpath = rel_parts[system_idx + 2:]
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

    if "query" in mapdict:
        query_cfg = mapdict.get("query") or {}
        raw_source_dir = query_cfg.get("source_dir", "Software")
        adjusted_source_dir = _adjust_source_dir_for_layout(raw_source_dir, system_info)
        source_dirs = [adjusted_source_dir]
        if raw_source_dir not in source_dirs:
            source_dirs.append(raw_source_dir)
        preserve_structure = bool(query_cfg.get("preserve_structure", False))
        bases = [
            os.path.join(
                config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                source_dir,
            )
            for source_dir in source_dirs
        ]
        if not subpath:
            # Query map root is virtual; let FUSE handle it as directory
            for base in bases:
                if os.path.isdir(base):
                    logger.debug(
                        f"DEBUG: _get_regular_source_path returns None for query virtual dir (map root): {base}"
                    )
                    return None
            return None

        for base in bases:
            real_path = os.path.join(base, *subpath)
            if os.path.exists(real_path):
                logger.debug(f"DEBUG: _get_regular_source_path returns real path (query): {real_path}")
                return real_path

            # If query listing is flattened (preserve_structure=false), the virtual name may
            # map to a file located in nested subdirectories under source_dir.
            if not preserve_structure and subpath:
                candidate_name = subpath[-1]
                recursive_match = _find_file_recursive_indexed(base, candidate_name)
                if recursive_match and os.path.exists(recursive_match):
                    logger.debug(f"DEBUG: _get_regular_source_path returns recursive query match: {recursive_match}")
                    return recursive_match

        logger.debug(
            f"DEBUG: _get_regular_source_path returns None for missing path (query): {os.path.join(bases[0], *subpath)}"
        )
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
    Supports category-based paths (e.g., /RetroBat/bios) and explicit system paths.
    """
    logger.debug(f"DEBUG: get_source_path_for_write({translated_path}) called")

    path = Path(translated_path)
    root_parts = Path(root).parts
    rel_parts = path.parts[len(root_parts):]

    if not rel_parts:
        return None
    
    if rel_parts[0] == "Native":
        return os.path.join(config.get("filestore", "/mnt/filestorefs"), "Native", *rel_parts[1:])

    projected_source = resolve_retronas_support_source_path(config, root, translated_path, for_write=True)
    if not retronas_support_not_applicable(projected_source):
        return projected_source

    client = get_client(config, rel_parts)
    if not client:
        return None

    if len(rel_parts) == 1:
        return None

    # Resolve category-based and non-standard virtual bases by matching map virtual base paths.
    # This handles paths like /RetroBat/bios/... where the category path key may be
    # "shared_bios" but the visible directory is "bios".
    translated_norm = str(path).replace('\\', '/').rstrip('/')
    translated_lower = translated_norm.lower()
    client_name = client.get('name', '')
    filestore = config.get("filestore", "/mnt/filestorefs")

    # Resolve client-level maps first (global maps under client root)
    client_local_base = client.get('local_base_path', '')
    if client_local_base:
        for map_entry in (client.get('maps') or []):
            map_name = list(map_entry.keys())[0]
            map_config = map_entry.get(map_name, {})
            if not isinstance(map_config, dict):
                continue

            pseudo_system = {
                'name': '_ClientShared',
                'category_paths': {},
            }
            try:
                base_path_template = resolve_virtual_base_path(client, pseudo_system, map_config)
                virtual_base = format_virtual_base_path(base_path_template, client_name, '_ClientShared')
            except Exception:
                continue

            full_virtual_base = os.path.join(root, virtual_base).replace('\\', '/').rstrip('/')
            full_virtual_base_lower = full_virtual_base.lower()

            if not (
                translated_lower == full_virtual_base_lower
                or translated_lower.startswith(full_virtual_base_lower + '/')
            ):
                continue

            sub_virtual = translated_norm[len(full_virtual_base):].lstrip('/')

            map_subpath = sub_virtual
            if map_name and map_name != '.':
                if map_subpath == map_name:
                    map_subpath = ''
                elif map_subpath.startswith(map_name + '/'):
                    map_subpath = map_subpath[len(map_name) + 1:]
                else:
                    continue

            if is_query_map(map_config):
                query_cfg = get_query_config(map_config) or {}
                source_dir = query_cfg.get('source_dir', 'Software')
                base = os.path.join(filestore, "Native", client_local_base, source_dir)
                return os.path.join(base, map_subpath) if map_subpath else base

            file_cfg = map_config.get('file')
            if file_cfg:
                source_path = file_cfg.get('path') if isinstance(file_cfg, dict) else str(file_cfg)
                base = os.path.join(filestore, "Native", client_local_base, source_path)
                return os.path.join(base, map_subpath) if map_subpath else base

    for system in client.get('systems', []):
        local_base = system.get('local_base_path', '')
        if not local_base:
            continue

        for map_entry in (system.get('maps') or []):
            map_name = list(map_entry.keys())[0]
            map_config = map_entry.get(map_name, {})
            if not isinstance(map_config, dict):
                continue

            try:
                base_path_template = resolve_virtual_base_path(client, system, map_config)
                virtual_base = format_virtual_base_path(base_path_template, client_name, system.get('name', ''))
            except Exception:
                continue

            full_virtual_base = os.path.join(root, virtual_base).replace('\\', '/').rstrip('/')
            full_virtual_base_lower = full_virtual_base.lower()

            if not (
                translated_lower == full_virtual_base_lower
                or translated_lower.startswith(full_virtual_base_lower + '/')
            ):
                continue

            # Portion under the mapped virtual base
            sub_virtual = translated_norm[len(full_virtual_base):].lstrip('/')

            # If this named map is not embedded in the virtual base path, only match
            # requests that explicitly target the map name.
            if map_name and map_name != '.':
                base_has_map = (
                    full_virtual_base_lower == f"{root.rstrip('/').lower()}/{map_name.lower()}"
                    or full_virtual_base_lower.endswith('/' + map_name.lower())
                )
                if (not base_has_map) and not (
                    sub_virtual == map_name
                    or sub_virtual.startswith(map_name + '/')
                ):
                    continue

            # For named maps where the virtual base does not include the map name,
            # strip the leading map segment from the subpath.
            map_subpath = sub_virtual
            if map_name and map_name != '.':
                if map_subpath == map_name:
                    map_subpath = ''
                elif map_subpath.startswith(map_name + '/'):
                    map_subpath = map_subpath[len(map_name) + 1:]

            # Query map writes: map to source_dir tree.
            if is_query_map(map_config):
                query_cfg = get_query_config(map_config) or {}
                source_dir = _adjust_source_dir_for_layout(query_cfg.get('source_dir', 'Software'), system)
                base = os.path.join(filestore, "Native", local_base, source_dir)
                result = os.path.join(base, map_subpath) if map_subpath else base
                logger.debug(f"Returning mapped query write path: {result}")
                return result

            # File/default-source map writes.
            file_cfg = map_config.get('file')
            if file_cfg:
                source_path = file_cfg.get('path') if isinstance(file_cfg, dict) else str(file_cfg)
                base = os.path.join(filestore, "Native", local_base, source_path)
                if map_subpath:
                    result = os.path.join(os.path.dirname(base), map_subpath)
                else:
                    result = base
                logger.debug(f"Returning mapped file write path: {result}")
                return result

            ds = map_config.get('default_source') or {}
            if "source_filename" in ds:
                base = os.path.join(filestore, "Native", local_base, ds["source_filename"])
                if map_subpath:
                    result = os.path.join(os.path.dirname(base), map_subpath)
                else:
                    result = base
                logger.debug(f"Returning mapped default_source write path: {result}")
                return result

    path_template_parts = Path(client['default_target_path']).parts
    system_info = get_system_info(client, list(rel_parts), path_template_parts)
    if not system_info:
        return None

    # Handle named maps
    if len(rel_parts) >= 3:
        map_path_parts = rel_parts[2:]
        for i in range(len(map_path_parts), 0, -1):
            map_name = '/'.join(map_path_parts[:i])
            map_entry = next((m for m in (system_info.get('maps') or []) if list(m.keys())[0] == map_name), None)
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
    local_base = system_info.get('local_base_path', '') if system_info else ''
    if local_base:
        result = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            local_base,
            *rel_parts[2:]
        )
        logger.debug(f"Returning fallback write path: {result}")
        return result

    # Final fallback: if we have a client but no system match, allow writes to client-based path
    # This handles clients like RetroBat that don't have system definitions but still need write support
    if client:
        result = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            *rel_parts[1:]  # Everything after the client name
        )
        logger.debug(f"Returning client-based fallback write path (no system match): {result}")
        return result

    return None
