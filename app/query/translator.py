"""
Virtual path to SQL query translation.

Converts FUSE readdir() path requests into efficient SQL queries.
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional
import os


@dataclass
class VirtualPathQuery:
    """Query parameters extracted from virtual path."""
    
    base_path: str
    filters: List[Tuple[str, str, str]]  # (column, operator, value)
    order_by: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = 0


class QueryBuilder:
    """Builds SQL queries from virtual paths."""
    
    def __init__(self):
        """Initialize query builder."""
        self.filter_keywords = {
            'genre', 'language', 'region', 'year',
            'prototype', 'homebrew', 'translation', 'hack'
        }
    
    def build_readdir_query(self, virtual_path: str) -> Tuple[str, List]:
        """
        Build SQL query for readdir() operation.
        
        Args:
            virtual_path: Virtual filesystem path (e.g., /Atari/5200/USA)
        
        Returns:
            (sql_query, parameters) tuple
        """
        query_params = self.parse_virtual_path(virtual_path)
        
        # Build WHERE clause
        where_clauses = []
        params = []
        
        # Match directory prefix
        # Virtual path like /Atari/5200 should match files under that path
        path_pattern = virtual_path.rstrip('/') + '/%'
        where_clauses.append("virtual_path LIKE %s")
        params.append(path_pattern)
        
        # Add metadata filters
        for column, operator, value in query_params.filters:
            if column in ['is_prototype', 'is_homebrew', 'is_translation', 'is_hack']:
                where_clauses.append(f"m.{column} = %s")
                params.append(1)
            elif column == 'year':
                where_clauses.append(f"m.year {operator} %s")
                params.append(int(value))
            else:
                where_clauses.append(f"m.{column} = %s")
                params.append(value)
        
        # Build full query
        sql = """
            SELECT 
                f.file_id, f.source_path, f.virtual_path, f.filename,
                f.extension, f.size, f.mtime, f.ctime, f.atime,
                f.ino, f.mode, f.is_directory, f.is_archive
            FROM files f
            LEFT JOIN metadata m ON f.file_id = m.file_id
            WHERE {}
        """.format(" AND ".join(where_clauses))
        
        # Add ordering
        if query_params.order_by:
            sql += f" ORDER BY {query_params.order_by}"
        else:
            sql += " ORDER BY f.filename"
        
        # Add pagination
        if query_params.limit:
            sql += f" LIMIT {query_params.limit}"
            if query_params.offset:
                sql += f" OFFSET {query_params.offset}"
        
        return (sql, params)
    
    def build_getattr_query(self, virtual_path: str) -> Tuple[str, List]:
        """
        Build SQL query for getattr() operation.
        
        Args:
            virtual_path: Full virtual file path
        
        Returns:
            (sql_query, parameters) tuple
        """
        sql = """
            SELECT 
                f.file_id, f.source_path, f.virtual_path, f.filename,
                f.extension, f.size, f.mtime, f.ctime, f.atime,
                f.ino, f.mode, f.is_directory, f.is_archive
            FROM files f
            WHERE f.virtual_path = %s
            LIMIT 1
        """
        
        return (sql, [virtual_path])
    
    def parse_virtual_path(self, virtual_path: str) -> VirtualPathQuery:
        """
        Parse virtual path into query parameters.
        
        Examples:
            /Atari/5200 → base_path=/Atari/5200, no filters
            /Atari/5200/USA → filter by region=USA
            /Atari/5200/Prototype → filter by is_prototype=1
        
        Args:
            virtual_path: Virtual filesystem path
        
        Returns:
            VirtualPathQuery object
        """
        parts = [p for p in virtual_path.split('/') if p]
        
        base_path = virtual_path
        filters = []
        
        # Check if last component is a filter keyword
        if parts:
            last_part = parts[-1]
            
            # Check for filter keywords
            if last_part.lower() in ['prototype', 'prototypes']:
                filters.append(('is_prototype', '=', '1'))
                base_path = '/'.join([''] + parts[:-1])
            
            elif last_part.lower() in ['homebrew']:
                filters.append(('is_homebrew', '=', '1'))
                base_path = '/'.join([''] + parts[:-1])
            
            elif last_part.lower() in ['translation', 'translations']:
                filters.append(('is_translation', '=', '1'))
                base_path = '/'.join([''] + parts[:-1])
            
            elif last_part.lower() in ['hack', 'hacks']:
                filters.append(('is_hack', '=', '1'))
                base_path = '/'.join([''] + parts[:-1])
            
            # Check for region codes (USA, Europe, Japan, etc.)
            elif last_part in ['USA', 'Europe', 'Japan', 'World', 'Germany', 'France', 'Spain', 'Italy']:
                filters.append(('region', '=', last_part))
                base_path = '/'.join([''] + parts[:-1])
        
        return VirtualPathQuery(
            base_path=base_path,
            filters=filters
        )
    
    def build_search_query(self, 
                          pattern: str,
                          filters: Optional[dict] = None,
                          limit: int = 100) -> Tuple[str, List]:
        """
        Build SQL query for searching files.
        
        Args:
            pattern: Filename search pattern
            filters: Optional metadata filters
            limit: Maximum results
        
        Returns:
            (sql_query, parameters) tuple
        """
        where_clauses = ["f.filename LIKE %s"]
        params = [f"%{pattern}%"]
        
        if filters:
            for key, value in filters.items():
                if key in ['is_prototype', 'is_homebrew', 'is_translation', 'is_hack']:
                    where_clauses.append(f"m.{key} = %s")
                    params.append(1 if value else 0)
                elif key in ['genre', 'language', 'region']:
                    where_clauses.append(f"m.{key} = %s")
                    params.append(value)
                elif key == 'year':
                    where_clauses.append("m.year = %s")
                    params.append(int(value))
        
        sql = f"""
            SELECT 
                f.file_id, f.source_path, f.virtual_path, f.filename,
                f.extension, f.size, f.mtime, f.ctime, f.atime,
                f.ino, f.mode, f.is_directory, f.is_archive,
                m.genre, m.language, m.region, m.year
            FROM files f
            LEFT JOIN metadata m ON f.file_id = m.file_id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY f.filename
            LIMIT {limit}
        """
        
        return (sql, params)
