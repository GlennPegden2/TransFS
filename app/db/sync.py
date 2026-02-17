"""
Filesystem to database synchronization.

Scans filesystem and populates database with file information and metadata.
"""
import os
import time
from pathlib import Path
from typing import Optional, List
import logging

from db.connection import get_connection, transaction
from db.models import FileEntry, FileMetadata
from metadata.parser import parse_filename

logger = logging.getLogger(__name__)


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
    
    def initial_scan(self, skip_hidden: bool = True) -> dict:
        """
        Perform initial database population from filesystem.
        
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
        
        with transaction() as conn:
            for dirpath, dirnames, filenames in os.walk(self.root_path):
                # Skip hidden directories
                if skip_hidden:
                    dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                
                for filename in filenames:
                    if skip_hidden and filename.startswith('.'):
                        continue
                    
                    filepath = os.path.join(dirpath, filename)
                    
                    try:
                        self._sync_file(conn, filepath, stats)
                    except Exception as e:
                        logger.error(f"Error syncing {filepath}: {e}")
                        stats['errors'] += 1
        
        stats['duration'] = time.time() - stats['start_time']
        logger.info(
            f"Initial scan complete: {stats['files_added']} added, "
            f"{stats['files_updated']} updated, {stats['metadata_added']} metadata, "
            f"{stats['errors']} errors in {stats['duration']:.2f}s"
        )
        
        return stats
    
    def _sync_file(self, conn, filepath: str, stats: dict):
        """Sync a single file to database."""
        stat = os.stat(filepath)
        
        # Get relative path from root
        rel_path = os.path.relpath(filepath, self.root_path)
        source_path = str(Path("/mnt/filestorefs") / rel_path)
        
        # Calculate virtual path (simple mapping for now)
        virtual_path = self._calculate_virtual_path(source_path)
        
        filename = os.path.basename(filepath)
        extension = os.path.splitext(filename)[1][1:] if '.' in filename else None
        
        # Extract system from path (e.g., Apple/AppleII)
        system = self._extract_system(source_path)
        
        # Check if file exists in database
        cursor = conn.execute(
            "SELECT file_id, mtime FROM files WHERE source_path = ?",
            (source_path,)
        )
        row = cursor.fetchone()
        
        now = int(time.time())
        
        if row is None:
            # Insert new file
            cursor = conn.execute("""
                INSERT INTO files (
                    source_path, virtual_path, filename, extension,
                    size, mtime, ctime, atime, ino, mode,
                    is_directory, is_archive, system, content_type,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_path, virtual_path, filename, extension,
                stat.st_size, int(stat.st_mtime), int(stat.st_ctime), int(stat.st_atime),
                stat.st_ino, stat.st_mode,
                False, self._is_archive(filename), system, None,
                now, now
            ))
            
            file_id = cursor.lastrowid
            stats['files_added'] += 1
            
            # Extract and store metadata
            if self._should_parse_metadata(filename):
                self._add_metadata(conn, file_id, filename, stats)
        
        elif row['mtime'] < int(stat.st_mtime):
            # Update existing file
            file_id = row['file_id']
            conn.execute("""
                UPDATE files SET
                    size = ?, mtime = ?, atime = ?,
                    mode = ?, updated_at = ?
                WHERE file_id = ?
            """, (
                stat.st_size, int(stat.st_mtime), int(stat.st_atime),
                stat.st_mode, now, file_id
            ))
            stats['files_updated'] += 1
        
        else:
            stats['files_skipped'] += 1
    
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
    
    def _add_metadata(self, conn, file_id: int, filename: str, stats: dict):
        """Parse filename and add metadata to database."""
        try:
            parsed = parse_filename(filename)
            
            # Only insert if we extracted meaningful data
            if any([
                parsed.region, parsed.language, parsed.year,
                parsed.is_prototype, parsed.is_homebrew, parsed.is_translation, parsed.is_hack
            ]):
                import json
                
                conn.execute("""
                    INSERT INTO metadata (
                        file_id, genre, language, region, year,
                        is_prototype, is_homebrew, is_translation, is_hack,
                        tags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_id, None, parsed.language, parsed.region, parsed.year,
                    parsed.is_prototype, parsed.is_homebrew, parsed.is_translation, parsed.is_hack,
                    json.dumps(parsed.tags) if parsed.tags else None
                ))
                
                stats['metadata_added'] += 1
        
        except Exception as e:
            logger.debug(f"Failed to parse metadata for {filename}: {e}")
    
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
            conn = get_connection()
            cursor = conn.execute(
                "SELECT MAX(updated_at) FROM files"
            )
            row = cursor.fetchone()
            since = row[0] if row and row[0] else 0
        
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
