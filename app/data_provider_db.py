"""
Database-based data provider (new system).

This provider uses the SQLite metadata database for file access.
Used when database mode is enabled.
"""
import logging
from typing import Optional, List
from pathlib import Path
import sqlite3

from data_provider import DataProvider, FileInfo, DirectoryListing
from db.connection import init_database, get_connection
from query.translator import QueryBuilder

logger = logging.getLogger(__name__)


class DatabaseDataProvider(DataProvider):
    """File system access using SQLite metadata database."""
    
    def __init__(self, db_path: str = "/mnt/filestorefs/.transfs_metadata.db"):
        """
        Initialize database provider.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.query_builder = QueryBuilder()
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize the provider and database."""
        logger.info(f"Initializing database-based data provider: {self.db_path}")
        
        try:
            # Initialize database schema if needed
            init_database(self.db_path)
            
            # Verify connection works
            conn = get_connection()
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            count = cursor.fetchone()[0]
            logger.info(f"Database ready with {count} files indexed")
            
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize database provider: {e}")
            self._initialized = False
            raise
    
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
            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
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
            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
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
            
            # Query database for source path
            conn = get_connection()
            cursor = conn.execute(
                "SELECT source_path FROM files WHERE virtual_path = ? LIMIT 1",
                (path,)
            )
            row = cursor.fetchone()
            
            if row is None:
                logger.debug(f"Path not found in database: {path}")
                return None
            
            source_path = row[0]
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
