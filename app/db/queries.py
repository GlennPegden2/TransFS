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


def query_files_by_system_and_query(
    system: str,
    query: Dict[str, Any],
    system_config: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query files by system and a structured query object.

    Supported query keys (extendable):
      - extensions: ["dsk", "po"] ("*" means no extension filter)
      - source_dir: "Software" (limits to /Native/<system>/source_dir/)
      - filters: [{"field": "year", "op": ">", "value": 1990}, ...]
      - logic: "and"|"or" (applies between filters)

    Supported fields (current):
      files table: extension, filename, source_path, virtual_path, size, mtime, system, content_type
      metadata table: genre, language, region, year, is_prototype, is_homebrew, is_translation, is_hack, tags
    """
    try:
        conn = get_connection()

        extensions = query.get("extensions") or []
        source_dir = query.get("source_dir")
        filters = query.get("filters") or []
        logic = (query.get("logic") or "and").lower()
        if logic not in {"and", "or"}:
            logic = "and"

        where_clauses = ["f.system = ?", "f.is_directory = 0"]
        params: List[Any] = [system]

        # Extension filter (case-insensitive)
        if extensions and "*" not in [str(e) for e in extensions] and "*" not in [str(e).upper() for e in extensions]:
            placeholders = ','.join(['?' for _ in extensions])
            where_clauses.append(f"LOWER(f.extension) IN ({placeholders})")
            params.extend([ext.lower() for ext in extensions])

        # Source directory filter
        if source_dir:
            if system_config and system_config.get("local_base_path"):
                base = f"/mnt/filestorefs/Native/{system_config['local_base_path'].rstrip('/')}/{source_dir.strip('/')}/"
                where_clauses.append("f.source_path LIKE ?")
                params.append(base + "%")
            else:
                where_clauses.append("f.source_path LIKE ?")
                params.append(f"%/{source_dir.strip('/')}/%")

        # Filter support
        metadata_fields = {
            "genre", "language", "region", "year",
            "is_prototype", "is_homebrew", "is_translation", "is_hack", "tags",
        }
        join_metadata = any(f.get("field") in metadata_fields for f in filters if isinstance(f, dict))

        filter_clauses = []
        for f in filters:
            if not isinstance(f, dict):
                continue
            field = f.get("field")
            op = (f.get("op") or "=").lower()
            value = f.get("value")

            if field in metadata_fields:
                column = f"m.{field}"
            else:
                column = f"f.{field}"

            if op in {"=", "eq"}:
                filter_clauses.append(f"{column} = ?")
                params.append(value)
            elif op in {"!=" , "ne"}:
                filter_clauses.append(f"{column} != ?")
                params.append(value)
            elif op in {">", "gt"}:
                filter_clauses.append(f"{column} > ?")
                params.append(value)
            elif op in {">=", "gte"}:
                filter_clauses.append(f"{column} >= ?")
                params.append(value)
            elif op in {"<", "lt"}:
                filter_clauses.append(f"{column} < ?")
                params.append(value)
            elif op in {"<=", "lte"}:
                filter_clauses.append(f"{column} <= ?")
                params.append(value)
            elif op == "like":
                filter_clauses.append(f"{column} LIKE ?")
                params.append(value)
            elif op == "in" and isinstance(value, list):
                placeholders = ','.join(['?' for _ in value])
                filter_clauses.append(f"{column} IN ({placeholders})")
                params.extend(value)
            elif op == "between" and isinstance(value, list) and len(value) == 2:
                filter_clauses.append(f"{column} BETWEEN ? AND ?")
                params.extend([value[0], value[1]])

        if filter_clauses:
            joiner = " OR " if logic == "or" else " AND "
            where_clauses.append("(" + joiner.join(filter_clauses) + ")")

        select = ""
        if join_metadata:
            select = (
                "SELECT f.file_id, f.filename, f.extension, f.source_path, f.virtual_path, "
                "f.size, f.mtime, f.system, f.content_type, "
                "m.genre, m.language, m.region, m.year, m.is_prototype, m.is_homebrew, m.is_translation, m.is_hack, m.tags "
                "FROM files f LEFT JOIN metadata m ON f.file_id = m.file_id"
            )
        else:
            select = (
                "SELECT f.file_id, f.filename, f.extension, f.source_path, f.virtual_path, "
                "f.size, f.mtime, f.system, f.content_type "
                "FROM files f"
            )

        query_sql = select + " WHERE " + " AND ".join(where_clauses) + " ORDER BY f.filename"
        if limit:
            query_sql += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(query_sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error querying files by query: {e}", exc_info=True)
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
