#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# First, fix the 2MG files - they should be assigned to FDs or HDs based on size
# FDs: 2MG files <= 908288 bytes
# HDs: 2MG files >= 908289 bytes

cursor.execute("""
UPDATE files SET map_name = 'FDs'
WHERE extension = '2mg' AND map_name = '2MG' AND size <= 908288
""")
print("Assigned 2MG files <= 908288 bytes to FDs")

cursor.execute("""
UPDATE files SET map_name = 'HDs'
WHERE extension = '2mg' AND map_name = '2MG' AND size >= 908289
""")
print("Assigned 2MG files >= 908289 bytes to HDs")

conn.commit()

# Verify
cursor.execute("SELECT map_name, COUNT(*) FROM files WHERE client='MiSTer' AND system='Apple/AppleII' GROUP BY map_name")
rows = cursor.fetchall()
print("\nFiles per map in Apple-II after fix:")
for map_name, count in rows:
    print(f"  {map_name}: {count} files")

# Specifically check 4th & Inches
cursor.execute("SELECT filename, extension, size, map_name FROM files WHERE filename LIKE '%Inches%'")
rows = cursor.fetchall()
print("\n4th & Inches files and their assignments:")
for filename, ext, size, map_name in rows:
    print(f"  {filename}: {size} bytes -> {map_name}")

conn.close()
