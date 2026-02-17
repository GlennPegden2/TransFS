#!/usr/bin/env python3
"""
Database Schema Migration V2 - Fix system extraction for Native files
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = '/mnt/filestorefs/.transfs_metadata.db'

def fix_system_extraction():
    """Fix the system field to use Manufacturer/System format"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("Extracting system using Python parsing...")
        
        cursor.execute("SELECT file_id, virtual_path FROM files WHERE system LIKE '%/%' OR virtual_path LIKE '%Altair8800%'")
        rows = cursor.fetchall()
        
        for file_id, vpath in rows:
            if '/Native/' in vpath:
                # Path format: /mnt/transfs/Native/Manufacturer/System/...
                parts = vpath.split('/')
                if len(parts) >= 5:
                    manufacturer = parts[4]  # index 4 after split
                    system = parts[5]        # index 5 after split
                    system_id = f"{manufacturer}/{system}"
                    cursor.execute("UPDATE files SET system = ? WHERE file_id = ?", (system_id, file_id))
            elif '/MiSTer/' in vpath:
                cursor.execute("UPDATE files SET system = ? WHERE file_id = ?", ('MiSTer', file_id))
        
        conn.commit()
        print("System extraction fixed")
        
        # Verify Altair8800
        cursor.execute("""
            SELECT system, COUNT(*)
            FROM files 
            WHERE virtual_path LIKE '%Altair8800%'
            GROUP BY system
        """)
        
        print("\nAltair8800 entries by system:")
        for system, count in cursor.fetchall():
            print(f"  {system:30s}: {count:4d} entries")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    if not fix_system_extraction():
        sys.exit(1)
