#!/usr/bin/env python3
"""
Populate the TransFS metadata database with filesystem data.
This is a temporary script for Phase 5 testing.
"""
import os
import sys
import sqlite3
from pathlib import Path
import mimetypes
from datetime import datetime

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from metadata.parser import parse_filename


def populate_database(db_path: str, filestore_path: str, base_mount: str = "/mnt/transfs"):
    """Populate database with metadata from filestore."""
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear existing data
    print("Clearing existing data...")
    cursor.execute("DELETE FROM files")
    conn.commit()
    
    # Scan Native directory
    native_path = os.path.join(filestore_path, "Native")
    if not os.path.exists(native_path):
        print(f"Native path not found: {native_path}")
        return
    
    print(f"Scanning: {native_path}")
    file_count = 0
    
    # Walk through directories
    for root, dirs, files in os.walk(native_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            
            # Get relative path from filestore root
            rel_path = os.path.relpath(file_path, filestore_path)
            
            # Convert to virtual mount path
            virtual_path = os.path.join(base_mount, rel_path)
            
            # Get file stats
            try:
                stats = os.stat(file_path)
                
                # Parse metadata
                parsed = parse_filename(filename)
                metadata = {
                    'platform': parsed.platform,
                    'title': parsed.title,
                    'publisher': parsed.publisher,
                    'year': parsed.year,
                    'region': parsed.region,
                    'genre': parsed.genre
                }
                
                # Determine MIME type
                mime_type, _ = mimetypes.guess_type(filename)
                if not mime_type:
                    mime_type = 'application/octet-stream'
                
                # Insert into database
                cursor.execute("""
                    INSERT INTO files (
                        virtual_path, filename, directory, real_path,
                        size, modified_time, is_directory, mime_type,
                        platform, title, publisher, year, region, genre
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    virtual_path,
                    filename,
                    os.path.dirname(virtual_path),
                    file_path,
                    stats.st_size,
                    datetime.fromtimestamp(stats.st_mtime).isoformat(),
                    False,
                    mime_type,
                    metadata.get('platform'),
                    metadata.get('title'),
                    metadata.get('publisher'),
                    metadata.get('year'),
                    metadata.get('region'),
                    metadata.get('genre')
                ))
                
                file_count += 1
                if file_count % 100 == 0:
                    print(f"  Processed {file_count} files...")
                    conn.commit()
                    
            except Exception as e:
                print(f"  Error processing {file_path}: {e}")
                continue
    
    # Add directories
    print("Adding directories...")
    dir_count = 0
    for root, dirs, files in os.walk(native_path):
        # Get relative path from filestore root
        rel_path = os.path.relpath(root, filestore_path)
        
        # Convert to virtual mount path
        virtual_path = os.path.join(base_mount, rel_path)
        
        # Get directory stats
        try:
            stats = os.stat(root)
            
            # Extract platform from path (e.g., Native/Acorn -> Acorn)
            parts = rel_path.split(os.sep)
            platform = parts[1] if len(parts) > 1 else None
            
            cursor.execute("""
                INSERT OR IGNORE INTO files (
                    virtual_path, filename, directory, real_path,
                    size, modified_time, is_directory, mime_type, platform
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                virtual_path,
                os.path.basename(root) if os.path.basename(root) else 'Native',
                os.path.dirname(virtual_path),
                root,
                0,
                datetime.fromtimestamp(stats.st_mtime).isoformat(),
                True,
                'inode/directory',
                platform
            ))
            
            dir_count += 1
            
        except Exception as e:
            print(f"  Error processing directory {root}: {e}")
            continue
    
    conn.commit()
    
    # Print stats
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 0")
    total_files = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 1")
    total_dirs = cursor.fetchone()[0]
    
    print(f"\n✅ Database populated successfully!")
    print(f"  Files: {total_files}")
    print(f"  Directories: {total_dirs}")
    print(f"  Total entries: {total_files + total_dirs}")
    
    conn.close()


if __name__ == "__main__":
    # Use Docker paths
    db_path = "/mnt/filestorefs/.transfs_metadata.db"
    filestore_path = "/mnt/filestorefs"
    
    # Check if running in container
    if not os.path.exists("/mnt/filestorefs"):
        print("ERROR: This script must be run inside the Docker container")
        print("Run with: docker exec transfs python3 /app/populate_database.py")
        sys.exit(1)
    
    populate_database(db_path, filestore_path)
