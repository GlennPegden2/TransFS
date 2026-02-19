#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check 4th & Inches files and their map_names
cursor.execute("SELECT filename, extension, map_name FROM files WHERE filename LIKE '%Inches%' LIMIT 5")
rows = cursor.fetchall()
print("4th & Inches files and their map_names:")
for filename, ext, map_name in rows:
    print(f"  {filename} ({ext}) -> map: {map_name}")

# Count files per map
cursor.execute("SELECT map_name, COUNT(*) FROM files WHERE client='MiSTer' AND system='Apple/AppleII' GROUP BY map_name")
rows = cursor.fetchall()
print("\nFiles per map in Apple-II:")
for map_name, count in rows:
    print(f"  {map_name}: {count} files")

conn.close()
