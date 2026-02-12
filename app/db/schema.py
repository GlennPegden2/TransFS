"""
Database schema definitions for metadata storage.

Tables:
- files: Core file information (path, size, timestamps)
- metadata: Extended metadata (genre, language, tags, etc.)
- collections: User-defined collections
- collection_members: Files within collections
- transforms: Transform pipeline configurations
- virtual_mappings: Virtual path mapping rules
"""

# SQLite schema with indexes optimized for common queries
SCHEMA_VERSION = 1

CREATE_TABLES = """
-- Core files table
CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL UNIQUE,
    virtual_path TEXT,
    filename TEXT NOT NULL,
    extension TEXT,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    ctime INTEGER NOT NULL,
    atime INTEGER NOT NULL,
    ino INTEGER,
    mode INTEGER,
    is_directory BOOLEAN DEFAULT 0,
    is_archive BOOLEAN DEFAULT 0,
    archive_format TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_source_path ON files(source_path);
CREATE INDEX IF NOT EXISTS idx_files_virtual_path ON files(virtual_path);
CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_files_is_directory ON files(is_directory);

-- Extended metadata table
CREATE TABLE IF NOT EXISTS metadata (
    meta_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    
    -- Content metadata
    genre TEXT,
    subgenre TEXT,
    language TEXT,
    region TEXT,
    year INTEGER,
    publisher TEXT,
    developer TEXT,
    
    -- Quality indicators
    rating REAL,
    play_count INTEGER DEFAULT 0,
    last_played INTEGER,
    
    -- Status flags
    is_prototype BOOLEAN DEFAULT 0,
    is_homebrew BOOLEAN DEFAULT 0,
    is_translation BOOLEAN DEFAULT 0,
    is_hack BOOLEAN DEFAULT 0,
    
    -- Custom tags (JSON array)
    tags TEXT,
    
    -- Raw metadata (JSON)
    raw_metadata TEXT,
    
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metadata_file_id ON metadata(file_id);
CREATE INDEX IF NOT EXISTS idx_metadata_genre ON metadata(genre);
CREATE INDEX IF NOT EXISTS idx_metadata_language ON metadata(language);
CREATE INDEX IF NOT EXISTS idx_metadata_region ON metadata(region);
CREATE INDEX IF NOT EXISTS idx_metadata_year ON metadata(year);
CREATE INDEX IF NOT EXISTS idx_metadata_publisher ON metadata(publisher);

-- Collections table
CREATE TABLE IF NOT EXISTS collections (
    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(name);

-- Collection membership table
CREATE TABLE IF NOT EXISTS collection_members (
    collection_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    added_at INTEGER NOT NULL,
    sort_order INTEGER,
    PRIMARY KEY (collection_id, file_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collection_members_collection_id ON collection_members(collection_id);
CREATE INDEX IF NOT EXISTS idx_collection_members_file_id ON collection_members(file_id);

-- Transform pipelines table
CREATE TABLE IF NOT EXISTS transforms (
    transform_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    pipeline TEXT NOT NULL,
    target_extension TEXT,
    estimated_output_size INTEGER,
    is_active BOOLEAN DEFAULT 1,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transforms_file_id ON transforms(file_id);
CREATE INDEX IF NOT EXISTS idx_transforms_is_active ON transforms(file_id, is_active);

-- Virtual mappings table
CREATE TABLE IF NOT EXISTS virtual_mappings (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pattern TEXT NOT NULL,
    virtual_pattern TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_virtual_mappings_source_pattern ON virtual_mappings(source_pattern);
CREATE INDEX IF NOT EXISTS idx_virtual_mappings_priority ON virtual_mappings(priority DESC);
CREATE INDEX IF NOT EXISTS idx_virtual_mappings_is_active ON virtual_mappings(is_active);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at INTEGER NOT NULL
);
"""

# Optimized SQLite configuration for read-heavy workload
PRAGMA_SETTINGS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA foreign_keys = ON;
"""

def get_schema_version():
    """Get current schema version."""
    return SCHEMA_VERSION
