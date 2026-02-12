"""
Database connection management.

Provides thread-safe connection pooling and initialization.
"""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .schema import CREATE_TABLES, PRAGMA_SETTINGS, get_schema_version

# Thread-local storage for connections
_thread_local = threading.local()

# Global database path
_db_path: Optional[Path] = None


def init_database(db_path: str = "/mnt/filestorefs/.transfs_metadata.db") -> None:
    """
    Initialize database with schema.
    
    Args:
        db_path: Path to SQLite database file
    """
    global _db_path
    _db_path = Path(db_path)
    
    # Ensure parent directory exists
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create connection and initialize schema
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        # Apply PRAGMA settings
        conn.executescript(PRAGMA_SETTINGS)
        
        # Create tables
        conn.executescript(CREATE_TABLES)
        
        # Check/update schema version
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
        row = cursor.fetchone()
        
        current_version = get_schema_version()
        if row is None:
            # First initialization
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (current_version, int(time.time()))
            )
            conn.commit()
        elif row[0] < current_version:
            # Future: Handle schema migrations here
            pass
            
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """
    Get thread-local database connection.
    
    Returns:
        SQLite connection with row_factory set
    """
    if _db_path is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    if not hasattr(_thread_local, 'connection') or _thread_local.connection is None:
        _thread_local.connection = sqlite3.connect(str(_db_path))
        _thread_local.connection.row_factory = sqlite3.Row
        
        # Apply PRAGMA settings to this connection
        _thread_local.connection.executescript(PRAGMA_SETTINGS)
    
    return _thread_local.connection


def close_connection() -> None:
    """Close thread-local connection."""
    if hasattr(_thread_local, 'connection') and _thread_local.connection is not None:
        _thread_local.connection.close()
        _thread_local.connection = None


def transaction(conn: Optional[sqlite3.Connection] = None):
    """
    Context manager for database transactions.
    
    Usage:
        with transaction() as conn:
            conn.execute("INSERT ...")
            conn.execute("UPDATE ...")
    """
    if conn is None:
        conn = get_connection()
    
    class TransactionContext:
        def __enter__(self):
            conn.execute("BEGIN")
            return conn
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
            return False
    
    return TransactionContext()
