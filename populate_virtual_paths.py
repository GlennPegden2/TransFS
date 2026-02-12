#!/usr/bin/env python3
"""
Populate database with virtual paths by walking the FUSE mount.
This captures the virtual directory structure that TransFS creates from clients.yaml.
"""
import os
import sys
import sqlite3
import time
from pathlib import Path

db_path = "/mnt/filestorefs/.transfs_metadata.db"
mount_path = "/mnt/transfs"
filestore_path = "/mnt/filestorefs"

def populate_virtual_paths(client_name="MiSTer", max_depth=None):
    """
    Walk the FUSE mount to capture virtual paths and populate database.
    
    Args:
        client_name: Client to populate (MiSTer, RetroBat, etc.)
        max_depth: Maximum depth to walk (None = unlimited)
    """
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return False
    
    client_mount = os.path.join(mount_path, client_name)
    if not os.path.exists(client_mount):
        print(f"ERROR: Client mount not found at {client_mount}")
        return False
    
    print(f"Populating database from FUSE mount: {client_mount}")
    print(f"This will capture the virtual directory structure...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = int(time.time())
    dir_count = 0
    file_count = 0
    error_count = 0
    skip_count = 0
    
    # Walk the FUSE mount to get virtual paths
    for root, dirs, files in os.walk(client_mount):
        # Calculate depth
        depth = root.replace(client_mount, '').count(os.sep)
        if max_depth is not None and depth > max_depth:
            dirs.clear()  # Don't descend further
            continue
        
        # Add directories
        for dirname in dirs:
            dir_path = os.path.join(root, dirname)
            
            # Skip hidden and special directories
            if dirname.startswith('.') or dirname.endswith('.transfs.zipindex'):
                skip_count += 1
                continue
            
            try:
                stat_info = os.stat(dir_path)
                
                # For virtual paths, source_path is often the same as virtual_path
                # or derived from Native sources (TransFS handles the mapping)
                cursor.execute("""
                    INSERT OR REPLACE INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, is_archive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dir_path,  # Use virtual path as source for now
                    dir_path,  # Virtual path
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
                
                if dir_count % 100 == 0:
                    print(f"  Directories processed: {dir_count}")
                    conn.commit()
                
            except Exception as e:
                print(f"  Error processing directory {dir_path}: {e}")
                error_count += 1
        
        # Add files
        for filename in files:
            file_path = os.path.join(root, filename)
            
            # Skip hidden files, temp files, and zip indices
            if (filename.startswith('.') or 
                filename.endswith('.transfs.zipindex') or
                filename.endswith('~')):
                skip_count += 1
                continue
            
            try:
                stat_info = os.stat(file_path)
                _, ext = os.path.splitext(filename)
                
                # Detect archive files
                is_archive = ext.lower() in ['.zip', '.7z', '.rar', '.tar', '.gz']
                
                cursor.execute("""
                    INSERT OR REPLACE INTO files (
                        source_path, virtual_path, filename, extension,
                        size, mtime, ctime, atime, ino, mode,
                        is_directory, is_archive, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_path,  # Use virtual path as source
                    file_path,  # Virtual path
                    filename,
                    ext,
                    stat_info.st_size,
                    int(stat_info.st_mtime),
                    int(stat_info.st_ctime),
                    int(stat_info.st_atime),
                    stat_info.st_ino,
                    stat_info.st_mode,
                    False,  # is_directory
                    is_archive,
                    now,
                    now
                ))
                file_count += 1
                
                if file_count % 500 == 0:
                    print(f"  Files processed: {file_count}")
                    conn.commit()
                
            except Exception as e:
                print(f"  Error processing file {file_path}: {e}")
                error_count += 1
        
        # Commit after each directory
        if (file_count + dir_count) % 1000 == 0:
            conn.commit()
            print(f"  Progress: {dir_count} dirs, {file_count} files, {error_count} errors")
    
    conn.commit()
    
    # Print summary
    cursor.execute("""
        SELECT COUNT(*) FROM files 
        WHERE is_directory = 0 AND virtual_path LIKE ?
    """, (os.path.join(mount_path, client_name) + '%',))
    db_file_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM files 
        WHERE is_directory = 1 AND virtual_path LIKE ?
    """, (os.path.join(mount_path, client_name) + '%',))
    db_dir_count = cursor.fetchone()[0]
    
    print(f"\n✅ Virtual path population complete!")
    print(f"  Client: {client_name}")
    print(f"  Directories added: {dir_count}")
    print(f"  Files added: {file_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Errors: {error_count}")
    print(f"\nDatabase totals for {client_name}:")
    print(f"  Directories: {db_dir_count}")
    print(f"  Files: {db_file_count}")
    print(f"  Total: {db_dir_count + db_file_count}")
    
    # Show some examples
    print(f"\nSample entries:")
    cursor.execute("""
        SELECT virtual_path, filename, size 
        FROM files 
        WHERE virtual_path LIKE ? AND is_directory = 0
        LIMIT 5
    """, (os.path.join(mount_path, client_name) + '%',))
    
    for vpath, fname, size in cursor.fetchall():
        print(f"  {fname} ({size} bytes) -> {vpath}")
    
    conn.close()
    return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Populate database with virtual paths from FUSE mount')
    parser.add_argument('--client', default='MiSTer', help='Client name (default: MiSTer)')
    parser.add_argument('--max-depth', type=int, help='Maximum depth to walk')
    args = parser.parse_args()
    
    if not os.path.exists(mount_path):
        print(f"ERROR: Mount path not found: {mount_path}")
        print("This script must run inside the Docker container with TransFS mounted")
        sys.exit(1)
    
    success = populate_virtual_paths(args.client, args.max_depth)
    sys.exit(0 if success else 1)
