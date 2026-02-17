#!/usr/bin/env python3
"""Check what Altair8800 data looks like in database"""

import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

print("Sample Altair8800 files in database:")
cursor.execute("""
    SELECT virtual_path, source_path, system, filename 
    FROM files 
    WHERE virtual_path LIKE '%Altair8800%' 
    LIMIT 10
""")

rows = cursor.fetchall()
if rows:
    for vpath, spath, system, fname in rows:
        print(f"System: {system}")
        print(f"  vpath: {vpath}")
        print(f"  spath: {spath}")
        print(f"  fname: {fname}")
        print()
else:
    print("No Altair8800 files found")

# Check raw path patterns
print("\nChecking path patterns for Altair/MITS files:")
cursor.execute("""
    SELECT DISTINCT 
        SUBSTR(virtual_path, 1, 50) as path_prefix,
        COUNT(*) as count
    FROM files
    WHERE virtual_path LIKE '%MITS%' OR virtual_path LIKE '%Altair%'
    GROUP BY SUBSTR(virtual_path, 1, 50)
""")

rows = cursor.fetchall()
for prefix, count in rows:
    print(f"  {prefix:50s}: {count:4d} files")

conn.close()
