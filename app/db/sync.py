"""
Filesystem to database synchronization.

Scans filesystem and populates database with file information and metadata.

DEPRECATED: This module is being phased out in favor of sync_database.py which has
client/map awareness and properly populates virtual mappings. This module remains
for backwards compatibility but should not be used for new code.

Use sync_database.DatabaseSync instead.
"""
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from io import StringIO
import logging

from db.connection import get_cursor
from db.models import FileEntry, FileMetadata
from metadata.parser import parse_filename

logger = logging.getLogger(__name__)

# Batch size for database operations
BATCH_SIZE = 1000


class FilesystemSync:
    """Synchronizes filesystem to database."""
    
    def __init__(self, root_path: str, mount_path: str = "/mnt/transfs"):
        """
        Initialize filesystem sync.
        
        Args:
            root_path: Root filesystem path to scan (/mnt/filestorefs)
            mount_path: Virtual mount path (/mnt/transfs)
        """
        self.root_path = Path(root_path)
        self.mount_path = mount_path
    
    def _extract_system(self, source_path: str) -> Optional[str]:
        """
        Extract system from source path.
        
        Examples:
            /mnt/filestorefs/Native/Apple/AppleII/Software/... → Apple/AppleII
            /mnt/filestorefs/Native/Nintendo/NES/Software/... → Nintendo/NES
        """
        parts = source_path.split('/')
        # Pattern: /mnt/filestorefs/Native/Manufacturer/System/Software/...
        if len(parts) >= 6 and parts[4] == 'Native':
            manufacturer = parts[5]
            system = parts[6]
            return f"{manufacturer}/{system}"
        return None
    
    def initial_scan(self, skip_hidden: bool = False) -> dict:
        """
        Perform initial database population from filesystem.
        Uses batch operations and COPY for optimal performance.
        
        Args:
            skip_hidden: Skip hidden files/directories (starting with .)
        
        Returns:
            Statistics dict with counts
        """
        stats = {
            'files_added': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'metadata_added': 0,
            'errors': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"Starting initial scan of {self.root_path}")
        
        # Collect all file data first
        file_batch = []
        metadata_batch = []
        
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            # Skip hidden directories
            if skip_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            
            for filename in filenames:
                if skip_hidden and filename.startswith('.'):
                    continue
                
                filepath = os.path.join(dirpath, filename)
                
                try:
                    file_data = self._prepare_file_data(filepath)
                    if file_data:
                        file_batch.append(file_data)
                        
                        # Process batch when it reaches BATCH_SIZE
                        if len(file_batch) >= BATCH_SIZE:
                            batch_stats = self._process_file_batch(file_batch)
                            stats['files_added'] += batch_stats['added']
                            stats['files_updated'] += batch_stats['updated']
                            stats['files_skipped'] += batch_stats['skipped']
                            stats['metadata_added'] += batch_stats['metadata']
                            file_batch = []
                            
                except Exception as e:
                    logger.error(f"Error preparing {filepath}: {e}")
                    stats['errors'] += 1
        
        # Process remaining files in final batch
        if file_batch:
            batch_stats = self._process_file_batch(file_batch)
            stats['files_added'] += batch_stats['added']
            stats['files_updated'] += batch_stats['updated']
            stats['files_skipped'] += batch_stats['skipped']
            stats['metadata_added'] += batch_stats['metadata']
        
        stats['duration'] = time.time() - stats['start_time']
        logger.info(
            f"Initial scan complete: {stats['files_added']} added, "
            f"{stats['files_updated']} updated, {stats['metadata_added']} metadata, "
            f"{stats['errors']} errors in {stats['duration']:.2f}s"
        )
        
        # Populate virtual_mappings table from client configurations
        logger.info("Building virtual path mappings...")
        mapping_stats = self._build_virtual_mappings()
        stats.update(mapping_stats)
        
        return stats
    
    def _prepare_file_data(self, filepath: str) -> Optional[Dict]:
        """Prepare file data for batch insert without database access."""
        try:
            stat = os.stat(filepath)
        except OSError as e:
            logger.debug(f"Cannot stat {filepath}: {e}")
            return None
        
        # Get relative path from root
        rel_path = os.path.relpath(filepath, self.root_path)
        source_path = str(Path("/mnt/filestorefs") / rel_path)
        
        # Calculate virtual path
        virtual_path = self._calculate_virtual_path(source_path)
        
        filename = os.path.basename(filepath)
        extension = os.path.splitext(filename)[1][1:] if '.' in filename else None
        
        # Extract system from path
        system = self._extract_system(source_path)
        
        # Parse metadata if applicable
        metadata = None
        if self._should_parse_metadata(filename):
            try:
                parsed = parse_filename(filename)
                if any([
                    parsed.region, parsed.language, parsed.year,
                    parsed.is_prototype, parsed.is_homebrew, parsed.is_translation, parsed.is_hack
                ]):
                    import json
                    metadata = {
                        'genre': None,
                        'language': parsed.language,
                        'region': parsed.region,
                        'year': parsed.year,
                        'is_prototype': parsed.is_prototype,
                        'is_homebrew': parsed.is_homebrew,
                        'is_translation': parsed.is_translation,
                        'is_hack': parsed.is_hack,
                        'tags': json.dumps(parsed.tags) if parsed.tags else None
                    }
            except Exception as e:
                logger.debug(f"Failed to parse metadata for {filename}: {e}")
        
        now = int(time.time())
        
        return {
            'source_path': source_path,
            'virtual_path': virtual_path,
            'filename': filename,
            'extension': extension,
            'size': stat.st_size,
            'mtime': int(stat.st_mtime),
            'ctime': int(stat.st_ctime),
            'atime': int(stat.st_atime),
            'ino': stat.st_ino,
            'mode': stat.st_mode,
            'is_directory': False,
            'is_archive': self._is_archive(filename),
            'system': system,
            'content_type': None,
            'created_at': now,
            'updated_at': now,
            'metadata': metadata
        }
    
    def _process_file_batch(self, file_batch: List[Dict]) -> Dict:
        """Process a batch of files using COPY for optimal performance."""
        stats = {'added': 0, 'updated': 0, 'skipped': 0, 'metadata': 0}
        
        if not file_batch:
            return stats
        
        with get_cursor() as cursor:
            # Get existing files in this batch
            source_paths = [f['source_path'] for f in file_batch]
            cursor.execute(
                "SELECT source_path, mtime, file_id FROM files WHERE source_path = ANY(%s)",
                (source_paths,)
            )
            existing_files = {row['source_path']: (row['mtime'], row['file_id']) 
                            for row in cursor.fetchall()}
            
            # Separate into inserts and updates
            files_to_insert = []
            files_to_update = []
            file_ids_to_metadata = {}
            
            for file_data in file_batch:
                source_path = file_data['source_path']
                
                if source_path in existing_files:
                    existing_mtime, file_id = existing_files[source_path]
                    if file_data['mtime'] > existing_mtime:
                        files_to_update.append((
                            file_data['size'], file_data['mtime'], file_data['atime'],
                            file_data['mode'], file_data['updated_at'], file_id
                        ))
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1
                        
                    # Associate metadata with existing file_id
                    if file_data['metadata']:
                        file_ids_to_metadata[file_id] = file_data['metadata']
                else:
                    files_to_insert.append(file_data)
            
            # Bulk insert new files using COPY
            if files_to_insert:
                inserted_ids = self._bulk_insert_files(cursor, files_to_insert)
                stats['added'] = len(inserted_ids)
                
                # Associate metadata with newly inserted file_ids
                for i, file_data in enumerate(files_to_insert):
                    if file_data['metadata'] and i < len(inserted_ids):
                        file_ids_to_metadata[inserted_ids[i]] = file_data['metadata']
            
            # Bulk update existing files
            if files_to_update:
                cursor.executemany("""
                    UPDATE files SET
                        size = %s, mtime = %s, atime = %s,
                        mode = %s, updated_at = %s
                    WHERE file_id = %s
                """, files_to_update)
            
            # Bulk insert metadata
            if file_ids_to_metadata:
                stats['metadata'] = self._bulk_insert_metadata(cursor, file_ids_to_metadata)
        
        return stats
    
    def _bulk_insert_files(self, cursor, files_to_insert: List[Dict]) -> List[int]:
        """Insert files using PostgreSQL COPY for maximum performance."""
        # Use COPY FROM STDIN for bulk insert
        copy_data = StringIO()
        for file_data in files_to_insert:
            # Format: source_path, virtual_path, filename, extension, size, mtime, ctime, atime,
            #         ino, mode, is_directory, is_archive, system, content_type, created_at, updated_at
            row = [
                file_data['source_path'],
                file_data['virtual_path'] or '',
                file_data['filename'],
                file_data['extension'] or '',
                str(file_data['size']),
                str(file_data['mtime']),
                str(file_data['ctime']),
                str(file_data['atime']),
                str(file_data['ino']),
                str(file_data['mode']),
                'f',  # is_directory (false)
                't' if file_data['is_archive'] else 'f',
                file_data['system'] or '',
                file_data['content_type'] or '',
                str(file_data['created_at']),
                str(file_data['updated_at'])
            ]
            # Escape special characters for COPY format
            copy_data.write('\t'.join(row).replace('\\', '\\\\').replace('\n', '\\n').replace('\t', '\\t') + '\n')
        
        copy_data.seek(0)
        
        # Use COPY command
        cursor.copy_from(
            copy_data,
            'files',
            columns=('source_path', 'virtual_path', 'filename', 'extension', 'size', 
                    'mtime', 'ctime', 'atime', 'ino', 'mode', 'is_directory', 'is_archive',
                    'system', 'content_type', 'created_at', 'updated_at')
        )
        
        # Retrieve the file_ids that were just inserted
        source_paths = [f['source_path'] for f in files_to_insert]
        cursor.execute(
            "SELECT file_id FROM files WHERE source_path = ANY(%s) ORDER BY file_id",
            (source_paths,)
        )
        return [row['file_id'] for row in cursor.fetchall()]
    
    def _bulk_insert_metadata(self, cursor, file_ids_to_metadata: Dict[int, Dict]) -> int:
        """Bulk insert metadata records."""
        metadata_rows = []
        for file_id, metadata in file_ids_to_metadata.items():
            metadata_rows.append((
                file_id,
                metadata['genre'],
                metadata['language'],
                metadata['region'],
                metadata['year'],
                metadata['is_prototype'],
                metadata['is_homebrew'],
                metadata['is_translation'],
                metadata['is_hack'],
                metadata['tags']
            ))
        
        if metadata_rows:
            cursor.executemany("""
                INSERT INTO metadata (
                    file_id, genre, language, region, year,
                    is_prototype, is_homebrew, is_translation, is_hack, tags
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, metadata_rows)
        
        return len(metadata_rows)
    
    def _sync_file(self, filepath: str, stats: dict):
        """Legacy single-file sync - deprecated in favor of batch processing."""
        # Kept for backwards compatibility but not used in initial_scan
        pass
    
    def _calculate_virtual_path(self, source_path: str) -> Optional[str]:
        """
        Calculate virtual path from source path.
        
        Simple implementation - just replaces /mnt/filestorefs with /mnt/transfs.
        Future: Use virtual_mappings table for complex mappings.
        """
        if source_path.startswith("/mnt/filestorefs"):
            return source_path.replace("/mnt/filestorefs", self.mount_path, 1)
        return None
    
    def _is_archive(self, filename: str) -> bool:
        """Check if file is an archive."""
        archive_extensions = {'.zip', '.7z', '.rar', '.tar', '.gz', '.bz2'}
        ext = os.path.splitext(filename)[1].lower()
        return ext in archive_extensions
    
    def _should_parse_metadata(self, filename: str) -> bool:
        """Check if file should have metadata parsed."""
        # Skip system files, images, archives (for now)
        skip_extensions = {'.txt', '.md', '.jpg', '.png', '.gif', '.pdf', '.zip', '.7z'}
        ext = os.path.splitext(filename)[1].lower()
        return ext not in skip_extensions
    
    def _build_virtual_mappings(self) -> dict:
        """
        Build virtual_mappings table from client configurations.
        Uses pre-built system index and batch inserts for optimal performance.
        """
        from config import read_clients_config
        
        stats = {
            'mappings_added': 0,
            'mappings_updated': 0,
            'mappings_errors': 0
        }
        
        try:
            config_data = read_clients_config()
            clients_list = config_data.get('clients', [])

            def _normalize_system_key(value: Optional[str]) -> str:
                if not value:
                    return ""
                return "".join(ch.lower() for ch in value if ch.isalnum())
            
            # OPTIMIZATION #2: Build system index first
            # Map system_key -> [(client_name, system_config), ...]
            system_index: Dict[str, List[Tuple[str, dict]]] = {}
            
            for client_config in clients_list:
                client_name = client_config.get('name', '')
                if not client_name:
                    continue
                
                for system_config in client_config.get('systems', []):
                    system_name = system_config.get('name', '')
                    mapping_name = system_config.get('system_mapping_name', '')
                    canonical_name = system_config.get('canonical_name', '')
                    local_base_path = system_config.get('local_base_path', '')
                    manufacturer = system_config.get('manufacturer', '')

                    candidate_keys = {
                        _normalize_system_key(system_name),
                        _normalize_system_key(mapping_name),
                        _normalize_system_key(canonical_name),
                        _normalize_system_key(local_base_path),
                        _normalize_system_key(f"{manufacturer}/{mapping_name}") if manufacturer and mapping_name else "",
                    }
                    candidate_keys.discard("")

                    # Add this client/system to all matching keys
                    for key in candidate_keys:
                        if key not in system_index:
                            system_index[key] = []
                        system_index[key].append((client_name, system_config))
            
            logger.info(f"Built system index with {len(system_index)} unique system keys")
            
            with get_cursor() as cursor:
                # Clear existing mappings
                cursor.execute("DELETE FROM virtual_mappings")
                
                # Get all files from database
                cursor.execute(
                    "SELECT file_id, source_path, filename, extension, system "
                    "FROM files WHERE is_directory = false"
                )
                files = cursor.fetchall()
                
                logger.info(f"Building virtual mappings for {len(files)} files across all clients...")
                
                now = int(time.time())
                
                # OPTIMIZATION #3: Batch insert mappings
                mapping_batch = []
                
                # For each file, look up matching clients/systems from index
                for file_row in files:
                    file_id = file_row['file_id']
                    source_path = file_row['source_path']
                    filename = file_row['filename']
                    file_system = file_row['system']  # e.g., "Atari/2600"
                    
                    if not file_system:
                        continue
                    
                    file_system_key = _normalize_system_key(file_system)
                    
                    # Look up in index instead of looping through all clients/systems
                    matching_systems = system_index.get(file_system_key, [])
                    
                    for client_name, system_config in matching_systems:
                        # Build virtual path for this client/system
                        virtual_base = f"/mnt/transfs/{client_name}/{system_config['name']}/ROMs"
                        virtual_path = f"{virtual_base}/{filename}"
                        display_name = filename
                        
                        mapping_batch.append((
                            file_id, virtual_path, display_name, 
                            client_name, system_config['name'], now
                        ))
                        
                        # Process batch when it reaches size limit
                        if len(mapping_batch) >= BATCH_SIZE:
                            self._insert_mapping_batch(cursor, mapping_batch, stats)
                            mapping_batch = []
                
                # Process remaining mappings
                if mapping_batch:
                    self._insert_mapping_batch(cursor, mapping_batch, stats)
                
                logger.info(f"Virtual mappings built: {stats['mappings_added']} added, {stats['mappings_errors']} errors")
        
        except Exception as e:
            logger.error(f"Failed to build virtual mappings: {e}", exc_info=True)
            stats['mappings_errors'] += 1
        
        return stats
    
    def _insert_mapping_batch(self, cursor, mapping_batch: List[Tuple], stats: dict):
        """Insert a batch of virtual mappings."""
        try:
            cursor.executemany("""
                INSERT INTO virtual_mappings (file_id, virtual_path, display_name, client, system, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (virtual_path) DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    display_name = EXCLUDED.display_name,
                    client = EXCLUDED.client,
                    system = EXCLUDED.system
            """, mapping_batch)
            stats['mappings_added'] += len(mapping_batch)
        except Exception as e:
            logger.error(f"Failed to insert mapping batch: {e}")
            stats['mappings_errors'] += len(mapping_batch)
    
    def _add_metadata(self, cursor, file_id: int, filename: str, stats: dict):
        """Legacy single-file metadata insert - deprecated in favor of bulk operations."""
        # Kept for backwards compatibility but not used in optimized batch processing
        pass
    
    def incremental_sync(self, since: Optional[int] = None) -> dict:
        """
        Perform incremental sync of changed files.
        
        Args:
            since: Unix timestamp to sync files modified since (None = last sync)
        
        Returns:
            Statistics dict
        """
        if since is None:
            # Get last sync time from database
            with get_cursor(commit=False) as cursor:
                cursor.execute(
                    "SELECT MAX(updated_at) FROM files"
                )
                row = cursor.fetchone()
                since = row['max'] if row and row['max'] else 0
        
        stats = {
            'files_checked': 0,
            'files_updated': 0,
            'files_added': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"Starting incremental sync since {since}")
        
        # For now, just do a full scan
        # Future: Use inotify/watchdog for real-time updates
        return self.initial_scan()


def scan_filesystem(root_path: str = "/mnt/filestorefs", mount_path: str = "/mnt/transfs") -> dict:
    """
    Convenience function to scan filesystem and populate database.
    
    Args:
        root_path: Root filesystem path
        mount_path: Virtual mount path
    
    Returns:
        Statistics dictionary
    """
    sync = FilesystemSync(root_path, mount_path)
    return sync.initial_scan()
