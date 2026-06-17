"""
Hybrid data provider (database with cache fallback).

Uses the database when available, falls back to cache if there are issues.
Used when database mode is hybrid.
"""
import logging
from typing import Optional, Dict, Any

from . import DataProvider, FileInfo, DirectoryListing
from .db import DatabaseDataProvider
from .cache import CacheDataProvider

logger = logging.getLogger(__name__)


class HybridDataProvider(DataProvider):
    """Hybrid provider using database with cache fallback."""
    
    def __init__(self, cache_provider=None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize hybrid provider.
        
        Args:
            cache_provider: Fallback cache provider
            config: Configuration dict from app.yaml
        """
        self.db_provider = DatabaseDataProvider(config)
        self.cache_provider = cache_provider or CacheDataProvider()
        self._initialized = False
        self._db_failures = 0
        self._max_failures = 10  # Fall back to cache after N failures
    
    def initialize(self) -> None:
        """Initialize both providers."""
        logger.info("Initializing hybrid data provider")
        
        try:
            self.db_provider.initialize()
            self.cache_provider.initialize()
            self._initialized = True
            self._db_failures = 0
            logger.info("Hybrid provider ready (database active)")
        except Exception as e:
            logger.warning(f"Database initialization failed, cache fallback active: {e}")
            self.cache_provider.initialize()
            self._initialized = True
    
    def readdir(self, path: str) -> DirectoryListing:
        """
        List files, trying database first, falling back to cache.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            DirectoryListing from database or cache
        """
        if not self._initialized:
            self.initialize()
        
        # Try database if it hasn't failed too many times
        if self._db_failures < self._max_failures:
            try:
                result = self.db_provider.readdir(path)
                
                if not result.errors:
                    # Success, reset failure count
                    self._db_failures = 0
                    logger.debug(f"Hybrid readdir (database): {path}")
                    return result
                else:
                    # Database returned errors
                    self._db_failures += 1
                    logger.warning(f"Database readdir error, trying cache: {result.errors}")
            
            except Exception as e:
                self._db_failures += 1
                logger.warning(f"Database readdir failed, trying cache: {e}")
        
        # Fall back to cache
        logger.debug(f"Hybrid readdir (cache fallback): {path}")
        return self.cache_provider.readdir(path)
    
    def getattr(self, path: str) -> Optional[FileInfo]:
        """
        Get file attributes, trying database first, falling back to cache.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            FileInfo from database or cache
        """
        if not self._initialized:
            self.initialize()
        
        # Try database if it hasn't failed too many times
        if self._db_failures < self._max_failures:
            try:
                result = self.db_provider.getattr(path)
                
                if result is not None:
                    # Success, reset failure count
                    self._db_failures = 0
                    logger.debug(f"Hybrid getattr (database): {path}")
                    return result
                
                # Database returned None, try cache
            
            except Exception as e:
                self._db_failures += 1
                logger.warning(f"Database getattr failed, trying cache: {e}")
        
        # Fall back to cache
        logger.debug(f"Hybrid getattr (cache fallback): {path}")
        return self.cache_provider.getattr(path)
    
    def open(self, path: str) -> Optional[str]:
        """
        Resolve path, trying database first, falling back to cache.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            Actual filesystem path
        """
        if not self._initialized:
            self.initialize()
        
        # Try database if it hasn't failed too many times
        if self._db_failures < self._max_failures:
            try:
                result = self.db_provider.open(path)
                
                if result is not None:
                    # Success, reset failure count
                    self._db_failures = 0
                    logger.debug(f"Hybrid open (database): {path}")
                    return result
                
                # Database returned None, try cache
            
            except Exception as e:
                self._db_failures += 1
                logger.warning(f"Database open failed, trying cache: {e}")
        
        # Fall back to cache
        logger.debug(f"Hybrid open (cache fallback): {path}")
        return self.cache_provider.open(path)
    
    def close(self) -> None:
        """Close both providers."""
        logger.info("Closing hybrid data provider")
        self.db_provider.close()
        self.cache_provider.close()
        self._initialized = False
    
    @property
    def mode(self) -> str:
        """Return provider mode."""
        if self._db_failures >= self._max_failures:
            return "hybrid (cache)"
        return "hybrid (database)"
