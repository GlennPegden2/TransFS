"""
FUSE operation adapter for DataProvider integration.

Provides adapter methods for seamless integration with transfs.py readdir/getattr operations.
Preserves backward compatibility while enabling feature switching.
"""
import logging
from typing import Optional, List, Dict, Any

from data_provider import FileInfo, DirectoryListing

logger = logging.getLogger(__name__)


class FUSEOperationAdapter:
    """Adapter for FUSE operations using DataProvider."""
    
    def __init__(self, data_provider):
        """
        Initialize adapter.
        
        Args:
            data_provider: DataProvider instance
        """
        self.data_provider = data_provider
    
    def readdir_entries(self, path: str) -> List[tuple]:
        """
        Convert DataProvider readdir to FUSE format.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            List of (name, stat) tuples compatible with pyfuse3
        """
        try:
            # Get directory listing from provider
            listing = self.data_provider.readdir(path)
            
            if listing.errors:
                logger.warning(f"Errors listing {path}: {listing.errors}")
            
            # Convert FileInfo objects to FUSE stat tuples
            entries = []
            for entry in listing.entries:
                # Create stat-like dict for FUSE
                stat_dict = {
                    'st_size': entry.size,
                    'st_mtime': entry.mtime,
                    'st_ctime': entry.ctime,
                    'st_atime': entry.atime,
                    'st_mode': entry.mode,
                    'st_ino': entry.ino,
                }
                
                entries.append((entry.filename, stat_dict))
            
            logger.debug(f"readdir_entries({path}): {len(entries)} entries")
            return entries
        
        except Exception as e:
            logger.error(f"Error in readdir_entries({path}): {e}")
            return []
    
    def getattr_stat(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Convert DataProvider getattr to FUSE stat format.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            Dict with stat attributes or None if not found
        """
        try:
            # Get file info from provider
            file_info = self.data_provider.getattr(path)
            
            if file_info is None:
                logger.debug(f"getattr_stat({path}): not found")
                return None
            
            # Convert to FUSE stat dict
            stat_dict = {
                'st_size': file_info.size,
                'st_mtime': file_info.mtime,
                'st_ctime': file_info.ctime,
                'st_atime': file_info.atime,
                'st_mode': file_info.mode,
                'st_ino': file_info.ino,
                'st_nlink': 1 if not file_info.is_directory else 2,
            }
            
            logger.debug(f"getattr_stat({path}): {file_info.filename}")
            return stat_dict
        
        except Exception as e:
            logger.error(f"Error in getattr_stat({path}): {e}")
            return None
    
    def resolve_path(self, path: str) -> Optional[str]:
        """
        Resolve virtual path to actual filesystem path.
        
        Args:
            path: Virtual filesystem path
        
        Returns:
            Actual filesystem path or None
        """
        try:
            # Use provider's open method to resolve path
            actual_path = self.data_provider.open(path)
            
            if actual_path:
                logger.debug(f"resolve_path({path}): {actual_path}")
            else:
                logger.debug(f"resolve_path({path}): not found")
            
            return actual_path
        
        except Exception as e:
            logger.error(f"Error in resolve_path({path}): {e}")
            return None
    
    def get_provider_mode(self) -> str:
        """Get current provider mode."""
        return self.data_provider.mode
    
    def is_database_mode(self) -> bool:
        """Check if using database provider."""
        return 'database' in self.data_provider.mode.lower()


class AdapterRegistry:
    """Registry for FUSE operation adapters."""
    
    _adapters: Dict[str, FUSEOperationAdapter] = {}
    
    @classmethod
    def register(cls, name: str, adapter: FUSEOperationAdapter):
        """Register an adapter."""
        cls._adapters[name] = adapter
        logger.info(f"Registered FUSE adapter: {name} (mode: {adapter.get_provider_mode()})")
    
    @classmethod
    def get(cls, name: str) -> Optional[FUSEOperationAdapter]:
        """Get a registered adapter."""
        return cls._adapters.get(name)
    
    @classmethod
    def get_default(cls) -> Optional[FUSEOperationAdapter]:
        """Get default adapter."""
        return cls._adapters.get('default')
    
    @classmethod
    def list_adapters(cls) -> List[str]:
        """List all registered adapters."""
        return list(cls._adapters.keys())
