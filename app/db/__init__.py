"""
Database module for metadata storage and querying.

This module provides SQLite-based metadata storage as an alternative
to the pickle-based cache system. Can be enabled/disabled via configuration.
"""

from .connection import get_connection, init_database, close_connection
from .models import FileEntry, FileMetadata, Collection, Transform, VirtualMapping

__all__ = [
    'get_connection',
    'init_database',
    'close_connection',
    'FileEntry',
    'FileMetadata',
    'Collection',
    'Transform',
    'VirtualMapping',
]
