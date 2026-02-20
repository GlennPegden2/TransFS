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
SCHEMA_VERSION = 3

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
    system TEXT,
    client TEXT,
    map_name TEXT,
    content_type TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_source_path ON files(source_path);
CREATE INDEX IF NOT EXISTS idx_files_virtual_path ON files(virtual_path);
CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_system ON files(system);
CREATE INDEX IF NOT EXISTS idx_files_system_ext ON files(system, extension);
CREATE INDEX IF NOT EXISTS idx_files_client_system_map ON files(client, system, map_name);
CREATE INDEX IF NOT EXISTS idx_files_content_type ON files(content_type);
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

-- Controlled vocab tables
CREATE TABLE IF NOT EXISTS media_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS languages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS app_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS publishers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- File metadata v2 (normalized)
CREATE TABLE IF NOT EXISTS file_metadata (
    file_id INTEGER PRIMARY KEY,
    transfs_path TEXT,
    extension TEXT,
    title TEXT,
    media_type_id INTEGER,
    region_id INTEGER,
    language_id INTEGER,
    genre_id INTEGER,
    app_type_id INTEGER,
    publisher_id INTEGER,
    release_date TEXT,
    release_year INTEGER,
    release_precision TEXT,
    rom_size INTEGER,
    is_revision BOOLEAN DEFAULT 0,
    is_prototype BOOLEAN DEFAULT 0,
    is_homebrew BOOLEAN DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (media_type_id) REFERENCES media_types(id),
    FOREIGN KEY (region_id) REFERENCES regions(id),
    FOREIGN KEY (language_id) REFERENCES languages(id),
    FOREIGN KEY (genre_id) REFERENCES genres(id),
    FOREIGN KEY (app_type_id) REFERENCES app_types(id),
    FOREIGN KEY (publisher_id) REFERENCES publishers(id)
);

CREATE INDEX IF NOT EXISTS idx_file_metadata_media_type ON file_metadata(media_type_id);
CREATE INDEX IF NOT EXISTS idx_file_metadata_region ON file_metadata(region_id);
CREATE INDEX IF NOT EXISTS idx_file_metadata_language ON file_metadata(language_id);
CREATE INDEX IF NOT EXISTS idx_file_metadata_genre ON file_metadata(genre_id);
CREATE INDEX IF NOT EXISTS idx_file_metadata_release_year ON file_metadata(release_year);

-- Flexible tag list for peripherals/flags/etc.
CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL,
    tag_type TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    PRIMARY KEY (file_id, tag_type, tag_value),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_file_tags_type ON file_tags(tag_type);

-- Packs and file membership
CREATE TABLE IF NOT EXISTS packs (
    pack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source TEXT,
    version TEXT,
    ruleset TEXT,
    ruleset_overrides TEXT
);

CREATE TABLE IF NOT EXISTS file_packs (
    file_id INTEGER NOT NULL,
    pack_id INTEGER NOT NULL,
    PRIMARY KEY (file_id, pack_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_id) REFERENCES packs(pack_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_file_packs_pack ON file_packs(pack_id);

-- Optional manual edit audit
CREATE TABLE IF NOT EXISTS metadata_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    edited_at INTEGER NOT NULL,
    edited_by TEXT,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metadata_edits_file_id ON metadata_edits(file_id);

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
# Note: WAL mode disabled for WSL filesystem compatibility
PRAGMA_SETTINGS = """
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA foreign_keys = ON;
"""

def get_schema_version():
    """Get current schema version."""
    return SCHEMA_VERSION
