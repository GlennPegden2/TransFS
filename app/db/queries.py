"""
Database query helpers for database-driven file organization.

Supports querying files by system and extension instead of folder scanning.
Enables virtual mappings without requiring physical folder structure.
"""

from typing import List, Optional, Dict, Any
import logging

from db.connection import get_cursor

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
        with get_cursor(commit=False) as cursor:
            # Convert extensions to lowercase for case-insensitive matching
            extensions_lower = [ext.lower() for ext in extensions]
            
            placeholders = ','.join(['%s' for _ in extensions_lower])
            
            query = f"""
                SELECT 
                    file_id, filename, extension, source_path, virtual_path,
                    size, mtime, system
                FROM files
                WHERE system = %s 
                AND LOWER(extension) IN ({placeholders})
                AND is_directory = false
                ORDER BY filename
            """
            
            params = [system] + extensions_lower
            
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
    
    except Exception as e:
        logger.error(f"Error querying files: {e}", exc_info=True)
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
      - extension_filters: {"2MG": {"max_size": 908288, "min_size": 100}} - size constraints per extension
      - filters: [{"field": "year", "op": ">", "value": 1990}, ...]
      - logic: "and"|"or" (applies between filters)

    Supported fields (current):
      files table: extension, filename, source_path, virtual_path, size, mtime, system, content_type
      metadata table: genre, language, region, year, is_prototype, is_homebrew, is_translation, is_hack, tags
    """
    try:
        with get_cursor(commit=False) as cursor:
            extensions = list(query.get("extensions") or [])
            if bool(query.get("transform_zip", False)):
                existing_exts = {str(ext).upper() for ext in extensions}
                for archive_ext in ("ZIP", "7Z"):
                    if archive_ext not in existing_exts:
                        extensions.append(archive_ext)
            source_dir = query.get("source_dir")
            extension_filters = query.get("extension_filters") or {}
            filters = query.get("filters") or []
            logic = (query.get("logic") or "and").lower()
            if logic not in {"and", "or"}:
                logic = "and"

            where_clauses = ["f.system = %s", "f.is_directory = false"]
            params: List[Any] = [system]

        # Extension filter with optional size constraints (case-insensitive)
        if extensions and "*" not in [str(e) for e in extensions] and "*" not in [str(e).upper() for e in extensions]:
            # Build extension filter with optional size constraints per extension
            ext_conditions = []
            for ext in extensions:
                ext_lower = ext.lower()
                
                # Check if this extension has size constraints
                if ext in extension_filters:
                    ext_filter = extension_filters[ext]
                    size_conditions = []
                    
                    if 'max_size' in ext_filter:
                        max_size = ext_filter['max_size']
                        size_conditions.append(f"f.size <= {max_size}")
                        logger.info(f"Query: extension {ext} with max_size={max_size}")
                    
                    if 'min_size' in ext_filter:
                        min_size = ext_filter['min_size']
                        size_conditions.append(f"f.size >= {min_size}")
                        logger.info(f"Query: extension {ext} with min_size={min_size}")
                    
                    # Combine extension match with size conditions
                    if size_conditions:
                        size_clause = " AND ".join(size_conditions)
                        ext_conditions.append(f"(LOWER(f.extension) = '{ext_lower}' AND {size_clause})")
                    else:
                        ext_conditions.append(f"LOWER(f.extension) = '{ext_lower}'")
                else:
                    # No size filter for this extension
                    ext_conditions.append(f"LOWER(f.extension) = '{ext_lower}'")
            
            # Combine all extension conditions with OR
            if ext_conditions:
                where_clauses.append(f"({' OR '.join(ext_conditions)})")
                logger.info(f"Extension filter conditions: {' OR '.join(ext_conditions)}")

        # Source directory filter
        if source_dir:
            if system_config and system_config.get("local_base_path"):
                try:
                    from config import read_app_config
                    _filestore = read_app_config().get("filestore", "/data/retronas")
                except Exception:  # pylint: disable=broad-except
                    _filestore = "/data/retronas"
                base = f"{_filestore}/Native/{system_config['local_base_path'].rstrip('/')}/{source_dir.strip('/')}/"
                where_clauses.append("f.source_path LIKE %s")
                params.append(base + "%")
            else:
                where_clauses.append("f.source_path LIKE %s")
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
                filter_clauses.append(f"{column} = %s")
                params.append(value)
            elif op in {"!=" , "ne"}:
                filter_clauses.append(f"{column} != %s")
                params.append(value)
            elif op in {">", "gt"}:
                filter_clauses.append(f"{column} > %s")
                params.append(value)
            elif op in {">=", "gte"}:
                filter_clauses.append(f"{column} >= %s")
                params.append(value)
            elif op in {"<", "lt"}:
                filter_clauses.append(f"{column} < %s")
                params.append(value)
            elif op in {"<=", "lte"}:
                filter_clauses.append(f"{column} <= %s")
                params.append(value)
            elif op == "like":
                filter_clauses.append(f"{column} LIKE %s")
                params.append(value)
            elif op == "in" and isinstance(value, list):
                placeholders = ','.join(['%s' for _ in value])
                filter_clauses.append(f"{column} IN ({placeholders})")
                params.extend(value)
            elif op == "between" and isinstance(value, list) and len(value) == 2:
                filter_clauses.append(f"{column} BETWEEN %s AND %s")
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
            query_sql += " LIMIT %s"
            params.append(limit)

        cursor.execute(query_sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error querying files by query: {e}", exc_info=True)
        return []
        
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
        with get_cursor(commit=False) as cursor:
            placeholders = ','.join(['%s' for _ in content_types])
            
            query = f"""
                SELECT 
                    file_id, filename, extension, source_path, virtual_path,
                    size, mtime, system, content_type
                FROM files
                WHERE system = %s 
                AND content_type IN ({placeholders})
                AND is_directory = false
                ORDER BY filename
            """
            
            params = [system] + content_types
            
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
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
        with get_cursor(commit=False) as cursor:
            cursor.execute("""
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
        with get_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT DISTINCT LOWER(extension) as ext
                FROM files
                WHERE system = %s AND extension IS NOT NULL
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
        with get_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM files
                WHERE system = %s AND LOWER(extension) = LOWER(%s)
            """, (system, extension))
            
            row = cursor.fetchone()
            return row['count'] if row else 0
    
    except Exception as e:
        logger.error(f"Error querying file count: {e}", exc_info=True)
        return 0


def query_file_by_id(file_id: int) -> Optional[Dict[str, Any]]:
    """Get file details by file_id."""
    try:
        with get_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT * FROM files WHERE file_id = %s
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
        with get_cursor(commit=False) as cursor:
            # Get file count and total size
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_files,
                    SUM(size) as total_size
                FROM files
                WHERE system = %s AND is_directory = false
            """, (system,))
            
            row = cursor.fetchone()
            total_files = row['total_files'] or 0
            total_size = row['total_size'] or 0
            
            # Get extension counts
            cursor.execute("""
                SELECT 
                    LOWER(extension) as ext,
                    COUNT(*) as count
                FROM files
                WHERE system = %s AND extension IS NOT NULL AND is_directory = false
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


def query_files_by_client_system_and_map(
    client: str,
    system: str,
    map_name: str,
    extensions: Optional[List[str]] = None,
    extension_filters: Optional[Dict[str, Dict[str, int]]] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query files for a specific client, system, and map.
    
    Used by readdir() in database-only mode.
    
    Args:
        client: Client name (e.g., 'MiSTer')
        system: System name (e.g., 'Apple-II')
        map_name: Map name (e.g., 'FDs', 'HDs')
        extensions: Optional list of extensions to filter (e.g., ['DSK', 'DO', 'PO', '2MG'])
        extension_filters: Optional dict mapping extension to size constraints
                          e.g., {'2MG': {'max_size': 865*1024}} for files <= 865KB
        limit: Maximum number of results
    
    Returns:
        List of file records with source_path, filename, extension, size, mtime, etc.
    """
    try:
        with get_cursor(commit=False) as cursor:
            # Join through file_client_maps so the same physical file can appear under multiple clients.
            query = (
                "SELECT f.file_id, f.source_path, fcm.virtual_path, f.filename, f.extension, "
                "f.size, f.mtime, f.created_at, f.updated_at "
                "FROM files f "
                "JOIN file_client_maps fcm ON f.file_id = fcm.file_id "
                "WHERE fcm.client = %s AND fcm.system = %s AND fcm.map_name = %s"
            )
            params = [client, system, map_name]

            # Build extension filter with optional size constraints
            # Strategy: For each extension, if it has size filters apply them, otherwise match as-is
            if extensions:
                conditions = []

                for ext in extensions:
                    ext_lower = ext.lower()

                    # Check if this extension has size constraints
                    if extension_filters and ext in extension_filters:
                        filters = extension_filters[ext]
                        size_parts = []

                        if 'max_size' in filters:
                            max_size = filters['max_size']
                            size_parts.append(f"f.size <= {max_size}")
                            logger.info(f"Query: {ext} <= {max_size} bytes")

                        if 'min_size' in filters:
                            min_size = filters['min_size']
                            size_parts.append(f"f.size >= {min_size}")
                            logger.info(f"Query: {ext} >= {min_size} bytes")

                        # Combine with extension match
                        if size_parts:
                            size_clause = " AND ".join(size_parts)
                            conditions.append(f"(LOWER(f.extension) = '{ext_lower}' AND {size_clause})")
                        else:
                            conditions.append(f"LOWER(f.extension) = '{ext_lower}'")
                    else:
                        # No size filter for this extension, match it directly
                        conditions.append(f"LOWER(f.extension) = '{ext_lower}'")

                # Combine all conditions with OR
                if conditions:
                    query += f" AND ({' OR '.join(conditions)})"
                    logger.info(f"Final SQL condition: {' OR '.join(conditions)}")

            query += " ORDER BY f.filename"
            if limit:
                query += f" LIMIT {limit}"

            logger.info(f"Final SQL query: {query}")
            cursor.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                logger.info(f"No files found for client={client}, system={system}, map={map_name}")
                return []

            result = [dict(row) for row in rows]

            logger.info(f"query_files_by_client_system_and_map: found {len(result)} files for {client}/{system}/{map_name}")
            return result

    except Exception as e:
        logger.error(f"Error querying files for {client}/{system}/{map_name}: {e}", exc_info=True)
        return []


def query_file_by_client_system_map_and_name(
    client: str,
    system: str,
    map_name: str,
    filename: str
) -> Optional[Dict[str, Any]]:
    """
    Query a single file by client, system, map, and filename.
    
    Used by getattr() in database-only mode to fetch file attributes.
    
    Args:
        client: Client name (e.g., 'MiSTer')
        system: System name (e.g., 'Apple-II')
        map_name: Map name (e.g., 'FDs', 'HDs')
        filename: Filename to search for
    
    Returns:
        File record with source_path, virtual_path, extension, size, mtime, or None
    """
    try:
        with get_cursor(commit=False) as cursor:
            # Join through file_client_maps so the same physical file can appear under multiple clients.
            query = (
                "SELECT f.file_id, f.source_path, fcm.virtual_path, f.filename, f.extension, "
                "f.size, f.mtime, f.created_at, f.updated_at "
                "FROM files f "
                "JOIN file_client_maps fcm ON f.file_id = fcm.file_id "
                "WHERE fcm.client = %s AND fcm.system = %s AND fcm.map_name = %s AND f.filename = %s"
            )
            params = [client, system, map_name, filename]

            logger.info(f"Querying single file: client={client}, system={system}, map={map_name}, filename={filename}")
            cursor.execute(query, params)
            row = cursor.fetchone()

            if row:
                logger.info(f"Found file: {dict(row)}")
                return dict(row)
            else:
                logger.info(f"File not found: {filename}")
                return None

    except Exception as e:
        logger.error(f"Error querying file {client}/{system}/{map_name}/{filename}: {e}", exc_info=True)
        return None


def query_file_by_virtual_path(virtual_path: str) -> Optional[Dict[str, Any]]:
    """
    Query a single file by exact virtual path.

    This avoids basename ambiguity for preserve_structure paths where files may
    share the same filename in different subdirectories.
    """
    try:
        with get_cursor(commit=False) as cursor:
            # Query through file_client_maps so per-client virtual paths are resolved correctly.
            query = """
                SELECT f.file_id, f.source_path, fcm.virtual_path, f.filename, f.extension,
                       f.size, f.mtime, f.created_at, f.updated_at,
                       fcm.client, fcm.system, fcm.map_name
                FROM files f
                JOIN file_client_maps fcm ON f.file_id = fcm.file_id
                WHERE fcm.virtual_path = %s
                LIMIT 1
            """
            cursor.execute(query, [virtual_path])
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error querying file by virtual_path {virtual_path}: {e}", exc_info=True)
        return None


def query_file_by_source_path(source_path: str) -> Optional[Dict[str, Any]]:
    """
    Query a single file by its exact source path on disk.

    Used by config-driven getattr/open resolution where the source path is
    reconstructed from the virtual path components and config (no file_client_maps join).
    """
    try:
        with get_cursor(commit=False) as cursor:
            query = """
                SELECT file_id, source_path, virtual_path, filename, extension,
                       size, mtime, created_at, updated_at
                FROM files
                WHERE source_path = %s
                  AND is_directory = false
                LIMIT 1
            """
            cursor.execute(query, [source_path])
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error querying file by source_path {source_path}: {e}", exc_info=True)
        return None
