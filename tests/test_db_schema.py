"""
Unit tests for database schema and connection management.
"""
import pytest
import sqlite3
from pathlib import Path

from app.db import connection, models


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db_path_str = str(db_path)
    
    # Initialize database
    connection.init_database(db_path_str)
    
    # Reset thread-local storage for clean state
    if hasattr(connection._thread_local, 'connection'):
        delattr(connection._thread_local, 'connection')
    
    yield db_path_str
    
    # Cleanup
    if hasattr(connection._thread_local, 'connection'):
        try:
            connection._thread_local.connection.close()
        except:
            pass
        delattr(connection._thread_local, 'connection')


class TestDatabaseSchema:
    """Test database schema creation and structure."""
    
    def test_schema_tables_creation(self, temp_db):
        """Test that all required tables are created."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        
        expected_tables = [
            'collection_members',
            'collections',
            'files',
            'metadata',
            'schema_version',
            'transforms',
            'virtual_mappings'
        ]
        
        assert all(table in tables for table in expected_tables), f"Missing tables. Found: {tables}"
        conn.close()
    
    def test_schema_indexes_created(self, temp_db):
        """Test that indexes are created."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        indexes = [row[0] for row in cursor.fetchall()]
        
        # Check for key indexes (exclude sqlite_autoindex_*)
        index_names = [idx for idx in indexes if not idx.startswith('sqlite_')]
        
        assert any('idx_files_virtual_path' in idx for idx in index_names), f"Missing idx_files_virtual_path. Found: {index_names}"
        assert any('idx_files_source_path' in idx for idx in index_names), f"Missing idx_files_source_path. Found: {index_names}"
        
        conn.close()
    
    def test_foreign_keys_enabled(self, temp_db):
        """Test that foreign keys are enabled."""
        conn = connection.get_connection()
        
        cursor = conn.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        
        assert result[0] == 1, "Foreign keys should be enabled"
    
    def test_schema_version_recorded(self, temp_db):
        """Test that schema version is recorded."""
        conn = connection.get_connection()
        
        cursor = conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()
        
        assert version is not None, "Schema version should be recorded"
        assert version[0] == 1, f"Schema version should be 1, got {version[0]}"


class TestConnectionManagement:
    """Test database connection management."""
    
    def test_get_connection_reuses_connection(self, temp_db):
        """Test that get_connection reuses thread-local connection."""
        conn1 = connection.get_connection()
        conn2 = connection.get_connection()
        
        assert conn1 is conn2, "Should reuse thread-local connection"
    
    def test_transaction_commits_changes(self, temp_db):
        """Test that transaction context commits changes."""
        with connection.transaction() as conn:
            conn.execute("""
                INSERT INTO files (
                    source_path, virtual_path, filename, size,
                    mtime, ctime, atime, ino, mode,
                    is_directory, is_archive,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                '/test/file.bin', '/test/file.bin', 'file.bin', 1024,
                1234567890, 1234567890, 1234567890, 12345, 33188,
                False, False, 1234567890, 1234567890
            ))
        
        # Verify in new connection
        conn2 = sqlite3.connect(temp_db)
        cursor = conn2.execute("SELECT filename FROM files WHERE source_path = ?", ('/test/file.bin',))
        result = cursor.fetchone()
        
        assert result is not None, "Should find inserted file"
        assert result[0] == 'file.bin'
        conn2.close()
    
    def test_transaction_rolls_back_on_error(self, temp_db):
        """Test that transaction rolls back on exception."""
        try:
            with connection.transaction() as conn:
                conn.execute("""
                    INSERT INTO files (
                        source_path, virtual_path, filename, size,
                        mtime, ctime, atime, ino, mode,
                        is_directory, is_archive,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    '/test/file2.bin', '/test/file2.bin', 'file2.bin', 2048,
                    1234567890, 1234567890, 1234567890, 12346, 33188,
                    False, False, 1234567890, 1234567890
                ))
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Verify not committed
        conn2 = sqlite3.connect(temp_db)
        cursor = conn2.execute("SELECT COUNT(*) FROM files WHERE source_path = ?", ('/test/file2.bin',))
        count = cursor.fetchone()[0]
        
        assert count == 0, "Transaction should have been rolled back"
        conn2.close()


class TestDataModels:
    """Test data model classes."""
    
    def test_file_entry_from_row(self):
        """Test FileEntry.from_row() conversion."""
        row = {
            'file_id': 1,
            'source_path': '/test/file.bin',
            'virtual_path': '/test/file.bin',
            'filename': 'file.bin',
            'extension': 'bin',
            'size': 1024,
            'mtime': 1234567890,
            'ctime': 1234567890,
            'atime': 1234567890,
            'ino': 12345,
            'mode': 33188,
            'is_directory': 0,
            'is_archive': 0,
            'archive_format': None,
            'created_at': 1234567890,
            'updated_at': 1234567890
        }
        
        entry = models.FileEntry.from_row(row)
        
        assert entry.file_id == 1
        assert entry.filename == 'file.bin'
        assert entry.size == 1024
        assert entry.is_directory is False
        assert entry.is_archive is False
    
    def test_file_metadata_from_row_with_json(self):
        """Test FileMetadata.from_row() with JSON fields."""
        row = {
            'meta_id': 1,
            'file_id': 1,
            'genre': 'Action',
            'subgenre': None,
            'language': 'En',
            'region': 'USA',
            'year': 1982,
            'publisher': None,
            'developer': None,
            'rating': None,
            'play_count': 0,
            'last_played': None,
            'is_prototype': 1,
            'is_homebrew': 0,
            'is_translation': 0,
            'is_hack': 0,
            'tags': '["prototype", "early"]',
            'raw_metadata': '{"source": "filename"}'
        }
        
        metadata = models.FileMetadata.from_row(row)
        
        assert metadata.meta_id == 1
        assert metadata.genre == 'Action'
        assert metadata.is_prototype is True
        assert metadata.is_homebrew is False
        assert metadata.tags == ["prototype", "early"]
        assert metadata.raw_metadata == {"source": "filename"}
    
    def test_collection_from_row(self):
        """Test Collection.from_row() conversion."""
        row = {
            'collection_id': 1,
            'name': 'Prototype Games',
            'description': 'All prototype ROMs',
            'created_at': 1234567890,
            'updated_at': 1234567890
        }
        
        collection = models.Collection.from_row(row)
        
        assert collection.collection_id == 1
        assert collection.name == 'Prototype Games'
        assert collection.description == 'All prototype ROMs'
