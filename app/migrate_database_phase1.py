#!/usr/bin/env python3
"""
Database Schema Migration Script
Migrates existing database from old schema to Phase 1 schema with system/content_type columns
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = '/mnt/filestorefs/.transfs_metadata.db'

def backup_database():
    """Create backup before migration"""
    db_file = Path(DB_PATH)
    backup_file = db_file.parent / f"{db_file.name}.backup"
    
    if not db_file.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return False
    
    try:
        import shutil
        shutil.copy2(str(db_file), str(backup_file))
        print(f"✓ Backup created: {backup_file}")
        return True
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False

def migrate_schema():
    """Add Phase 1 columns to existing database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("Starting schema migration...")
        
        # Check if system column already exists
        cursor.execute("PRAGMA table_info(files)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'system' not in columns:
            print("Adding 'system' column...")
            cursor.execute("ALTER TABLE files ADD COLUMN system TEXT DEFAULT 'Unknown'")
        else:
            print("'system' column already exists")
        
        if 'content_type' not in columns:
            print("Adding 'content_type' column...")
            cursor.execute("ALTER TABLE files ADD COLUMN content_type TEXT DEFAULT 'application/octet-stream'")
        else:
            print("'content_type' column already exists")
        
        conn.commit()
        
        # Extract system from virtual_path or source_path
        print("Extracting system information from paths...")
        
        # For Native files: /mnt/transfs/Native/Manufacturer/System
        cursor.execute("""
            UPDATE files
            SET system = 
                CASE 
                    WHEN virtual_path LIKE '/mnt/transfs/Native/%' THEN
                        SUBSTR(virtual_path, 29, INSTR(SUBSTR(virtual_path, 29), '/') - 1)
                    WHEN virtual_path LIKE '/mnt/transfs/MiSTer/%' THEN
                        'MiSTer'
                    ELSE 'Unknown'
                END
            WHERE system = 'Unknown'
        """)
        
        updated = cursor.rowcount
        print(f"Updated {updated} entries with system information")
        
        # Create indexes if they don't exist
        print("Creating indexes...")
        
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_system ON files(system)",
            "CREATE INDEX IF NOT EXISTS idx_system_ext ON files(system, extension)",
            "CREATE INDEX IF NOT EXISTS idx_content_type ON files(content_type)"
        ]
        
        for stmt in index_statements:
            cursor.execute(stmt)
            print(f"  {stmt}")
        
        conn.commit()
        conn.close()
        
        print("✓ Schema migration complete!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_migration():
    """Verify the migration was successful"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("\nVerifying migration...")
        
        # Check schema
        cursor.execute("PRAGMA table_info(files)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        if 'system' in columns and 'content_type' in columns:
            print("✓ New columns added successfully")
        else:
            print("❌ Columns not found after migration")
            return False
        
        # Check data
        cursor.execute("SELECT COUNT(*) FROM files")
        total = cursor.fetchone()[0]
        print(f"Total entries: {total}")
        
        cursor.execute("SELECT COUNT(*) FROM files WHERE system != 'Unknown'")
        systems_populated = cursor.fetchone()[0]
        print(f"Entries with system: {systems_populated}")
        
        # Sample systems
        cursor.execute("SELECT DISTINCT system FROM files LIMIT 10")
        systems = [row[0] for row in cursor.fetchall()]
        print(f"Sample systems: {systems}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

def main():
    print("=" * 70)
    print("PHASE 1: DATABASE SCHEMA MIGRATION")
    print("=" * 70)
    print()
    
    # Backup
    if not backup_database():
        sys.exit(1)
    
    print()
    
    # Migrate
    if not migrate_schema():
        sys.exit(1)
    
    print()
    
    # Verify
    if not verify_migration():
        sys.exit(1)
    
    print()
    print("=" * 70)
    print("MIGRATION SUCCESSFUL")
    print("=" * 70)

if __name__ == '__main__':
    main()
