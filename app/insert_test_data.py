#!/usr/bin/env python3
"""
Populate the TransFS metadata database with test data for Phase 5 testing.
"""
import os
import sys
import sqlite3
from datetime import datetime
import time

db_path = "/mnt/filestorefs/.transfs_metadata.db"
filestore_path = "/mnt/filestorefs"
mount_path = "/mnt/transfs"

def insert_test_data():
    """Insert test entries into the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear existing data
    cursor.execute("DELETE FROM files")
    conn.commit()
    
    now = int(time.time())
    entries = []
    
    # First, add directory entries for Native platform
    dir_entries = [
        ("/mnt/transfs/Native", "/mnt/filestorefs/Native", "Native", True),
        ("/mnt/transfs/Native/Acorn", "/mnt/filestorefs/Native/Acorn", "Acorn", True),
        ("/mnt/transfs/Native/Amstrad", "/mnt/filestorefs/Native/Amstrad", "Amstrad", True),
        ("/mnt/transfs/Native/Apple", "/mnt/filestorefs/Native/Apple", "Apple", True),
        ("/mnt/transfs/Native/Atari", "/mnt/filestorefs/Native/Atari", "Atari", True),
        ("/mnt/transfs/Native/MITS", "/mnt/filestorefs/Native/MITS", "MITS", True),
        ("/mnt/transfs/Native/Tandy", "/mnt/filestorefs/Native/Tandy", "Tandy", True),
    ]
    
    # Sample file entries
    file_entries = [
        ("/mnt/transfs/Native/Acorn/test_rom.bin", "/mnt/filestorefs/Native/Acorn/test_rom.bin", "test_rom.bin", False, 1024),
        ("/mnt/transfs/Native/Amstrad/demo.dsk", "/mnt/filestorefs/Native/Amstrad/demo.dsk", "demo.dsk", False, 2048),
        ("/mnt/transfs/Native/Apple/game.do", "/mnt/filestorefs/Native/Apple/game.do", "game.do", False, 4096),
        ("/mnt/transfs/Native/Atari/breakout.bin", "/mnt/filestorefs/Native/Atari/breakout.bin", "breakout.bin", False, 512),
    ]
    
    # Insert directories
    for virt_path, real_path, filename, is_dir in dir_entries:
        # Only insert if the directory actually exists
        if os.path.exists(real_path):
            try:
                stat_info = os.stat(real_path)
                cursor.execute("""
                    INSERT INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, is_archive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    real_path,
                    virt_path,
                    filename,
                    None,
                    0,
                    int(stat_info.st_mtime),
                    int(stat_info.st_ctime),
                    int(stat_info.st_atime),
                    stat_info.st_ino,
                    stat_info.st_mode,
                    True,
                    False,
                    now,
                    now
                ))
            except Exception as e:
                print(f"Error inserting directory {real_path}: {e}")
    
    # Insert sample files
    for virt_path, real_path, filename, is_dir, size in file_entries:
        # Only insert if we can determine properties
        try:
            # Get extension
            _, ext = os.path.splitext(filename)
            
            # Create dummy stat info since these are sample files
            stat_mtime = now
            stat_ctime = now
            stat_atime = now
            ino = hash(real_path) & 0xffffffff
            mode = 33188  # Regular file permission
            
            cursor.execute("""
                INSERT INTO files (
                    source_path, virtual_path, filename, extension,
                    size, mtime, ctime, atime, ino, mode,
                    is_directory, is_archive, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                real_path,
                virt_path,
                filename,
                ext,
                size,
                stat_mtime,
                stat_ctime,
                stat_atime,
                ino,
                mode,
                False,
                False,
                now,
                now
            ))
        except Exception as e:
            print(f"Error inserting file {real_path}: {e}")
    
    conn.commit()
    
    # Count entries
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 0")
    file_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM files WHERE is_directory = 1")
    dir_count = cursor.fetchone()[0]
    
    print(f"✅ Test data inserted successfully!")
    print(f"  Directories: {dir_count}")
    print(f"  Files: {file_count}")
    print(f"  Total: {file_count + dir_count}")
    
    conn.close()

if __name__ == "__main__":
    if not os.path.exists(filestore_path):
        print("ERROR: Filestore path not found")
        sys.exit(1)
    
    insert_test_data()
