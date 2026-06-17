"""
Database-based data provider (new system).

This provider uses the PostgreSQL metadata database for file access.
Used when database mode is enabled.
"""
import logging
import threading
from typing import Optional, List, Dict, Any
from pathlib import Path

from . import DataProvider, FileInfo, DirectoryListing
from db.connection import init_database, get_cursor
from query.translator import QueryBuilder

logger = logging.getLogger(__name__)


class DatabaseDataProvider(DataProvider):
    """File system access using PostgreSQL metadata database."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize database provider.
        
        Args:
            config: Configuration dict from app.yaml
        """
        self.config = config or {}
        self.query_builder = QueryBuilder()
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize the provider and database."""
        logger.info("Initializing database-based data provider")
        
        try:
            # Initialize database schema if needed
            # Use larger pool for concurrent FUSE operations
            init_database(pool_size=100, max_overflow=100)
            
            # Check if we should sync on startup
            db_config = self.config.get('database', {})
            if db_config.get('sync_on_startup', False):
                logger.info("sync_on_startup enabled - starting background filesystem sync")
                # Start sync in background thread to avoid blocking initialization
                sync_thread = threading.Thread(target=self._perform_sync, daemon=True)
                sync_thread.start()
            
            # Verify connection works
            from db.connection import get_cursor
            with get_cursor(commit=False) as cursor:
                cursor.execute("SELECT COUNT(*) FROM files")
                count = cursor.fetchone()['count']
            logger.info(f"Database ready with {count} files indexed")
            
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize database provider: {e}")
            self._initialized = False
            raise
    
    def _perform_sync(self) -> None:
        """Perform filesystem to database synchronization (runs in background thread)."""
        try:
            from sync_database import DatabaseSync
            from config import read_config
            
            logger.info("Starting background filesystem sync")
            config = read_config()
            db_sync = DatabaseSync(config)
            db_sync.full_sync()
            
            stats = db_sync.stats
            logger.info(
                f"Filesystem sync complete: {stats.get('files_added', 0)} added, "
                f"{stats.get('files_updated', 0)} updated, "
                f"{stats.get('errors', 0)} errors"
            )
        except Exception as e:
            logger.error(f"Failed to perform filesystem sync: {e}", exc_info=True)

    
    def readdir(self, path: str) -> DirectoryListing:
        """
        List files in a directory using database.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            DirectoryListing with entries from database
        """
        if not self._initialized:
            self.initialize()
        
        try:
            logger.debug(f"Database readdir: {path}")
            
            # Build query for this path
            sql, params = self.query_builder.build_readdir_query(path)
            
            # Execute query
            with get_cursor(commit=False) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            
            # Convert rows to FileInfo objects
            entries = []
            for row in rows:
                entry = FileInfo(
                    path=row['virtual_path'],
                    filename=row['filename'],
                    size=row['size'],
                    mtime=row['mtime'],
                    ctime=row['ctime'],
                    atime=row['atime'],
                    mode=row['mode'],
                    ino=row['ino'],
                    is_directory=bool(row['is_directory']),
                    is_archive=bool(row['is_archive']),
                    extension=row['extension']
                )
                entries.append(entry)
            
            logger.debug(f"Database readdir returned {len(entries)} entries for {path}")
            
            return DirectoryListing(
                path=path,
                entries=entries,
                total_count=len(entries)
            )
        
        except Exception as e:
            logger.error(f"Database readdir error for {path}: {e}")
            return DirectoryListing(
                path=path,
                entries=[],
                total_count=0,
                errors=[str(e)]
            )
    
    def getattr(self, path: str) -> Optional[FileInfo]:
        """
        Get file attributes using database.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            FileInfo from database or None if not found
        """
        if not self._initialized:
            self.initialize()
        
        try:
            logger.debug(f"Database getattr: {path}")
            
            # Build query for this specific file
            sql, params = self.query_builder.build_getattr_query(path)
            
            # Execute query
            with get_cursor(commit=False) as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
            
            if row is None:
                logger.debug(f"File not found in database: {path}")
                return None
            
            # Convert to FileInfo
            entry = FileInfo(
                path=row['virtual_path'],
                filename=row['filename'],
                size=row['size'],
                mtime=row['mtime'],
                ctime=row['ctime'],
                atime=row['atime'],
                mode=row['mode'],
                ino=row['ino'],
                is_directory=bool(row['is_directory']),
                is_archive=bool(row['is_archive']),
                extension=row['extension']
            )
            
            logger.debug(f"Database getattr found: {path}")
            return entry
        
        except Exception as e:
            logger.error(f"Database getattr error for {path}: {e}")
            return None
    
    def open(self, path: str) -> Optional[str]:
        """
        Resolve virtual path to actual filesystem path.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            Actual source filesystem path or None
        """
        if not self._initialized:
            self.initialize()
        
        try:
            logger.debug(f"Database open: {path}")
            
            # Query database for source path using context manager
            with get_cursor(commit=False) as cursor:
                cursor.execute(
                    "SELECT source_path FROM files WHERE virtual_path = %s LIMIT 1",
                    (path,)
                )
                row = cursor.fetchone()
                
                if row is None:
                    logger.debug(f"Path not found in database: {path}")
                    return None
                
                source_path = row['source_path']
                logger.debug(f"Database open resolved {path} → {source_path}")
                return source_path
        
        except Exception as e:
            logger.error(f"Database open error for {path}: {e}")
            return None
    
    def close(self) -> None:
        """Close the provider and database connection."""
        logger.info("Closing database-based data provider")
        self._initialized = False
        # Database connections are thread-local and managed by connection.py
    
    @property
    def mode(self) -> str:
        """Return provider mode."""
        return "database"
