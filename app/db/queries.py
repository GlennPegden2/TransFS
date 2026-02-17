"""
Database query helpers for database-driven file organization.

Supports querying files by system and extension instead of folder scanning.
Enables virtual mappings without requiring physical folder structure.
"""

from typing import List, Optional, Dict, Any
import logging

from db.connection import get_connection

logger = logging.getLogger(__name__)


def query_files_by_system_and_extensions(
    system: str,
    extensions: List[str],
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query files by system and extension(s).
    
    Args:
        system: System identifier (e.g., 'Apple/AppleII', 'Nintendo/NES')
        extensions: List of file extensions to match (e.g., ['dsk', 'do', 'po'])
        limit: Maximum number of results to return
    
    Returns:
        List of file dictionaries with keys: file_id, filename, extension, virtual_path, size, etc.
    """
    if not extensions:
        return []
    
    try:
        conn = get_connection()
        
        # Build WHERE clause for extensions (case-insensitive)
        placeholders = ','.join(['?' for _ in extensions])
        extensions_lower = [ext.lower() for ext in extensions]
        
        query = f"""
            SELECT 
                file_id, filename, extension, source_path, virtual_path,
                size, mtime, system
            FROM files
            WHERE system = ? 
            AND LOWER(extension) IN ({placeholders})
            AND is_directory = 0
            ORDER BY filename
        """
        
        params = [system] + extensions_lower
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    except Exception as e:
        logger.error(f"Error querying files: {e}", exc_info=True)
        return []


def query_files_by_system_and_content_type(
    system: str,
    content_types: List[str],
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query files by system and content type.
    
    Args:
        system: System identifier (e.g., 'Apple/AppleII')
        content_types: List of content types (e.g., ['disk_image', 'rom'])
        limit: Maximum number of results
    
    Returns:
        List of file dictionaries
    """
    if not content_types:
        return []
    
    try:
        conn = get_connection()
        
        placeholders = ','.join(['?' for _ in content_types])
        
        query = f"""
            SELECT 
                file_id, filename, extension, source_path, virtual_path,
                size, mtime, system, content_type
            FROM files
            WHERE system = ? 
            AND content_type IN ({placeholders})
            AND is_directory = 0
            ORDER BY filename
        """
        
        params = [system] + content_types
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    except Exception as e:
        logger.error(f"Error querying files by content type: {e}", exc_info=True)
        return []


def query_all_systems() -> List[str]:
    """
    Get list of all unique systems in database.
    
    Returns:
        List of system identifiers (e.g., ['Apple/AppleII', 'Nintendo/NES'])
    """
    try:
        conn = get_connection()
        
        cursor = conn.execute("""
            SELECT DISTINCT system
            FROM files
            WHERE system IS NOT NULL
            ORDER BY system
        """)
        
        rows = cursor.fetchall()
        return [row['system'] for row in rows]
    
    except Exception as e:
        logger.error(f"Error querying systems: {e}", exc_info=True)
        return []


def query_extensions_by_system(system: str) -> List[str]:
    """
    Get list of all extensions available in a system.
    
    Args:
        system: System identifier
    
    Returns:
        List of unique extensions found in system
    """
    try:
        conn = get_connection()
        
        cursor = conn.execute("""
            SELECT DISTINCT LOWER(extension) as ext
            FROM files
            WHERE system = ? AND extension IS NOT NULL
            ORDER BY ext
        """, (system,))
        
        rows = cursor.fetchall()
        return [row['ext'] for row in rows]
    
    except Exception as e:
        logger.error(f"Error querying extensions: {e}", exc_info=True)
        return []


def query_file_count_by_system_and_extension(
    system: str,
    extension: str
) -> int:
    """
    Get count of files matching system and extension.
    
    Useful for UI indicators (e.g., "47 .nib files")
    """
    try:
        conn = get_connection()
        
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM files
            WHERE system = ? AND LOWER(extension) = LOWER(?)
        """, (system, extension))
        
        row = cursor.fetchone()
        return row['count'] if row else 0
    
    except Exception as e:
        logger.error(f"Error querying file count: {e}", exc_info=True)
        return 0


def query_file_by_id(file_id: int) -> Optional[Dict[str, Any]]:
    """Get file details by file_id."""
    try:
        conn = get_connection()
        
        cursor = conn.execute("""
            SELECT * FROM files WHERE file_id = ?
        """, (file_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    except Exception as e:
        logger.error(f"Error querying file: {e}", exc_info=True)
        return None


def query_system_statistics(system: str) -> Dict[str, Any]:
    """
    Get statistics about a system (file counts, extensions, sizes).
    
    Returns:
        Dict with stats: {
            'total_files': N,
            'total_size': bytes,
            'extension_counts': {'dsk': 10, 'po': 5, ...},
            'extensions': ['dsk', 'po', ...]
        }
    """
    try:
        conn = get_connection()
        
        # Get file count and total size
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total_files,
                SUM(size) as total_size
            FROM files
            WHERE system = ? AND is_directory = 0
        """, (system,))
        
        row = cursor.fetchone()
        total_files = row['total_files'] or 0
        total_size = row['total_size'] or 0
        
        # Get extension counts
        cursor = conn.execute("""
            SELECT 
                LOWER(extension) as ext,
                COUNT(*) as count
            FROM files
            WHERE system = ? AND extension IS NOT NULL AND is_directory = 0
            GROUP BY LOWER(extension)
            ORDER BY count DESC
        """, (system,))
        
        ext_counts = {}
        extensions = []
        for row in cursor.fetchall():
            ext = row['ext']
            extensions.append(ext)
            ext_counts[ext] = row['count']
        
        return {
            'total_files': total_files,
            'total_size': total_size,
            'extension_counts': ext_counts,
            'extensions': extensions
        }
    
    except Exception as e:
        logger.error(f"Error getting system statistics: {e}", exc_info=True)
        return {
            'total_files': 0,
            'total_size': 0,
            'extension_counts': {},
            'extensions': []
        }
