"""
Data provider abstraction for file data access.

Allows switching between cache-based and database-based approaches using feature flags.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """File information for FUSE operations."""
    path: str
    filename: str
    size: int
    mtime: int
    ctime: int
    atime: int
    mode: int
    ino: int
    is_directory: bool
    is_archive: bool = False
    extension: Optional[str] = None
    # Metadata fields
    genre: Optional[str] = None
    region: Optional[str] = None
    language: Optional[str] = None
    year: Optional[int] = None


@dataclass
class DirectoryListing:
    """Result of listing a directory."""
    path: str
    entries: List[FileInfo]
    total_count: int
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class DataProvider(ABC):
    """Abstract base class for file data providers."""
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize the provider."""
        pass
    
    @abstractmethod
    def readdir(self, path: str) -> DirectoryListing:
        """
        List files in a directory.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            DirectoryListing with entries
        """
        pass
    
    @abstractmethod
    def getattr(self, path: str) -> Optional[FileInfo]:
        """
        Get file attributes.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            FileInfo or None if not found
        """
        pass
    
    @abstractmethod
    def open(self, path: str) -> Optional[str]:
        """
        Resolve a virtual path to actual filesystem path.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            Actual filesystem path or None
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the provider and release resources."""
        pass
    
    @property
    @abstractmethod
    def mode(self) -> str:
        """Return the provider mode (cache, database, hybrid)."""
        pass


class DataProviderFactory:
    """Factory for creating appropriate data providers."""
    
    @staticmethod
    def create(config: Dict[str, Any], existing_provider=None) -> DataProvider:
        """
        Create a data provider based on configuration.
        
        Args:
            config: Configuration dict from app.yaml
            existing_provider: Existing cache provider (for fallback)
        
        Returns:
            Appropriate DataProvider instance
        """
        db_config = config.get('database', {})
        mode = db_config.get('mode', 'disabled')
        enabled = db_config.get('enabled', False)
        
        logger.info(f"Creating data provider: mode={mode}, enabled={enabled}")
        
        if not enabled or mode == 'disabled':
            logger.info("Using cache-based provider (database disabled)")
            from .cache import CacheDataProvider
            return CacheDataProvider(existing_provider)
        
        elif mode == 'enabled':
            logger.info("Using database-based provider")
            from .db import DatabaseDataProvider
            return DatabaseDataProvider(config)
        
        elif mode == 'hybrid':
            logger.info("Using hybrid provider (database with cache fallback)")
            from .hybrid import HybridDataProvider
            return HybridDataProvider(existing_provider, config)
        
        else:
            logger.warning(f"Unknown database mode: {mode}, using cache")
            from .cache import CacheDataProvider
            return CacheDataProvider(existing_provider)
