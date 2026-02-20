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
import sqlite3
import argparse
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
import logging

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import read_config
from pathutils import get_client, get_system_info, find_map_entry, get_map_config, is_query_map, get_query_config
from transforms import build_transform_pipeline
from metadata import enrich_file_metadata, PackContext

logger = logging.getLogger(__name__)


class DatabaseSync:
    """Synchronizes filesystem to database based on clients.yaml configuration."""
    
    def __init__(self, config: dict, db_path: str = "/mnt/filestorefs/.transfs_metadata.db"):
        """
        Initialize database sync.
        
        Args:
            config: Configuration from read_config()
            db_path: Path to SQLite database
        """
        self.config = config
        self.db_path = db_path
        self.filestore = config.get("filestore", "/mnt/filestorefs")
        self.mount_path = "/mnt/transfs"
        
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
                    pack_context = PackContext(
                        pack_name=pack.get("name") or pack.get("id"),
                        ruleset=metadata.get("ruleset"),
                        ruleset_overrides=metadata.get("overrides"),
                        defaults=metadata.get("defaults"),
                        tags=metadata.get("tags") or [],
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
    
    def init_database(self):
        """Initialize database schema using centralized schema."""
        from db.connection import init_database as db_init_database
        
        logger.info(f"Initializing database: {self.db_path}")
        db_init_database(self.db_path)
        logger.info("Database schema initialized")
    
    def full_sync(self, client_filter: Optional[str] = None, system_filter: Optional[str] = None):
        """
        Perform full database synchronization.
        
        Args:
            client_filter: Only sync this client (e.g., "MiSTer")
            system_filter: Only sync this system (e.g., "Apple-II")
        """
        logger.info("Starting full database sync")
        start_time = time.time()
        
        # Initialize database
        self.init_database()
        
        # Scan all configured clients and systems
        clients_config = self.config.get("clients", [])
        
        for client_config in clients_config:
            client_name = client_config.get("name")
            
            # Apply client filter
            if client_filter and client_name != client_filter:
                logger.debug(f"Skipping client {client_name} (filter: {client_filter})")
                continue
            
            logger.info(f"Syncing client: {client_name}")
            
            systems = client_config.get("systems", [])
            for system_config in systems:
                system_name = system_config.get("name")
                
                # Apply system filter
                if system_filter and system_name != system_filter:
                    logger.debug(f"Skipping system {system_name} (filter: {system_filter})")
                    continue
                
                logger.info(f"  Syncing system: {client_name}/{system_name}")
                self._sync_system(client_config, system_config)
        
        # Clean up deleted files
        self._clean_deleted_files()
        
        duration = time.time() - start_time
        logger.info(
            f"Sync complete: {self.stats['files_added']} added, "
            f"{self.stats['files_updated']} updated, {self.stats['files_deleted']} deleted, "
            f"{self.stats['errors']} errors in {duration:.2f}s"
        )
        
        return self.stats
    
    def _sync_system(self, client_config: dict, system_config: dict):
        """Sync a single system's files to database."""
        client_name = client_config["name"]
        system_name = system_config["name"]
        local_base_path = system_config.get("local_base_path", "")
        
        # Process each map
        maps = system_config.get("maps", [])
        for map_entry in maps:
            map_name = list(map_entry.keys())[0]
            map_config = map_entry[map_name]
            
            # Skip non-query maps
            if not is_query_map(map_config):
                logger.debug(f"    Skipping non-query map: {map_name}")
                continue
            
            logger.info(f"    Syncing map: {map_name}")
            self._sync_query_map(client_name, system_name, map_name, system_config, map_config)
    
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
        
        # Scan for files with matching extensions
        file_count = 0
        if system_config.get("download_layout") == "source_based":
            file_count += self._scan_directory_recursive(
                source_path, client_name, system_name, map_name,
                extensions, extension_map, transforms
            )
        else:
            for ext in extensions:
                ext_upper = ext.upper()
                
                # Check extension subdirectory (e.g., Software/DSK/)
                ext_dir = os.path.join(source_path, ext_upper)
                if os.path.isdir(ext_dir):
                    file_count += self._scan_directory(
                        ext_dir, client_name, system_name, map_name,
                        [ext_upper], extension_map, transforms
                    )
                
                # Also check lowercase
                ext_dir_lower = os.path.join(source_path, ext.lower())
                if os.path.isdir(ext_dir_lower) and ext_dir_lower != ext_dir:
                    file_count += self._scan_directory(
                        ext_dir_lower, client_name, system_name, map_name,
                        [ext_upper], extension_map, transforms
                    )
            
            # Also scan source_dir directly for files (flat layout)
            file_count += self._scan_directory(
                source_path, client_name, system_name, map_name,
                extensions, extension_map, transforms
            )
        
        logger.info(f"      Found {file_count} files in {map_name}")
    
    def _scan_directory(self, dir_path: str, client_name: str, system_name: str,
                       map_name: str, extensions: List[str], extension_map: dict,
                       transforms: dict) -> int:
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
                            ext, extension_map, transforms
                        )
                        file_count += 1
        except Exception as e:
            logger.error(f"Error scanning directory {dir_path}: {e}")
            self.stats['errors'] += 1
        
        return file_count

    def _scan_directory_recursive(self, dir_path: str, client_name: str, system_name: str,
                                 map_name: str, extensions: List[str], extension_map: dict,
                                 transforms: dict) -> int:
        """Recursively scan a directory for files and add them to database."""
        if not os.path.isdir(dir_path):
            return 0

        file_count = 0
        extensions_upper = {e.upper() for e in extensions}
        try:
            for root, _, files in os.walk(dir_path):
                for filename in files:
                    _, ext = os.path.splitext(filename)
                    ext = ext[1:].upper() if ext else ""
                    if ext in extensions_upper:
                        self._add_file_to_database(
                            os.path.join(root, filename), client_name, system_name, map_name,
                            ext, extension_map, transforms
                        )
                        file_count += 1
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
                             transforms: dict):
        """Add or update a single file in the database."""
        try:
            # Track that we've seen this file
            self.seen_source_paths.add(source_path)
            
            # Get file stats
            stat = os.stat(source_path)
            filename = os.path.basename(source_path)
            
            # Determine virtual extension (may be mapped)
            virtual_ext = extension_map.get(extension, extension)
            
            # Check if there's a transform for this extension
            has_transform = extension in transforms
            if has_transform:
                # Build transform pipeline to get output extension
                try:
                    transform_specs = transforms[extension]
                    pipeline = build_transform_pipeline(source_path, transform_specs)
                    
                    # Get detected output extension if available
                    detected_ext = pipeline.get_effective_output_extension()
                    if detected_ext:
                        virtual_ext = detected_ext
                        logger.debug(f"Transform detected extension: {extension} -> {virtual_ext}")
                except Exception as e:
                    logger.warning(f"Failed to build transform pipeline for {filename}: {e}")
            
            # Build virtual filename
            base_name, _ = os.path.splitext(filename)
            virtual_filename = f"{base_name}.{virtual_ext.lower()}"
            
            # Build virtual path
            virtual_path = os.path.join(
                self.mount_path,
                client_name,
                system_name,
                map_name,
                virtual_filename
            )
            
            # Insert or update in database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # If this source_path already exists, keep its current virtual_path
            cursor.execute(
                "SELECT file_id, virtual_path, filename, extension FROM files WHERE source_path = ?",
                (source_path,)
            )
            existing = cursor.fetchone()
            if existing:
                existing_virtual_path = existing[1]
                existing_filename = existing[2]
                existing_extension = existing[3]
                if existing_virtual_path:
                    virtual_path = existing_virtual_path
                if existing_filename:
                    virtual_filename = existing_filename
                if existing_extension:
                    virtual_ext = existing_extension

            # Ensure virtual path is unique within the database
            cursor.execute(
                "SELECT source_path FROM files WHERE virtual_path = ? AND source_path != ?",
                (virtual_path, source_path)
            )
            if cursor.fetchone():
                hash_suffix = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:8]
                unique_filename = f"{base_name} [{hash_suffix}].{virtual_ext.lower()}"
                unique_path = os.path.join(
                    self.mount_path,
                    client_name,
                    system_name,
                    map_name,
                    unique_filename
                )

                counter = 1
                while True:
                    cursor.execute(
                        "SELECT source_path FROM files WHERE virtual_path = ? AND source_path != ?",
                        (unique_path, source_path)
                    )
                    if not cursor.fetchone():
                        virtual_filename = unique_filename
                        virtual_path = unique_path
                        break
                    counter += 1
                    unique_filename = f"{base_name} [{hash_suffix}-{counter}].{virtual_ext.lower()}"
                    unique_path = os.path.join(
                        self.mount_path,
                        client_name,
                        system_name,
                        map_name,
                        unique_filename
                    )
            
            now = int(time.time())
            
            # Check if exists
            if not existing:
                cursor.execute("SELECT file_id FROM files WHERE source_path = ?", (source_path,))
                existing = cursor.fetchone()
            
            if existing:
                # Update
                cursor.execute("""
                    UPDATE files SET
                        virtual_path = ?,
                        filename = ?,
                        extension = ?,
                        size = ?,
                        mtime = ?,
                        ctime = ?,
                        atime = ?,
                        ino = ?,
                        mode = ?,
                        system = ?,
                        client = ?,
                        map_name = ?,
                        updated_at = ?
                    WHERE source_path = ?
                """, (
                    virtual_path,
                    virtual_filename,
                    virtual_ext,
                    stat.st_size,
                    int(stat.st_mtime),
                    int(stat.st_ctime),
                    int(stat.st_atime),
                    stat.st_ino,
                    stat.st_mode,
                    system_name,
                    client_name,
                    map_name,
                    now,
                    source_path
                ))
                self.stats['files_updated'] += 1
                file_id = existing[0]
            else:
                # Insert
                cursor.execute("""
                    INSERT INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, system, client, map_name,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    source_path,
                    virtual_path,
                    virtual_filename,
                    virtual_ext,
                    stat.st_size,
                    int(stat.st_mtime),
                    int(stat.st_ctime),
                    int(stat.st_atime),
                    stat.st_ino,
                    stat.st_mode,
                    False,
                    system_name,
                    client_name,
                    map_name,
                    now,
                    now
                ))
                self.stats['files_added'] += 1
                file_id = cursor.lastrowid

            pack_context = None
            if system_name and client_name:
                # Resolve manufacturer/canonical from config
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
                if manufacturer and canonical_name:
                    pack_context = self._get_pack_context_for_file(manufacturer, canonical_name, source_path)

            enrich_file_metadata(
                conn,
                {
                    "file_id": file_id,
                    "filename": virtual_filename,
                    "extension": virtual_ext,
                    "map_name": map_name,
                    "virtual_path": virtual_path,
                    "size": stat.st_size,
                },
                pack_context=pack_context
            )
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to add file {source_path}: {e}")
            self.stats['errors'] += 1
    
    def _clean_deleted_files(self):
        """Remove files from database that no longer exist on filesystem."""
        logger.info("Cleaning up deleted files from database")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all source paths from database
        cursor.execute("SELECT file_id, source_path FROM files WHERE is_directory = 0")
        rows = cursor.fetchall()
        
        for file_id, source_path in rows:
            # If we didn't see this file during scan and it doesn't exist, delete it
            if source_path not in self.seen_source_paths and not os.path.exists(source_path):
                cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                self.stats['files_deleted'] += 1
                logger.debug(f"Deleted missing file: {source_path}")
        
        conn.commit()
        conn.close()


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
