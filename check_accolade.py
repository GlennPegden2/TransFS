#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check all files named 4th & Inches with any extension in Apple-II
cursor.execute("""
    SELECT filename, size, extension, map_name 
    FROM files 
    WHERE filename LIKE ? AND system=?
    ORDER BY filename
""", ('%4th%Inches%', 'Apple/AppleII'))

rows = cursor.fetchall()
print(f"All files matching '4th & Inches' or '4th*Inches' in Apple-II:")
for filename, size, ext, map_name in rows:
    kb = size / 1024
    print(f"  {filename}")
    print(f"    Size: {size} bytes ({kb:.2f} KB), Ext: {ext}, Map: {map_name}")

conn.close()
