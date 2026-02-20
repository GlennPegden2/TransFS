"""
Data models for database entities.

Simple dataclasses to represent database rows.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import json


@dataclass
class FileEntry:
    """Represents a file in the database."""
    file_id: Optional[int] = None
    source_path: str = ""
    virtual_path: Optional[str] = None
    filename: str = ""
    extension: Optional[str] = None
    size: int = 0
    mtime: int = 0
    ctime: int = 0
    atime: int = 0
    ino: Optional[int] = None
    mode: Optional[int] = None
    is_directory: bool = False
    is_archive: bool = False
    archive_format: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'file_id': self.file_id,
            'source_path': self.source_path,
            'virtual_path': self.virtual_path,
            'filename': self.filename,
            'extension': self.extension,
            'size': self.size,
            'mtime': self.mtime,
            'ctime': self.ctime,
            'atime': self.atime,
            'ino': self.ino,
            'mode': self.mode,
            'is_directory': self.is_directory,
            'is_archive': self.is_archive,
            'archive_format': self.archive_format,
        }
    
    @classmethod
    def from_row(cls, row) -> 'FileEntry':
        """Create from database row."""
        return cls(
            file_id=row['file_id'],
            source_path=row['source_path'],
            virtual_path=row['virtual_path'],
            filename=row['filename'],
            extension=row['extension'],
            size=row['size'],
            mtime=row['mtime'],
            ctime=row['ctime'],
            atime=row['atime'],
            ino=row['ino'],
            mode=row['mode'],
            is_directory=bool(row['is_directory']),
            is_archive=bool(row['is_archive']),
            archive_format=row['archive_format'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )


@dataclass
class FileMetadata:
    """Extended metadata for a file."""
    meta_id: Optional[int] = None
    file_id: int = 0
    genre: Optional[str] = None
    subgenre: Optional[str] = None
    language: Optional[str] = None
    region: Optional[str] = None
    year: Optional[int] = None
    publisher: Optional[str] = None
    developer: Optional[str] = None
    rating: Optional[float] = None
    play_count: int = 0
    last_played: Optional[int] = None
    is_prototype: bool = False
    is_homebrew: bool = False
    is_translation: bool = False
    is_hack: bool = False
    tags: List[str] = field(default_factory=list)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def tags_json(self) -> str:
        """Get tags as JSON string."""
        return json.dumps(self.tags)
    
    @tags_json.setter
    def tags_json(self, value: str):
        """Set tags from JSON string."""
        self.tags = json.loads(value) if value else []
    
    @property
    def raw_metadata_json(self) -> str:
        """Get raw metadata as JSON string."""
        return json.dumps(self.raw_metadata)
    
    @raw_metadata_json.setter
    def raw_metadata_json(self, value: str):
        """Set raw metadata from JSON string."""
        self.raw_metadata = json.loads(value) if value else {}
    
    @classmethod
    def from_row(cls, row) -> 'FileMetadata':
        """Create from database row."""
        meta = cls(
            meta_id=row['meta_id'],
            file_id=row['file_id'],
            genre=row['genre'],
            subgenre=row['subgenre'],
            language=row['language'],
            region=row['region'],
            year=row['year'],
            publisher=row['publisher'],
            developer=row['developer'],
            rating=row['rating'],
            play_count=row['play_count'] or 0,
            last_played=row['last_played'],
            is_prototype=bool(row['is_prototype']),
            is_homebrew=bool(row['is_homebrew']),
            is_translation=bool(row['is_translation']),
            is_hack=bool(row['is_hack']),
        )
        
        # Parse JSON fields
        if row['tags']:
            meta.tags_json = row['tags']
        if row['raw_metadata']:
            meta.raw_metadata_json = row['raw_metadata']
        
        return meta


@dataclass
class FileMetadataRecord:
    """Normalized metadata record (file_metadata)."""
    file_id: int
    transfs_path: Optional[str] = None
    extension: Optional[str] = None
    media_type_id: Optional[int] = None
    region_id: Optional[int] = None
    language_id: Optional[int] = None
    genre_id: Optional[int] = None
    app_type_id: Optional[int] = None
    publisher_id: Optional[int] = None
    release_date: Optional[str] = None
    release_year: Optional[int] = None
    release_precision: Optional[str] = None
    rom_size: Optional[int] = None
    is_revision: bool = False
    is_prototype: bool = False
    is_homebrew: bool = False

    @classmethod
    def from_row(cls, row) -> 'FileMetadataRecord':
        return cls(
            file_id=row['file_id'],
            transfs_path=row['transfs_path'],
            extension=row['extension'],
            media_type_id=row['media_type_id'],
            region_id=row['region_id'],
            language_id=row['language_id'],
            genre_id=row['genre_id'],
            app_type_id=row['app_type_id'],
            publisher_id=row['publisher_id'],
            release_date=row['release_date'],
            release_year=row['release_year'],
            release_precision=row['release_precision'],
            rom_size=row['rom_size'],
            is_revision=bool(row['is_revision']),
            is_prototype=bool(row['is_prototype']),
            is_homebrew=bool(row['is_homebrew']),
        )


@dataclass
class Collection:
    """User-defined collection of files."""
    collection_id: Optional[int] = None
    name: str = ""
    description: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0
    
    @classmethod
    def from_row(cls, row) -> 'Collection':
        """Create from database row."""
        return cls(
            collection_id=row['collection_id'],
            name=row['name'],
            description=row['description'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )


@dataclass
class Transform:
    """Transform pipeline for a file."""
    transform_id: Optional[int] = None
    file_id: int = 0
    pipeline: str = ""  # JSON string
    target_extension: Optional[str] = None
    estimated_output_size: Optional[int] = None
    is_active: bool = True
    created_at: int = 0
    
    @property
    def pipeline_dict(self) -> List[Dict[str, Any]]:
        """Get pipeline as dict."""
        return json.loads(self.pipeline) if self.pipeline else []
    
    @pipeline_dict.setter
    def pipeline_dict(self, value: List[Dict[str, Any]]):
        """Set pipeline from dict."""
        self.pipeline = json.dumps(value)
    
    @classmethod
    def from_row(cls, row) -> 'Transform':
        """Create from database row."""
        return cls(
            transform_id=row['transform_id'],
            file_id=row['file_id'],
            pipeline=row['pipeline'],
            target_extension=row['target_extension'],
            estimated_output_size=row['estimated_output_size'],
            is_active=bool(row['is_active']),
            created_at=row['created_at'],
        )


@dataclass
class VirtualMapping:
    """Virtual path mapping rule."""
    mapping_id: Optional[int] = None
    source_pattern: str = ""
    virtual_pattern: str = ""
    priority: int = 0
    is_active: bool = True
    created_at: int = 0
    
    @classmethod
    def from_row(cls, row) -> 'VirtualMapping':
        """Create from database row."""
        return cls(
            mapping_id=row['mapping_id'],
            source_pattern=row['source_pattern'],
            virtual_pattern=row['virtual_pattern'],
            priority=row['priority'],
            is_active=bool(row['is_active']),
            created_at=row['created_at'],
        )
