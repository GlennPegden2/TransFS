#!/usr/bin/env python3
"""
Populate MiSTer data into the TransFS metadata database.
Scans /mnt/filestorefs/MiSTer and adds entries to the database for parity testing.
"""
import os
import sys
import sqlite3
import time
from pathlib import Path

db_path = "/mnt/filestorefs/.transfs_metadata.db"
filestore_path = "/mnt/filestorefs"
mount_path = "/mnt/transfs"

def populate_mister_database():
    """Populate database with MiSTer filesystem structure."""
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        print("Run this script in the container with an initialized database")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = int(time.time())
    
    # First, add all directories from MiSTer source
    mister_source = os.path.join(filestore_path, "MiSTer")
    if not os.path.exists(mister_source):
        print(f"ERROR: MiSTer source not found at {mister_source}")
        return False
    
    print(f"Scanning MiSTer source: {mister_source}")
    
    dir_count = 0
    file_count = 0
    error_count = 0
    
    # Walk through the MiSTer directory structure
    for root, dirs, files in os.walk(mister_source):
        # Add all directories
        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            rel_path = os.path.relpath(dir_path, filestore_path)
            virt_path = os.path.join(mount_path, rel_path)
            
            try:
                stat_info = os.stat(dir_path)
                cursor.execute("""
                    INSERT OR IGNORE INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, is_archive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dir_path,
                    virt_path,
                    dirname,
                    None,
                    0,
                    int(stat_info.st_mtime),
                    int(stat_info.st_ctime),
                    int(stat_info.st_atime),
                    stat_info.st_ino,
                    stat_info.st_mode,
                    True,  # is_directory
                    False,  # is_archive
                    now,
                    now
                ))
                dir_count += 1
            except Exception as e:
                print(f"  Error adding directory {dir_path}: {e}")
                error_count += 1
        
        # Add all files
        for filename in files:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, filestore_path)
            virt_path = os.path.join(mount_path, rel_path)
            
            try:
                stat_info = os.stat(file_path)
                _, ext = os.path.splitext(filename)
                
                cursor.execute("""
                    INSERT OR IGNORE INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, is_archive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_path,
                    virt_path,
                    filename,
                    ext,
                    stat_info.st_size,
                    int(stat_info.st_mtime),
                    int(stat_info.st_ctime),
                    int(stat_info.st_atime),
                    stat_info.st_ino,
                    stat_info.st_mode,
                    False,  # is_directory
                    False,  # is_archive
                    now,
                    now
                ))
                file_count += 1
                
                if (file_count + dir_count) % 100 == 0:
                    print(f"  Processed {file_count + dir_count} entries...")
            except Exception as e:
                print(f"  Error adding file {file_path}: {e}")
                error_count += 1
        
        # Commit in batches
        if (file_count + dir_count) % 500 == 0:
            conn.commit()
    
    conn.commit()
    
    # Print summary
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 0 AND source_path LIKE ?", 
                   (os.path.join(filestore_path, "MiSTer") + '%',))
    mister_file_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 1 AND source_path LIKE ?",
                   (os.path.join(filestore_path, "MiSTer") + '%',))
    mister_dir_count = cursor.fetchone()[0]
    
    print(f"\n✅ MiSTer database population complete!")
    print(f"  Directories added: {dir_count}")
    print(f"  Files added: {file_count}")
    print(f"  Errors: {error_count}")
    print(f"\nMiSTer entries in database:")
    print(f"  Directories: {mister_dir_count}")
    print(f"  Files: {mister_file_count}")
    print(f"  Total: {mister_dir_count + mister_file_count}")
    
    conn.close()
    return True

if __name__ == "__main__":
    if not os.path.exists(filestore_path):
        print(f"ERROR: Filestore path not found: {filestore_path}")
        print("This script must run inside the Docker container")
        sys.exit(1)
    
    success = populate_mister_database()
    sys.exit(0 if success else 1)
