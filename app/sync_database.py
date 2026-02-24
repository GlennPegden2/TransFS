#!/usr/bin/env python3
"""
Database synchronization tool for TransFS.

Scans the filesystem and populates the database based on clients.yaml configuration.
This is the primary way to add files to the TransFS database.

Usage:
    docker exec transfs python3 -m app.sync_database [options]
    
Options:
    --full          Full rescan (clear database and rebuild)
    --incremental   Only add new files (default)
    --client NAME   Only sync specific client
    --system NAME   Only sync specific system
    --dry-run       Show what would be done without making changes
    --verbose       Show detailed progress
"""
import os
import sys
import time
import re
import argparse
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from io import StringIO
import logging

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import read_config
from pathutils import get_client, get_system_info, find_map_entry, get_map_config, is_query_map, get_query_config
from transforms import build_transform_pipeline
from metadata import enrich_file_metadata, PackContext
from db.connection import get_connection, return_connection

logger = logging.getLogger(__name__)

# Batch processing configuration for performance optimization
BATCH_SIZE = 1000  # Number of files to batch before flushing to database


class DatabaseSync:
    """Synchronizes filesystem to database based on clients.yaml configuration."""
    
    def __init__(self, config: dict, progress_callback=None):
        """
        Initialize database sync.
        
        Args:
            config: Configuration from read_config()
            progress_callback: Optional callable to receive progress updates
        """
        self.config = config
        self.filestore = config.get("filestore", "/mnt/filestorefs")
        self.mount_path = "/mnt/transfs"
        self.progress_callback = progress_callback
        
        # Statistics
        self.stats = {
            'files_added': 0,
            'files_updated': 0,
            'files_deleted': 0,
            'errors': 0,
            'skipped': 0,
        }
        
        # Track seen source paths for deletion detection
        self.seen_source_paths: Set[str] = set()
        self._pack_context_by_folder = self._build_pack_context_index()
        
        # Shared database connection and batch processing
        self.conn = None
        self.cursor = None
        self.batch_size = BATCH_SIZE
        self.file_batch = []  # For batching file operations
        self.pending_operations = []
    
    def _emit_progress(self, status: str, **kwargs):
        """Emit progress update to callback if configured."""
        if self.progress_callback:
            msg = {'status': status, **kwargs}
            self.progress_callback(msg)

    def _build_pack_context_index(self) -> Dict[str, Dict[str, dict]]:
        """
        Build a lookup of {manufacturer/system: {folder: pack_context_dict}}.
        Folder corresponds to sources[].folder (e.g., ROMs, BIN).
        """
        index: Dict[str, Dict[str, dict]] = {}
        archive_sources = self.config.get("archive_sources", {})
        for manufacturer, systems in archive_sources.items():
            for canonical_name, source_config in systems.items():
                system_key = f"{manufacturer}::{canonical_name}"
                index[system_key] = {}
                download_layout = self._get_download_layout(manufacturer, canonical_name)
                sources = source_config.get("sources", [])
                source_by_name = {src.get("name"): src for src in sources}
                for pack in source_config.get("packs", []) or []:
                    metadata = pack.get("metadata") or {}
                    defaults = metadata.get("defaults") or {}
                    pack_context = PackContext(
                        pack_name=pack.get("name") or pack.get("id"),
                        ruleset=metadata.get("ruleset"),
                        ruleset_overrides=metadata.get("overrides"),
                        defaults=defaults,
                        tags=metadata.get("tags") or [],
                        default_extension=defaults.get("extension"),
                    )
                    for source_name in pack.get("sources", []) or []:
                        source = source_by_name.get(source_name)
                        if not source:
                            continue
                        folder = self._resolve_source_folder_for_layout(
                            folder=source.get("folder"),
                            source_name=source_name,
                            download_layout=download_layout,
                        )
                        if folder and folder not in index[system_key]:
                            index[system_key][folder] = pack_context
        return index

    def _resolve_source_folder_for_layout(self, folder: Optional[str], source_name: str,
                                          download_layout: Optional[str]) -> Optional[str]:
        if download_layout != "source_based":
            return folder
        if not source_name:
            return folder
        folder = folder or ""
        normalized = folder.replace("\\", "/").lower().strip("/")
        if normalized.startswith("bios") or "/bios/" in f"/{normalized}/":
            return folder
        if "sources/" in normalized:
            return folder
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name.strip()) or "source"
        return os.path.join("Software", "Sources", safe_name)

    def _get_download_layout(self, manufacturer: str, canonical_name: str) -> Optional[str]:
        for client in self.config.get("clients", []):
            client_layout = client.get("download_layout")
            for system in client.get("systems", []):
                system_canonical = system.get("system_mapping_name") or system.get("cananonical_system_name")
                if system.get("manufacturer") == manufacturer and system_canonical == canonical_name:
                    return system.get("download_layout", client_layout)
        return None

    def _get_pack_context_for_file(self, manufacturer: str, canonical_name: str, source_path: str) -> Optional[dict]:
        system_key = f"{manufacturer}::{canonical_name}"
        folder_map = self._pack_context_by_folder.get(system_key, {})
        if not folder_map:
            return None
        for folder, context in folder_map.items():
            normalized_folder = (folder or "").replace("\\", "/").strip("/")
            if normalized_folder.lower().startswith("software/"):
                needle = f"/{normalized_folder}/"
            else:
                needle = f"/Software/{normalized_folder}/"
            if needle.lower() in source_path.lower():
                return context
        return None
    
    def _get_pack_context_for_system(self, client_name: str, system_name: str, dir_path: str) -> Optional[PackContext]:
        """Get pack context for a given client/system based on directory path."""
        # Get manufacturer and canonical name from config
        for client in self.config.get("clients", []):
            if client.get("name") == client_name:
                for system in client.get("systems", []):
                    if system.get("name") == system_name:
                        manufacturer = system.get("manufacturer")
                        canonical_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
                        if manufacturer and canonical_name:
                            # Use existing method but need to convert dir_path to source_path format
                            # dir_path is typically like /mnt/filestorefs/Native/Acorn/Atom/Software/...
                            source_path = dir_path
                            return self._get_pack_context_for_file(manufacturer, canonical_name, source_path)
        return None
    
    def init_database(self):
        """Initialize database schema using centralized schema."""
        from db.connection import init_database as db_init_database
        
        logger.info("Initializing database connection")
        # init_database reads from environment variables set in docker-compose
        db_init_database()
        logger.info("Database schema initialized")
    
    def full_sync(self, client_filter: Optional[str] = None, system_filter: Optional[str] = None):
        """
        Perform full database synchronization.
        
        Args:
            client_filter: Only sync this client (e.g., "MiSTer")
            system_filter: Only sync this system (e.g., "Apple-II")
        """
        # Log sync scope at the start
        if client_filter and system_filter:
            logger.info(f"Starting database sync: {client_filter}/{system_filter}")
        elif client_filter:
            logger.info(f"Starting database sync: client '{client_filter}' (all systems)")
            self._emit_progress('syncing', message=f"Syncing client '{client_filter}'")
        elif system_filter:
            logger.info(f"Starting database sync: system '{system_filter}' (all clients)")
            self._emit_progress('syncing', message=f"Syncing system '{system_filter}'")
        else:
            logger.info("Starting database sync: FULL FILESYSTEM (all clients and systems)")
            self._emit_progress('syncing', message="Starting full filesystem sync")
        
        logger.info("Initializing database connection")
        start_time = time.time()
        
        # Initialize database
        self.init_database()
        
        # Get connection from pool
        self.conn = get_connection()
        self.cursor = self.conn.cursor()
        
        logger.info("Database schema initialized")
        self._emit_progress('initialized', message="Database initialized")
        
        try:
            # Scan all configured clients and systems
            clients_config = self.config.get("clients", [])
            total_clients = len([c for c in clients_config if not client_filter or c.get("name") == client_filter])
            current_client = 0
            
            for client_config in clients_config:
                client_name = client_config.get("name")
                
                # Apply client filter
                if client_filter and client_name != client_filter:
                    logger.debug(f"Skipping client {client_name} (filter: {client_filter})")
                    continue
                
                current_client += 1
                logger.info(f"Syncing client: {client_name}")
                self._emit_progress('client', client=client_name, progress=current_client, total=total_clients)
                
                systems = client_config.get("systems", [])
                for system_config in systems:
                    system_name = system_config.get("name")
                    
                    # Apply system filter
                    if system_filter and system_name != system_filter:
                        logger.debug(f"Skipping system {system_name} (filter: {system_filter})")
                        continue
                    
                    logger.info(f"  Syncing system: {client_name}/{system_name}")
                    self._emit_progress('system', client=client_name, system=system_name)
                    self._sync_system(client_config, system_config)
            
            # Flush any remaining batched operations
            self._flush_batch()
            
            # Clean up deleted files
            logger.info("Cleaning up deleted files from database")
            self._emit_progress('cleanup', message="Cleaning up deleted files")
            self._clean_deleted_files()
            
            # Final commit
            self.conn.commit()
            
        finally:
            if self.conn:
                return_connection(self.conn)
                self.conn = None
            self.cursor = None
        
        duration = time.time() - start_time
        logger.info(
            f"Sync complete: {self.stats['files_added']} added, "
            f"{self.stats['files_updated']} updated, {self.stats['files_deleted']} deleted, "
            f"{self.stats['errors']} errors in {duration:.2f}s"
        )
        
        self._emit_progress('complete', 
                          stats=self.stats,
                          duration=duration,
                          message=f"Sync complete: {self.stats['files_added']} added, {self.stats['files_updated']} updated")
        
        return self.stats
    
    def _sync_system(self, client_config: dict, system_config: dict):
        """Sync a single system's files to database by scanning entire base path."""
        client_name = client_config["name"]
        system_name = system_config["name"]
        local_base_path = system_config.get("local_base_path", "")
        
        # Build system base path
        system_base_path = os.path.join(
            self.filestore,
            "Native",
            local_base_path
        )
        
        if not os.path.exists(system_base_path):
            logger.warning(f"    System base path not found: {system_base_path}")
            return
        
        # Build map configurations for file matching
        maps = system_config.get("maps", [])
        query_map_configs = []
        file_based_maps = []
        
        for map_entry in maps:
            map_name = list(map_entry.keys())[0]
            map_config = map_entry[map_name]
            
            # Handle file-based maps (have "file" key)
            if "file" in map_config:
                file_based_maps.append({
                    'name': map_name,
                    'config': map_config,
                    'file_spec': map_config.get('file'),
                })
                logger.debug(f"    Found file-based map: {map_name}")
            # Handle query maps (have "query" key)
            elif is_query_map(map_config):
                query_cfg = get_query_config(map_config)
                if query_cfg:
                    query_map_configs.append({
                        'name': map_name,
                        'config': map_config,
                        'query': query_cfg,
                        'extensions': [e.upper() for e in query_cfg.get("extensions", [])],
                        'source_dir': query_cfg.get("source_dir", "Software"),
                        'extension_map': query_cfg.get("extension_map", {}),
                        'transforms': map_config.get("transforms", {}),
                        'preserve_exact_filenames': query_cfg.get("preserve_exact_filenames", False)
                    })
                    logger.debug(f"    Found query map: {map_name}")
            else:
                logger.debug(f"    Skipping unknown map type: {map_name}")
        
        # Process file-based maps first
        for file_map in file_based_maps:
            self._sync_file_based_map(
                client_name, system_name, file_map['name'],
                file_map['config'], system_config
            )
        
        # Flush file-based map entries before scanning query maps
        # This prevents them from being overwritten by query map scans of the same files
        self._flush_file_batch()
        
        # Then process query maps
        if query_map_configs:
            logger.info(f"    Scanning entire system base: {system_base_path}")
            self._scan_system_directory(
                system_base_path, client_name, system_name, query_map_configs
            )
        elif not file_based_maps:
            logger.debug(f"    No query or file-based maps found for {system_name}")
    
    def _sync_file_based_map(self, client_name: str, system_name: str, map_name: str,
                            map_config: dict, system_config: dict):
        """Sync files from a file-based map to database."""
        logger.info(f"    Syncing file-based map: {map_name}")
        
        file_spec = map_config.get('file')
        if not file_spec:
            logger.warning(f"      No file spec for {map_name}")
            return
        
        # Extract file path from spec
        if isinstance(file_spec, dict):
            file_path = file_spec.get('path')
            unzip = file_spec.get('unzip', False)
            zip_internal_file = file_spec.get('zip_internal_file')
        else:
            file_path = file_spec
            unzip = map_config.get('unzip', False)
            zip_internal_file = map_config.get('zip_internal_file')
        
        if not file_path:
            logger.warning(f"      No file path for {map_name}")
            return
        
        # Build full path to the file
        local_base_path = system_config.get("local_base_path", "")
        full_path = os.path.join(
            self.filestore,
            "Native",
            local_base_path,
            file_path
        )
        
        logger.debug(f"      File-based map {map_name}: {full_path}")
        
        # Handle different cases
        if unzip and full_path.lower().endswith('.zip'):
            # File is inside a ZIP
            if not os.path.exists(full_path):
                logger.warning(f"      ZIP file not found: {full_path}")
                return
            
            if zip_internal_file:
                # Single internal file specified
                logger.debug(f"      Adding zip entry: {zip_internal_file} from {full_path}")
                # Use tuple notation for zip files
                virtual_filename = os.path.basename(zip_internal_file)
                virtual_path = os.path.join(
                    self.mount_path,
                    client_name,
                    system_name,
                    map_name,
                    virtual_filename
                )
                
                now = int(time.time())
                
                # For zip entries, we store the tuple as source (handled in open operations)
                # Store as a simple entry in database with special handling
                try:
                    stat = os.stat(full_path)  # Get stats of the ZIP file
                    
                    self.file_batch.append({
                        'source_path': f"{full_path}#ZIP#{zip_internal_file}",  # Special format for zip
                        'virtual_path': virtual_path,
                        'filename': virtual_filename,
                        'extension': os.path.splitext(virtual_filename)[1][1:].lower(),
                        'size': stat.st_size,  # Approximate with ZIP size
                        'mtime': int(stat.st_mtime),
                        'ctime': int(stat.st_ctime),
                        'atime': int(stat.st_atime),
                        'ino': stat.st_ino,
                        'mode': stat.st_mode,
                        'system': system_name,
                        'client': client_name,
                        'map_name': map_name,
                        'now': now,
                    })
                    
                    if len(self.file_batch) >= self.batch_size:
                        self._flush_file_batch()
                    
                    self.stats['files_added'] += 1
                    logger.info(f"      Added file-based map entry: {virtual_filename}")
                except Exception as e:
                    logger.error(f"      Error adding file {full_path}: {e}")
                    self.stats['errors'] += 1
            else:
                # Extract all files from ZIP
                logger.info(f"      Extracting all files from ZIP: {full_path}")
                try:
                    import zipfile
                    with zipfile.ZipFile(full_path, 'r') as zf:
                        for info in zf.filelist:
                            if info.is_dir():
                                continue  # Skip directories
                            
                            virtual_filename = os.path.basename(info.filename)
                            virtual_path = os.path.join(
                                self.mount_path,
                                client_name,
                                system_name,
                                map_name,
                                virtual_filename
                            )
                            
                            now = int(time.time())
                            stat = os.stat(full_path)  # Get stats of the ZIP file
                            
                            self.file_batch.append({
                                'source_path': f"{full_path}#ZIP#{info.filename}",
                                'virtual_path': virtual_path,
                                'filename': virtual_filename,
                                'extension': os.path.splitext(virtual_filename)[1][1:].lower(),
                                'size': info.file_size,
                                'mtime': int(stat.st_mtime),
                                'ctime': int(stat.st_ctime),
                                'atime': int(stat.st_atime),
                                'ino': stat.st_ino,
                                'mode': stat.st_mode,
                                'system': system_name,
                                'client': client_name,
                                'map_name': map_name,
                                'now': now,
                            })
                            
                            if len(self.file_batch) >= self.batch_size:
                                self._flush_file_batch()
                            
                            self.stats['files_added'] += 1
                            logger.debug(f"        Added zip entry: {virtual_filename} from {info.filename}")
                        
                        logger.info(f"      Extracted {len(zf.filelist)} files from {os.path.basename(full_path)}")
                except Exception as e:
                    logger.error(f"      Error extracting ZIP {full_path}: {e}")
                    self.stats['errors'] += 1
        else:
            # Regular file (not zipped)
            if not os.path.exists(full_path):
                logger.warning(f"      File not found: {full_path}")
                return
            
            logger.debug(f"      Adding file entry: {full_path}")
            
            try:
                stat = os.stat(full_path)
                virtual_filename = os.path.basename(full_path)
                virtual_path = os.path.join(
                    self.mount_path,
                    client_name,
                    system_name,
                    map_name,
                    virtual_filename
                )
                
                now = int(time.time())
                
                self.file_batch.append({
                    'source_path': full_path,
                    'virtual_path': virtual_path,
                    'filename': virtual_filename,
                    'extension': os.path.splitext(virtual_filename)[1][1:].lower(),
                    'size': stat.st_size,
                    'mtime': int(stat.st_mtime),
                    'ctime': int(stat.st_ctime),
                    'atime': int(stat.st_atime),
                    'ino': stat.st_ino,
                    'mode': stat.st_mode,
                    'system': system_name,
                    'client': client_name,
                    'map_name': map_name,
                    'now': now,
                })
                
                if len(self.file_batch) >= self.batch_size:
                    self._flush_file_batch()
                
                self.stats['files_added'] += 1
                logger.info(f"      Added file-based map entry: {virtual_filename}")
            except Exception as e:
                logger.error(f"      Error adding file {full_path}: {e}")
                self.stats['errors'] += 1
    
    def _sync_query_map(self, client_name: str, system_name: str, map_name: str, 
                       system_config: dict, map_config: dict):
        """Sync files from a query map to database."""
        # Get query configuration
        query_cfg = get_query_config(map_config)
        if not query_cfg:
            logger.warning(f"      No query config for {map_name}")
            return
        
        extensions = query_cfg.get("extensions", [])
        source_dir = query_cfg.get("source_dir", "Software")
        source_dir = self._resolve_source_dir_for_layout(source_dir, system_config)
        extension_map = query_cfg.get("extension_map", {})
        transforms = map_config.get("transforms", {})
        preserve_exact_filenames = query_cfg.get("preserve_exact_filenames", False)
        
        # Build source directory path
        local_base_path = system_config.get("local_base_path", "")
        source_path = os.path.join(
            self.filestore,
            "Native",
            local_base_path,
            source_dir
        )
        
        if not os.path.exists(source_path):
            logger.warning(f"      Source directory not found: {source_path}")
            return
        
        # Count total files first for progress reporting
        logger.info(f"      Counting files in {map_name}...")
        total_files = self._count_files(source_path, extensions, system_config.get("download_layout"))
        logger.info(f"      Processing {total_files} files in {map_name}...")
        
        # Scan for files with matching extensions
        file_count = 0
        if system_config.get("download_layout") == "source_based":
            file_count += self._scan_directory_recursive(
                source_path, client_name, system_name, map_name,
                extensions, extension_map, transforms, total_files, preserve_exact_filenames
            )
        else:
            for ext in extensions:
                ext_upper = ext.upper()
                
                # Check extension subdirectory (e.g., Software/DSK/)
                ext_dir = os.path.join(source_path, ext_upper)
                if os.path.isdir(ext_dir):
                    file_count += self._scan_directory(
                        ext_dir, client_name, system_name, map_name,
                        [ext_upper], extension_map, transforms, total_files, preserve_exact_filenames
                    )
                
                # Also check lowercase
                ext_dir_lower = os.path.join(source_path, ext.lower())
                if os.path.isdir(ext_dir_lower) and ext_dir_lower != ext_dir:
                    file_count += self._scan_directory(
                        ext_dir_lower, client_name, system_name, map_name,
                        [ext_upper], extension_map, transforms, total_files, preserve_exact_filenames
                    )
            
            # Also scan source_dir directly for files (flat layout)
            file_count += self._scan_directory(
                source_path, client_name, system_name, map_name,
                extensions, extension_map, transforms, total_files, preserve_exact_filenames
            )
        
        logger.info(f"      ✓ Processed {file_count}/{total_files} files in {map_name}")
    
    def _scan_system_directory(self, base_path: str, client_name: str, system_name: str, 
                               map_configs: List[dict]):
        """
        Scan entire system directory and match files to appropriate maps.
        
        This scans all files under the system's base path and determines which map(s)
        each file belongs to based on extension and location.
        """
        file_count = 0
        unmatched_count = 0
        
        # Get manufacturer and canonical name for pack context lookups
        manufacturer = None
        canonical_name = None
        for client in self.config.get("clients", []):
            if client.get("name") == client_name:
                for system in client.get("systems", []):
                    if system.get("name") == system_name:
                        manufacturer = system.get("manufacturer")
                        canonical_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
                        break
                break
        
        try:
            for root, _, files in os.walk(base_path):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, base_path)
                    
                    # Get file extension
                    _, ext = os.path.splitext(filename)
                    ext = ext[1:].upper() if ext else ""
                    
                    # If no extension, try to get pack context and apply default extension
                    if not ext and manufacturer and canonical_name:
                        pack_context = self._get_pack_context_for_file(manufacturer, canonical_name, file_path)
                        if pack_context and pack_context.default_extension:
                            ext = pack_context.default_extension.upper()
                            logger.debug(f"      File {filename} has no extension, applying pack default: {ext}")
                    
                    # Try to match file to a map
                    matched = False
                    for map_info in map_configs:
                        if ext in map_info['extensions']:
                            # File extension matches this map
                            preserve_exact = map_info.get('preserve_exact_filenames', False)
                            self._add_file_to_database(
                                file_path, client_name, system_name, map_info['name'],
                                ext, map_info['extension_map'], map_info['transforms'],
                                preserve_exact
                            )
                            file_count += 1
                            matched = True
                            break  # File matched to first applicable map
                    
                    if not matched and ext:
                        # File has extension but didn't match any map
                        unmatched_count += 1
                        logger.debug(f"      Unmatched file: {relative_path} (ext: {ext})")
                    
                    # Progress reporting
                    if file_count > 0 and file_count % 500 == 0:
                        logger.info(f"      Progress: {file_count} files processed...")
                        self._emit_progress('files', 
                                          processed=file_count,
                                          added=self.stats['files_added'],
                                          updated=self.stats['files_updated'])
        
        except Exception as e:
            logger.error(f"Error scanning system directory {base_path}: {e}")
            self.stats['errors'] += 1
        
        logger.info(f"    ✓ Processed {file_count} files for {system_name} ({unmatched_count} unmatched)")
        self._emit_progress('system_complete', 
                          system=system_name,
                          files=file_count,
                          unmatched=unmatched_count)

    
    def _count_files(self, dir_path: str, extensions: List[str], layout: Optional[str] = None) -> int:
        """Count total files matching extensions for progress tracking."""
        if not os.path.isdir(dir_path):
            return 0
        
        count = 0
        scanned = 0
        last_log_time = time.monotonic()
        extensions_upper = {e.upper() for e in extensions}
        
        try:
            if layout == "source_based":
                # Recursive count
                logger.info(f"      Counting files in {dir_path} (recursive)...")
                for root, _, files in os.walk(dir_path):
                    for filename in files:
                        scanned += 1
                        _, ext = os.path.splitext(filename)
                        ext = ext[1:].upper() if ext else ""
                        if ext in extensions_upper:
                            count += 1
                        if time.monotonic() - last_log_time >= 5:
                            logger.info(f"      Counting files... {scanned} scanned, {count} matching")
                            last_log_time = time.monotonic()
            else:
                # Flat count
                logger.info(f"      Counting files in {dir_path} (flat)...")
                for entry in os.scandir(dir_path):
                    if entry.is_file():
                        scanned += 1
                        _, ext = os.path.splitext(entry.name)
                        ext = ext[1:].upper() if ext else ""
                        if ext in extensions_upper:
                            count += 1
                        if time.monotonic() - last_log_time >= 5:
                            logger.info(f"      Counting files... {scanned} scanned, {count} matching")
                            last_log_time = time.monotonic()
        except Exception:
            pass
        
        return count
    
    def _flush_batch(self):
        """Commit pending operations to database."""
        # Flush any pending file batch first
        self._flush_file_batch()
        
        if self.conn:
            self.conn.commit()
    
    def _scan_directory(self, dir_path: str, client_name: str, system_name: str,
                       map_name: str, extensions: List[str], extension_map: dict,
                       transforms: dict, total_files: int = 0, preserve_exact_filenames: bool = False) -> int:
        """
        Scan a directory for files and add them to database.
        
        Returns:
            Number of files found
        """
        if not os.path.isdir(dir_path):
            return 0
        
        file_count = 0
        
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file():
                    # Check if extension matches
                    _, ext = os.path.splitext(entry.name)
                    ext = ext[1:].upper() if ext else ""
                    
                    if ext in [e.upper() for e in extensions]:
                        self._add_file_to_database(
                            entry.path, client_name, system_name, map_name,
                            ext, extension_map, transforms, preserve_exact_filenames
                        )
                        file_count += 1
                        
                        # Progress reporting every 100 files
                        if total_files > 0 and file_count % 100 == 0:
                            progress = (self.stats['files_added'] + self.stats['files_updated']) / total_files * 100
                            logger.info(f"         Progress: {progress:.1f}% ({self.stats['files_added'] + self.stats['files_updated']}/{total_files})")
        except Exception as e:
            logger.error(f"Error scanning directory {dir_path}: {e}")
            self.stats['errors'] += 1
        
        return file_count

    def _scan_directory_recursive(self, dir_path: str, client_name: str, system_name: str,
                                 map_name: str, extensions: List[str], extension_map: dict,
                                 transforms: dict, total_files: int = 0, preserve_exact_filenames: bool = False) -> int:
        """Recursively scan a directory for files and add them to database."""
        if not os.path.isdir(dir_path):
            return 0

        file_count = 0
        extensions_upper = {e.upper() for e in extensions}
        
        # Get manufacturer and canonical name for pack context lookups
        manufacturer = None
        canonical_name = None
        for client in self.config.get("clients", []):
            if client.get("name") == client_name:
                for system in client.get("systems", []):
                    if system.get("name") == system_name:
                        manufacturer = system.get("manufacturer")
                        canonical_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
                        break
                break
        
        try:
            for root, _, files in os.walk(dir_path):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    _, ext = os.path.splitext(filename)
                    ext_original = ext[1:].upper() if ext else ""
                    ext = ext_original
                    
                    # Get pack context for this specific file to check for default_extension
                    applied_default = False
                    if not ext and manufacturer and canonical_name:
                        pack_context = self._get_pack_context_for_file(manufacturer, canonical_name, file_path)
                        if pack_context and pack_context.default_extension:
                            default_ext = pack_context.default_extension.upper()
                            ext = default_ext
                            applied_default = True
                            logger.debug(f"File {filename} has no extension, applying default from pack: {default_ext}")
                    
                    # File matches if extension is in the list, OR if we applied a default extension that's in the list
                    if ext in extensions_upper:
                        self._add_file_to_database(
                            file_path, client_name, system_name, map_name,
                            ext, extension_map, transforms, preserve_exact_filenames
                        )
                        file_count += 1
                        
                        # Progress reporting every 100 files
                        if total_files > 0 and file_count % 100 == 0:
                            progress = (self.stats['files_added'] + self.stats['files_updated']) / total_files * 100
                            logger.info(f"         Progress: {progress:.1f}% ({self.stats['files_added'] + self.stats['files_updated']}/{total_files})")
        except Exception as e:
            logger.error(f"Error scanning directory {dir_path}: {e}")
            self.stats['errors'] += 1

        return file_count

    def _resolve_source_dir_for_layout(self, source_dir: str, system_config: dict) -> str:
        layout = system_config.get("download_layout")
        if layout != "source_based":
            return source_dir
        normalized = (source_dir or "").replace("\\", "/").strip("/").lower()
        if "sources" in normalized:
            return source_dir
        if "bios" in normalized.split("/"):
            return source_dir
        return os.path.join(source_dir, "Sources")
    
    def _add_file_to_database(self, source_path: str, client_name: str, system_name: str,
                             map_name: str, extension: str, extension_map: dict, 
                             transforms: dict, preserve_exact_filenames: bool = False):
        """
        Add file to batch for processing.
        
        Args:
            source_path: Actual file path on filesystem
            client_name: Client name (e.g., 'MiSTer')
            system_name: System name (e.g., 'Atari2600')
            map_name: Map name (e.g., 'ROMs')
            extension: File extension (e.g., 'BIN')
            extension_map: Mapping of extensions (e.g., {'SFC': 'SMC'})
            transforms: Transform specifications for this extension
            preserve_exact_filenames: If True, skip duplicates instead of renaming (default False)
        """
        try:
            # Track that we've seen this file
            self.seen_source_paths.add(source_path)
            
            # Check if this file is already in the batch with a different map_name
            # If so, skip it to preserve the first map_name (usually from file-based maps)
            for existing_entry in self.file_batch:
                if existing_entry['source_path'] == source_path:
                    logger.debug(f"File {source_path} already in batch with map {existing_entry['map_name']}, skipping map {map_name}")
                    return
            
            # Get file stats
            stat = os.stat(source_path)
            filename = os.path.basename(source_path)
            
            # Determine virtual extension (may be mapped)
            virtual_ext = extension_map.get(extension, extension)
            
            # Check if there's a transform for this extension
            has_transform = extension in transforms
            if has_transform:
                try:
                    transform_specs = transforms[extension]
                    pipeline = build_transform_pipeline(source_path, transform_specs)
                    detected_ext = pipeline.get_effective_output_extension()
                    if detected_ext:
                        virtual_ext = detected_ext
                except Exception as e:
                    logger.warning(f"Failed to build transform pipeline for {filename}: {e}")
            
            # Build virtual filename
            base_name, _ = os.path.splitext(filename)
            virtual_filename = f"{base_name}.{virtual_ext.lower()}"
            
            # Handle duplicate filenames in the same directory
            # Check both the current batch AND the database for existing filenames
            dir_key = f"{client_name}/{system_name}/{map_name}"
            
            # Check in-memory batch for files with same base name (including suffixed versions)
            import re as regex_module
            duplicates_in_batch = []
            for entry in self.file_batch:
                if f"{entry['client']}/{entry['system']}/{entry['map_name']}" == dir_key:
                    entry_filename = entry['filename']
                    # Match exact filename OR filename_N.ext pattern
                    if (entry_filename == virtual_filename or 
                        (entry_filename.startswith(f"{base_name}_") and 
                         regex_module.match(f"^{regex_module.escape(base_name)}_[0-9]+\\.{virtual_ext.lower()}$", entry_filename))):
                        duplicates_in_batch.append(entry)
            
            # Check database for existing files with this name in this directory
            duplicates_in_db = []
            try:
                # Query for exact match OR files with _N suffix pattern
                # This ensures we don't match "Action Man - Action Force.bin" when looking for "Action Man.bin"
                import re as regex_module
                query = """
                    SELECT filename FROM files 
                    WHERE client = %s AND system = %s AND map_name = %s 
                    AND (filename = %s OR filename ~ %s)
                """
                # Regex pattern: basename_digits.extension (e.g., "Action Man_2.bin")
                # Escape special regex characters in base_name
                escaped_base = regex_module.escape(base_name)
                pattern = f"^{escaped_base}_[0-9]+\\.{virtual_ext.lower()}$"
                self.cursor.execute(query, (client_name, system_name, map_name, virtual_filename, pattern))
                duplicates_in_db = [row[0] for row in self.cursor.fetchall()]
            except Exception as e:
                logger.warning(f"Failed to check for duplicates in DB: {e}")
            
            # Count total duplicates
            total_duplicates = len(duplicates_in_batch) + (1 if virtual_filename in duplicates_in_db else 0)
            
            if total_duplicates > 0:
                if preserve_exact_filenames:
                    # Skip this file - keep the one we already have
                    logger.info(f"      Skipping duplicate {virtual_filename} in {dir_key} (preserve_exact_filenames=True)")
                    self.stats['skipped'] += 1
                    return
                else:
                    # Find the next available suffix number
                    # Check what suffixes already exist
                    existing_numbers = set()
                    for dup_filename in duplicates_in_db + [entry['filename'] for entry in duplicates_in_batch]:
                        # Check if it matches pattern: basename_N.ext
                        if dup_filename.startswith(base_name):
                            # Extract the part between base_name and .extension
                            remainder = dup_filename[len(base_name):]
                            if remainder.startswith('_'):
                                # Try to extract the number
                                parts = remainder[1:].split('.', 1)
                                if parts[0].isdigit():
                                    existing_numbers.add(int(parts[0]))
                            elif remainder == f".{virtual_ext.lower()}":
                                # This is the base filename without suffix (counts as 1)
                                existing_numbers.add(1)
                    
                    # Find next available number (start from 2)
                    suffix_num = 2
                    while suffix_num in existing_numbers:
                        suffix_num += 1
                    
                    # If the original exists, this becomes _2, _3, etc.
                    virtual_filename = f"{base_name}_{suffix_num}.{virtual_ext.lower()}"
                    logger.info(f"      Renaming duplicate: {base_name}.{virtual_ext.lower()} → {virtual_filename}")
            
            # Build virtual path
            virtual_path = os.path.join(
                self.mount_path,
                client_name,
                system_name,
                map_name,
                virtual_filename
            )
            
            now = int(time.time())
            
            # Add to batch
            self.file_batch.append({
                'source_path': source_path,
                'virtual_path': virtual_path,
                'filename': virtual_filename,
                'extension': virtual_ext,
                'size': stat.st_size,
                'mtime': int(stat.st_mtime),
                'ctime': int(stat.st_ctime),
                'atime': int(stat.st_atime),
                'ino': stat.st_ino,
                'mode': stat.st_mode,
                'system': system_name,
                'client': client_name,
                'map_name': map_name,
                'now': now,
            })
            
            # Flush batch if it reaches batch size
            if len(self.file_batch) >= self.batch_size:
                self._flush_file_batch()
                
        except Exception as e:
            logger.error(f"Failed to add file {source_path}: {e}")
            self.stats['errors'] += 1
    
    def _flush_file_batch(self):
        """Process accumulated file batch with bulk operations."""
        if not self.file_batch:
            return
        
        try:
            cursor = self.cursor
            
            # Use PostgreSQL's INSERT ... ON CONFLICT for upsert
            # IMPORTANT: Only update if the file already existed, but preserve map_name if set
            upsert_query = """
                INSERT INTO files (
                    source_path, virtual_path, filename, extension,
                    size, mtime, ctime, atime, ino, mode,
                    is_directory, system, client, map_name,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_path) DO UPDATE SET
                    virtual_path = COALESCE(EXCLUDED.virtual_path, files.virtual_path),
                    filename = COALESCE(EXCLUDED.filename, files.filename),
                    extension = COALESCE(EXCLUDED.extension, files.extension),
                    size = COALESCE(EXCLUDED.size, files.size),
                    mtime = GREATEST(COALESCE(EXCLUDED.mtime, 0), COALESCE(files.mtime, 0)),
                    ctime = COALESCE(EXCLUDED.ctime, files.ctime),
                    atime = COALESCE(EXCLUDED.atime, files.atime),
                    ino = COALESCE(EXCLUDED.ino, files.ino),
                    mode = COALESCE(EXCLUDED.mode, files.mode),
                    system = COALESCE(EXCLUDED.system, files.system),
                    client = COALESCE(EXCLUDED.client, files.client),
                    map_name = COALESCE(files.map_name, EXCLUDED.map_name),
                    updated_at = EXCLUDED.updated_at
                RETURNING file_id, (xmax = 0) AS inserted
            """
            
            # Prepare batch data
            batch_data = []
            for file_info in self.file_batch:
                batch_data.append((
                    file_info['source_path'],
                    file_info['virtual_path'],
                    file_info['filename'],
                    file_info['extension'],
                    file_info['size'],
                    file_info['mtime'],
                    file_info['ctime'],
                    file_info['atime'],
                    file_info['ino'],
                    file_info['mode'],
                    False,  # is_directory
                    file_info['system'],
                    file_info['client'],
                    file_info['map_name'],
                    file_info['now'],
                    file_info['now']
                ))
            
            # Execute batch upsert and collect returned file_ids for metadata enrichment
            file_ids_for_enrichment = []
            for idx, batch_row in enumerate(batch_data):
                cursor.execute(upsert_query, batch_row)
                result = cursor.fetchone()
                if result:
                    file_id, inserted = result
                    file_ids_for_enrichment.append({
                        'file_id': file_id,
                        'file_info': self.file_batch[idx]
                    })
            
            # Update stats (rough estimate - PostgreSQL doesn't easily tell us insert vs update count with executemany)
            self.stats['files_updated'] += len(self.file_batch)
            
            # Commit files BEFORE metadata enrichment so foreign keys resolve
            self.conn.commit()
            
            # Now enrich metadata for files that were committed above
            for enrichment_data in file_ids_for_enrichment:
                try:
                    file_id = enrichment_data['file_id']
                    file_info = enrichment_data['file_info']
                    
                    # Prepare file_info dict for enrichment
                    enrichment_file_info = {
                        'file_id': file_id,
                        'filename': file_info['filename'],
                        'extension': file_info['extension'],
                        'map_name': file_info['map_name'],
                        'virtual_path': file_info['virtual_path'],
                        'size': file_info['size'],
                    }
                    
                    # enrich_file_metadata uses get_cursor(commit=True) so it commits immediately
                    # This is safe because files are already committed above
                    enrich_file_metadata(None, enrichment_file_info)
                except Exception as e:
                    logger.warning(f"Failed to enrich metadata for file {file_id}: {e}")
            
            # Clear batch
            self.file_batch.clear()
            
        except Exception as e:
            logger.error(f"Batch flush failed: {e}")
            self.stats['errors'] += len(self.file_batch)
            self.file_batch.clear()
            # Rollback to clean state
            self.conn.rollback()
    
    def _clean_deleted_files(self):
        """Remove files from database that no longer exist on filesystem."""
        logger.info("Cleaning up deleted files from database")

        # Get all source paths from database
        self.cursor.execute("SELECT file_id, source_path FROM files WHERE is_directory = false")
        rows = self.cursor.fetchall()

        for file_id, source_path in rows:
            # If we didn't see this file during scan and it doesn't exist, delete it
            if source_path not in self.seen_source_paths and not os.path.exists(source_path):
                self.cursor.execute("DELETE FROM files WHERE file_id = %s", (file_id,))
                self.stats['files_deleted'] += 1
                logger.debug(f"Deleted missing file: {source_path}")

        self.conn.commit()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync filesystem to TransFS database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--full", action="store_true", help="Full rescan (clear and rebuild)")
    parser.add_argument("--incremental", action="store_true", help="Incremental scan (default)")
    parser.add_argument("--client", help="Only sync specific client")
    parser.add_argument("--system", help="Only sync specific system")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load configuration
    logger.info("Loading configuration")
    config = read_config()
    
    # Create sync instance
    sync = DatabaseSync(config)
    
    # Perform sync
    if args.dry_run:
        logger.info("DRY RUN MODE - no changes will be made")
        # TODO: Implement dry-run mode
        sys.exit(0)
    
    stats = sync.full_sync(
        client_filter=args.client,
        system_filter=args.system
    )
    
    # Print summary
    print("\n=== Sync Complete ===")
    print(f"Files added:   {stats['files_added']}")
    print(f"Files updated: {stats['files_updated']}")
    print(f"Files deleted: {stats['files_deleted']}")
    print(f"Errors:        {stats['errors']}")
    print(f"Skipped:       {stats['skipped']}")


if __name__ == "__main__":
    main()
