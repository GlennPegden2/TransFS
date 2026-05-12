"""
DataProvider initialization and setup for FUSE operations.

Initializes the appropriate data provider based on feature flags and configuration.
Integrates with transfs.py without disrupting existing functionality.
"""
import logging
from typing import Dict, Any, Optional

from data_provider import DataProviderFactory
from feature_flags import FeatureFlagManager

logger = logging.getLogger(__name__)


class DataProviderManager:
    """Manages DataProvider lifecycle and initialization."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize manager.
        
        Args:
            config: Configuration dict from app.yaml
        """
        self.config = config
        self.flags = FeatureFlagManager(config)
        self.provider = None
    
    def initialize(self, existing_cache_provider=None) -> bool:
        """
        Initialize the data provider.
        
        Args:
            existing_cache_provider: Existing cache provider for fallback
        
        Returns:
            True if initialization successful
        """
        try:
            logger.info(f"Initializing data provider (mode: {self.flags.get_mode_description()})")
            
            # Create appropriate provider based on config
            self.provider = DataProviderFactory.create(
                self.config,
                existing_cache_provider
            )
            
            # Initialize provider
            self.provider.initialize()
            
            logger.info(f"Data provider initialized successfully: {self.provider.mode}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize data provider: {e}")
            logger.warning("Falling back to cache-only mode")
            
            # Create cache provider as fallback
            from app.data_provider_cache import CacheDataProvider
            self.provider = CacheDataProvider(existing_cache_provider)
            self.provider.initialize()
            
            return False
    
    def get_provider(self):
        """Get the initialized provider."""
        if self.provider is None:
            raise RuntimeError("Provider not initialized - call initialize() first")
        return self.provider
    
    def shutdown(self):
        """Shutdown the provider and cleanup."""
        if self.provider:
            logger.info(f"Shutting down data provider: {self.provider.mode}")
            self.provider.close()
            self.provider = None
    
    def is_cache_mode(self) -> bool:
        """Check if running in cache-only mode."""
        return self.flags.is_cache_mode()
    
    def is_database_mode(self) -> bool:
        """Check if database mode is active."""
        return self.flags.is_database_mode()
    
    def is_hybrid_mode(self) -> bool:
        """Check if running in hybrid mode."""
        return self.flags.is_hybrid_mode()


# Global provider manager instance
_provider_manager: Optional[DataProviderManager] = None


def get_data_provider_manager() -> DataProviderManager:
    """Get the global data provider manager."""
    global _provider_manager
    if _provider_manager is None:
        raise RuntimeError("DataProviderManager not initialized")
    return _provider_manager


def initialize_data_provider(config: Dict[str, Any], existing_cache_provider=None) -> DataProviderManager:
    """
    Initialize the global data provider manager.
    
    Args:
        config: Configuration dict from app.yaml
        existing_cache_provider: Existing cache provider
    
    Returns:
        Initialized DataProviderManager
    """
    global _provider_manager
    
    logger.info("Setting up DataProviderManager")
    _provider_manager = DataProviderManager(config)
    _provider_manager.initialize(existing_cache_provider)
    
    return _provider_manager


def shutdown_data_provider():
    """Shutdown the global data provider manager."""
    global _provider_manager
    if _provider_manager:
        _provider_manager.shutdown()
        _provider_manager = None
