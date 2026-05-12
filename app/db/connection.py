"""
PostgreSQL database connection management.

Provides thread-safe connection pooling and schema initialization.
"""

import os
import time
import logging
from typing import Optional
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from .schema import CREATE_TABLES, get_schema_version

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[pool.ThreadedConnectionPool] = None
_db_config = None


def init_database(
    host: Optional[str] = None,
    port: Optional[int] = None,
    dbname: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    pool_size: int = 5,
    max_overflow: int = 10
):
    """
    Initialize PostgreSQL connection pool and schema.
    
    Args:
        host: Database host (defaults to DB_HOST env var or 'postgres')
        port: Database port (defaults to DB_PORT env var or 5432)
        dbname: Database name (defaults to DB_NAME env var or 'transfs')
        user: Database user (defaults to DB_USER env var or 'transfs')
        password: Database password (defaults to DB_PASSWORD env var)
        pool_size: Minimum number of connections in pool
        max_overflow: Maximum overflow connections beyond pool_size
    """
    global _connection_pool, _db_config
    
    # Get config from environment or parameters
    _db_config = {
        'host': host or os.getenv('DB_HOST', 'postgres'),
        'port': int(port or os.getenv('DB_PORT', 5432)),
        'dbname': dbname or os.getenv('DB_NAME', 'transfs'),
        'user': user or os.getenv('DB_USER', 'transfs'),
        'password': password or os.getenv('DB_PASSWORD', 'transfs_pass'),
    }
    
    logger.info(f"Initializing database connection pool: {_db_config['user']}@{_db_config['host']}:{_db_config['port']}/{_db_config['dbname']}")
    
    # If a pool is already open, reuse it rather than creating a new one.
    # Creating a fresh ThreadedConnectionPool without closing the previous one leaks
    # the old min-connections (minconn persistent connections remain open in PostgreSQL),
    # which quickly exhausts the server's max_connections.
    if _connection_pool is not None:
        logger.debug("Database connection pool already initialized, skipping re-initialization")
        return
    
    # Create connection pool
    _connection_pool = pool.ThreadedConnectionPool(
        pool_size,
        pool_size + max_overflow,
        **_db_config
    )
    
    # Initialize schema
    _init_schema()
    
    logger.info("Database connection pool initialized")


def _init_schema():
    """Initialize database schema if needed."""
    conn = None
    try:
        conn = _connection_pool.getconn()
        cursor = conn.cursor()
        
        # Execute schema creation - split by semicolons and execute each statement
        # This is necessary because psycopg2.cursor.execute() only executes one statement at a time
        statements = CREATE_TABLES.split(';')
        for statement in statements:
            statement = statement.strip()
            if statement:  # Skip empty statements
                logger.debug(f"Executing schema statement: {statement[:80]}...")
                try:
                    cursor.execute(statement)
                except Exception as e:
                    logger.warning(f"Schema statement failed (may be idempotent): {e}")
                    conn.rollback()
        
        conn.commit()
        
        # Check/update schema version
        cursor.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
        row = cursor.fetchone()
        
        current_version = get_schema_version()
        if row is None:
            # First initialization
            cursor.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (%s, %s)",
                (current_version, int(time.time()))
            )
            conn.commit()
        elif row[0] < current_version:
            old_version = row[0]

            # v7: backfill file_client_maps from existing files records
            if old_version < 7:
                try:
                    cursor.execute("""
                        INSERT INTO file_client_maps
                            (file_id, client, system, map_name, virtual_path, created_at, updated_at)
                        SELECT file_id, client, system, map_name, virtual_path, created_at, updated_at
                        FROM files
                        WHERE client IS NOT NULL AND system IS NOT NULL AND map_name IS NOT NULL
                        ON CONFLICT (file_id, client, system, map_name) DO NOTHING
                    """)
                    conn.commit()
                    logger.info("Migration v7: backfilled file_client_maps from files table")
                except Exception as mig_err:
                    logger.warning(f"Migration v7 backfill failed: {mig_err}")
                    conn.rollback()

            # Record new schema version
            cursor.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (%s, %s)",
                (current_version, int(time.time()))
            )
            conn.commit()
            
    finally:
        if conn:
            _connection_pool.putconn(conn)


def get_connection():
    """
    Get a connection from the pool.
    
    Returns:
        PostgreSQL connection with RealDictCursor
        
    Note: Caller is responsible for returning connection via return_connection()
    """
    if _connection_pool is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    import time as time_module
    wait_start = time_module.time()
    conn = _connection_pool.getconn()
    wait_time = time_module.time() - wait_start
    
    # Log if we had to wait for a connection (performance indicator)
    if wait_time > 0.01:
        logger.debug(f"Connection pool wait: {wait_time:.3f}s (may indicate pool exhaustion)")
    
    return conn


def return_connection(conn):
    """Return a connection to the pool."""
    if _connection_pool and conn:
        _connection_pool.putconn(conn)


def close_connection():
    """Compatibility function - does nothing for connection pool."""
    pass


@contextmanager
def get_cursor(commit=True):
    """
    Context manager for database operations.
    
    Usage:
        with get_cursor() as cursor:
            cursor.execute("SELECT * FROM files")
            rows = cursor.fetchall()
    
    Args:
        commit: Whether to commit on successful exit (default True)
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            return_connection(conn)


def transaction():
    """
    Context manager for explicit transactions.
    
    Usage:
        with transaction() as cursor:
            cursor.execute("INSERT ...")
            cursor.execute("UPDATE ...")
    """
    return get_cursor(commit=True)


def close_pool():
    """Close all connections in the pool."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Database connection pool closed")

