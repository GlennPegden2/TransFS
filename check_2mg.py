#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check all 2MG files in Apple-II system
cursor.execute("""
    SELECT filename, size, extension, map_name 
    FROM files 
    WHERE system=? AND extension=?
    ORDER BY size DESC
""", ('Apple-II', '2MG'))

rows = cursor.fetchall()
print(f"2MG files in Apple-II system: {len(rows)} found")
for filename, size, ext, map_name in rows:
    print(f"  {filename}: {size} bytes → map {map_name}")

conn.close()


conn.close()
