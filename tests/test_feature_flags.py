"""
Tests for data provider abstraction and feature switching.
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

# Import from correct paths
from app.data_provider import DataProviderFactory, FileInfo, DirectoryListing
from app.data_provider_cache import CacheDataProvider
from app.data_provider_db import DatabaseDataProvider
from app.data_provider_hybrid import HybridDataProvider
from app.feature_flags import FeatureFlagManager


class TestDataProviderAbstraction:
    """Test data provider abstraction layer."""
    
    def test_file_info_creation(self):
        """Test creating FileInfo objects."""
        info = FileInfo(
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
        
        assert info.path == "/test/file.bin"
        assert info.filename == "file.bin"
        assert info.size == 1024
        assert info.is_directory is False
    
    def test_directory_listing_creation(self):
        """Test creating DirectoryListing objects."""
        entries = [
            FileInfo(
                path="/test/file1.bin",
                filename="file1.bin",
                size=512,
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
                size=1024,
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
        
        assert listing.path == "/test"
        assert len(listing.entries) == 2
        assert listing.total_count == 2
        assert listing.errors == []
    
    def test_directory_listing_with_errors(self):
        """Test DirectoryListing with error tracking."""
        listing = DirectoryListing(
            path="/test",
            entries=[],
            total_count=0,
            errors=["Permission denied", "Database error"]
        )
        
        assert len(listing.errors) == 2
        assert "Permission denied" in listing.errors


class TestFeatureFlagManager:
    """Test feature flag management."""
    
    def test_feature_flags_cache_only(self):
        """Test feature flags with cache-only mode."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        flags = FeatureFlagManager(config)
        
        assert flags.database_enabled is False
        assert flags.is_cache_mode() is True
        assert flags.is_database_mode() is False
        assert flags.is_hybrid_mode() is False
    
    def test_feature_flags_database_only(self):
        """Test feature flags with database-only mode."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'enabled'
            }
        }
        
        flags = FeatureFlagManager(config)
        
        assert flags.database_enabled is True
        assert flags.database_mode == 'enabled'
        assert flags.is_cache_mode() is False
        assert flags.is_database_mode() is True
        assert flags.is_hybrid_mode() is False
    
    def test_feature_flags_hybrid(self):
        """Test feature flags with hybrid mode."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'hybrid'
            }
        }
        
        flags = FeatureFlagManager(config)
        
        assert flags.database_enabled is True
        assert flags.database_mode == 'hybrid'
        assert flags.is_cache_mode() is False
        assert flags.is_database_mode() is True
        assert flags.is_hybrid_mode() is True
    
    def test_sync_flags(self):
        """Test sync-related feature flags."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'enabled',
                'sync_on_startup': True,
                'auto_sync': False
            }
        }
        
        flags = FeatureFlagManager(config)
        
        assert flags.should_sync_on_startup() is True
        assert flags.should_auto_sync() is False
    
    def test_mode_descriptions(self):
        """Test mode description generation."""
        test_cases = [
            ({'database': {'enabled': False}}, "Cache-Only"),
            ({'database': {'enabled': True, 'mode': 'disabled'}}, "Cache-Only (DB disabled)"),
            ({'database': {'enabled': True, 'mode': 'enabled'}}, "Database-Only"),
            ({'database': {'enabled': True, 'mode': 'hybrid'}}, "Hybrid (Database + Cache Fallback)"),
        ]
        
        for config, expected_desc in test_cases:
            flags = FeatureFlagManager(config)
            assert expected_desc in flags.get_mode_description()


class TestDataProviderFactory:
    """Test data provider factory."""
    
    def test_factory_creates_cache_provider_when_disabled(self):
        """Test factory creates cache provider when disabled."""
        config = {
            'database': {
                'enabled': False,
                'mode': 'disabled'
            }
        }
        
        provider = DataProviderFactory.create(config)
        assert provider.mode == "cache"
    
    def test_factory_creates_database_provider_when_enabled(self):
        """Test factory creates database provider when enabled."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'enabled',
                'path': '/tmp/test.db'
            }
        }
        
        with patch('app.db.connection.init_database'):
            provider = DataProviderFactory.create(config)
            assert provider.mode == "database"
    
    def test_factory_creates_hybrid_provider_when_hybrid(self):
        """Test factory creates hybrid provider when hybrid mode."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'hybrid',
                'path': '/tmp/test.db'
            }
        }
        
        with patch('app.db.connection.init_database'):
            provider = DataProviderFactory.create(config)
            assert "hybrid" in provider.mode.lower()
    
    def test_factory_handles_default_path(self):
        """Test factory handles default database path."""
        config = {
            'database': {
                'enabled': True,
                'mode': 'enabled'
            }
        }
        
        with patch('app.db.connection.init_database'):
            provider = DataProviderFactory.create(config)
            assert provider.db_path == '/mnt/filestorefs/.transfs_metadata.db'


class TestCacheDataProvider:
    """Test cache-based data provider."""
    
    def test_cache_provider_mode(self):
        """Test cache provider reports correct mode."""
        provider = CacheDataProvider()
        assert provider.mode == "cache"
    
    def test_cache_provider_initialization(self):
        """Test cache provider initialization."""
        provider = CacheDataProvider()
        provider.initialize()
        assert provider._initialized is True
    
    def test_cache_provider_graceful_degradation(self):
        """Test cache provider returns empty results gracefully."""
        provider = CacheDataProvider()
        provider.initialize()
        
        result = provider.readdir("/test")
        assert isinstance(result, DirectoryListing)
        assert result.path == "/test"
        assert len(result.entries) == 0
        assert result.total_count == 0
        # Cache provider not yet fully integrated, so it has placeholder errors
        # This is expected during integration


class TestDatabaseDataProvider:
    """Test database-based data provider."""
    
    def test_database_provider_mode(self):
        """Test database provider reports correct mode."""
        provider = DatabaseDataProvider("/tmp/test.db")
        assert provider.mode == "database"
    
    @pytest.mark.skip(reason="Requires database initialization")
    def test_database_provider_initialization(self):
        """Test database provider initialization."""
        provider = DatabaseDataProvider("/tmp/test.db")
        provider.initialize()
        assert provider._initialized is True


class TestHybridDataProvider:
    """Test hybrid data provider with fallback."""
    
    def test_hybrid_provider_mode(self):
        """Test hybrid provider reports correct mode."""
        provider = HybridDataProvider("/tmp/test.db")
        assert "hybrid" in provider.mode.lower()
    
    def test_hybrid_provider_fallback_tracking(self):
        """Test hybrid provider tracks fallback failures."""
        provider = HybridDataProvider("/tmp/test.db")
        
        assert provider._db_failures == 0
        assert provider._max_failures == 10
