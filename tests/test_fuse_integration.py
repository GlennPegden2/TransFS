"""
Integration tests for DataProvider with FUSE operations.

Tests the adapter layer and initialization without requiring full FUSE mount.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch

from app.data_provider import FileInfo, DirectoryListing
from app.data_provider_init import DataProviderManager, initialize_data_provider
from app.fuse_adapter import FUSEOperationAdapter, AdapterRegistry


class TestDataProviderManager:
    """Test DataProviderManager initialization and lifecycle."""
    
    def test_manager_initialization_cache_mode(self):
        """Test manager initializes in cache-only mode."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        manager = DataProviderManager(config)
        assert manager.flags.is_cache_mode() is True
        assert manager.is_cache_mode() is True
        assert manager.is_database_mode() is False
    
    def test_manager_initialization_database_mode(self):
        """Test manager initializes in database mode."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'enabled'
            }
        }
        
        manager = DataProviderManager(config)
        assert manager.flags.is_database_mode() is True
        assert manager.is_database_mode() is True
        assert manager.is_cache_mode() is False
    
    def test_manager_initialization_hybrid_mode(self):
        """Test manager initializes in hybrid mode."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'hybrid'
            }
        }
        
        manager = DataProviderManager(config)
        assert manager.flags.is_hybrid_mode() is True
        assert manager.is_hybrid_mode() is True
    
    def test_manager_provides_correct_provider(self):
        """Test manager creates correct provider type."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        manager = DataProviderManager(config)
        manager.initialize()
        
        provider = manager.get_provider()
        assert provider.mode == "cache"
    
    def test_manager_shutdown(self):
        """Test manager shutdown."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        manager = DataProviderManager(config)
        manager.initialize()
        manager.shutdown()
        
        assert manager.provider is None


class TestFUSEOperationAdapter:
    """Test FUSE operation adapter."""
    
    def test_adapter_readdir_entries(self):
        """Test converting readdir to FUSE format."""
        # Mock provider
        mock_provider = Mock()
        
        # Create test entries
        entries = [
            FileInfo(
                path="/test/file1.bin",
                filename="file1.bin",
                size=1024,
                mtime=1234567890,
                ctime=1234567890,
                atime=1234567890,
                mode=33188,
                ino=12346,
                is_directory=False
            ),
            FileInfo(
                path="/test/file2.bin",
                filename="file2.bin",
                size=2048,
                mtime=1234567890,
                ctime=1234567890,
                atime=1234567890,
                mode=33188,
                ino=12347,
                is_directory=False
            )
        ]
        
        listing = DirectoryListing(
            path="/test",
            entries=entries,
            total_count=2
        )
        
        mock_provider.readdir.return_value = listing
        mock_provider.mode = "test"
        
        # Test adapter
        adapter = FUSEOperationAdapter(mock_provider)
        fuse_entries = adapter.readdir_entries("/test")
        
        assert len(fuse_entries) == 2
        assert fuse_entries[0][0] == "file1.bin"
        assert fuse_entries[0][1]['st_size'] == 1024
        assert fuse_entries[1][0] == "file2.bin"
        assert fuse_entries[1][1]['st_size'] == 2048
    
    def test_adapter_getattr_stat(self):
        """Test converting getattr to FUSE stat format."""
        # Mock provider
        mock_provider = Mock()
        
        file_info = FileInfo(
            path="/test/file.bin",
            filename="file.bin",
            size=1024,
            mtime=1234567890,
            ctime=1234567890,
            atime=1234567890,
            mode=33188,
            ino=12345,
            is_directory=False
        )
        
        mock_provider.getattr.return_value = file_info
        mock_provider.mode = "test"
        
        # Test adapter
        adapter = FUSEOperationAdapter(mock_provider)
        stat = adapter.getattr_stat("/test/file.bin")
        
        assert stat is not None
        assert stat['st_size'] == 1024
        assert stat['st_mtime'] == 1234567890
        assert stat['st_mode'] == 33188
        assert stat['st_nlink'] == 1
    
    def test_adapter_getattr_stat_directory(self):
        """Test getattr for directory."""
        # Mock provider
        mock_provider = Mock()
        
        dir_info = FileInfo(
            path="/test",
            filename="test",
            size=4096,
            mtime=1234567890,
            ctime=1234567890,
            atime=1234567890,
            mode=16877,  # Directory
            ino=12345,
            is_directory=True
        )
        
        mock_provider.getattr.return_value = dir_info
        mock_provider.mode = "test"
        
        # Test adapter
        adapter = FUSEOperationAdapter(mock_provider)
        stat = adapter.getattr_stat("/test")
        
        assert stat is not None
        assert stat['st_nlink'] == 2  # Directories have link count 2
    
    def test_adapter_getattr_not_found(self):
        """Test getattr when file not found."""
        # Mock provider
        mock_provider = Mock()
        mock_provider.getattr.return_value = None
        mock_provider.mode = "test"
        
        # Test adapter
        adapter = FUSEOperationAdapter(mock_provider)
        stat = adapter.getattr_stat("/nonexistent")
        
        assert stat is None
    
    def test_adapter_resolve_path(self):
        """Test path resolution."""
        # Mock provider
        mock_provider = Mock()
        mock_provider.open.return_value = "/mnt/filestorefs/test/file.bin"
        mock_provider.mode = "test"
        
        # Test adapter
        adapter = FUSEOperationAdapter(mock_provider)
        actual_path = adapter.resolve_path("/test/file.bin")
        
        assert actual_path == "/mnt/filestorefs/test/file.bin"
    
    def test_adapter_provider_mode(self):
        """Test getting provider mode."""
        # Mock provider
        mock_provider = Mock()
        mock_provider.mode = "database"
        
        adapter = FUSEOperationAdapter(mock_provider)
        
        assert adapter.get_provider_mode() == "database"
        assert adapter.is_database_mode() is True
    
    def test_adapter_error_handling_readdir(self):
        """Test error handling in readdir."""
        # Mock provider that raises exception
        mock_provider = Mock()
        mock_provider.readdir.side_effect = Exception("Database error")
        mock_provider.mode = "test"
        
        adapter = FUSEOperationAdapter(mock_provider)
        result = adapter.readdir_entries("/test")
        
        assert result == []  # Should return empty list on error
    
    def test_adapter_error_handling_getattr(self):
        """Test error handling in getattr."""
        # Mock provider that raises exception
        mock_provider = Mock()
        mock_provider.getattr.side_effect = Exception("Database error")
        mock_provider.mode = "test"
        
        adapter = FUSEOperationAdapter(mock_provider)
        result = adapter.getattr_stat("/test")
        
        assert result is None  # Should return None on error


class TestAdapterRegistry:
    """Test adapter registry."""
    
    def test_registry_register_adapter(self):
        """Test registering an adapter."""
        mock_provider = Mock()
        mock_provider.mode = "test"
        adapter = FUSEOperationAdapter(mock_provider)
        
        AdapterRegistry.register("test", adapter)
        
        assert AdapterRegistry.get("test") is adapter
    
    def test_registry_get_default(self):
        """Test getting default adapter."""
        mock_provider = Mock()
        mock_provider.mode = "test"
        adapter = FUSEOperationAdapter(mock_provider)
        
        AdapterRegistry.register("default", adapter)
        
        assert AdapterRegistry.get_default() is adapter
    
    def test_registry_list_adapters(self):
        """Test listing registered adapters."""
        mock_provider = Mock()
        mock_provider.mode = "test"
        adapter1 = FUSEOperationAdapter(mock_provider)
        adapter2 = FUSEOperationAdapter(mock_provider)
        
        AdapterRegistry._adapters.clear()
        AdapterRegistry.register("adapter1", adapter1)
        AdapterRegistry.register("adapter2", adapter2)
        
        adapters = AdapterRegistry.list_adapters()
        
        assert "adapter1" in adapters
        assert "adapter2" in adapters


class TestDataProviderInitialization:
    """Test DataProvider initialization function."""
    
    def test_initialize_data_provider(self):
        """Test global initialization."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        from app.data_provider_init import _provider_manager, get_data_provider_manager
        import app.data_provider_init as init_module
        
        # Reset global state
        init_module._provider_manager = None
        
        # Initialize
        manager = initialize_data_provider(config)
        
        assert manager is not None
        assert manager.is_cache_mode() is True
        
        # Cleanup
        from app.data_provider_init import shutdown_data_provider
        shutdown_data_provider()
