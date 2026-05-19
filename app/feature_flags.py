"""
Feature flag management for database system.

Controls enabling/disabling of database features without code changes.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class FeatureFlagManager:
    """Manages feature flags for the database system."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize feature flag manager.
        
        Args:
            config: Configuration dict from app.yaml
        """
        self.config = config
        self.db_config = config.get('database', {})
        
        # Feature flags
        self.database_enabled = self.db_config.get('enabled', False)
        self.database_mode = self.db_config.get('mode', 'disabled')
        self.database_path = self.db_config.get('path', '/data/retronas/.transfs_metadata.db')
        self.auto_sync = self.db_config.get('auto_sync', False)
        self.sync_on_startup = self.db_config.get('sync_on_startup', False)
        
        # Log configuration
        self._log_config()
    
    def _log_config(self):
        """Log current configuration."""
        logger.info("=" * 60)
        logger.info("Database Feature Flags Configuration")
        logger.info("=" * 60)
        logger.info(f"  Database Enabled:  {self.database_enabled}")
        logger.info(f"  Database Mode:     {self.database_mode}")
        logger.info(f"  Database Path:     {self.database_path}")
        logger.info(f"  Auto Sync:         {self.auto_sync}")
        logger.info(f"  Sync on Startup:   {self.sync_on_startup}")
        logger.info("=" * 60)
        
        if self.database_enabled:
            if self.database_mode == 'disabled':
                logger.warning("Database enabled but mode is disabled - using cache only")
            elif self.database_mode == 'enabled':
                logger.info("Using DATABASE-ONLY mode (no cache fallback)")
            elif self.database_mode == 'hybrid':
                logger.info("Using HYBRID mode (database with cache fallback)")
            else:
                logger.warning(f"Unknown database mode: {self.database_mode}")
        else:
            logger.info("Database disabled - using CACHE-ONLY mode")
    
    def is_database_mode(self) -> bool:
        """Check if database mode is active."""
        return self.database_enabled and self.database_mode in ['enabled', 'hybrid']
    
    def is_cache_mode(self) -> bool:
        """Check if cache mode is active (either cache-only or fallback)."""
        return not self.database_enabled or self.database_mode == 'disabled'
    
    def is_hybrid_mode(self) -> bool:
        """Check if hybrid mode (database with fallback) is active."""
        return self.database_enabled and self.database_mode == 'hybrid'
    
    def should_sync_on_startup(self) -> bool:
        """Check if filesystem should be synced on startup."""
        return self.database_enabled and self.sync_on_startup
    
    def should_auto_sync(self) -> bool:
        """Check if automatic sync is enabled."""
        return self.database_enabled and self.auto_sync
    
    def get_database_path(self) -> str:
        """Get the database file path."""
        return self.database_path
    
    def get_mode_description(self) -> str:
        """Get human-readable description of current mode."""
        if not self.database_enabled:
            return "Cache-Only"
        elif self.database_mode == 'disabled':
            return "Cache-Only (DB disabled)"
        elif self.database_mode == 'enabled':
            return "Database-Only"
        elif self.database_mode == 'hybrid':
            return "Hybrid (Database + Cache Fallback)"
        else:
            return f"Unknown ({self.database_mode})"


class FeatureFlagContext:
    """Context manager for feature flag checking."""
    
    def __init__(self, flags: FeatureFlagManager):
        """
        Initialize context.
        
        Args:
            flags: FeatureFlagManager instance
        """
        self.flags = flags
    
    def __enter__(self):
        """Enter context."""
        return self.flags
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context."""
        pass
