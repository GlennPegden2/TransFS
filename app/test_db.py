#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check total files
cursor.execute('SELECT COUNT(*) FROM files')
print(f"Total files in database: {cursor.fetchone()[0]}")

# Check Apple-II files
cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II"')
print(f"Total Apple-II files: {cursor.fetchone()[0]}")

# Check FDs/HDs
cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II" AND map_name IN ("FDs", "HDs")')
print(f"Total Apple-II FDs/HDs files: {cursor.fetchone()[0]}")

# Check by map
cursor.execute('SELECT map_name, COUNT(*) FROM files WHERE system="Apple-II" GROUP BY map_name')
for map_name, count in cursor.fetchall():
    print(f"  {map_name}: {count} files")

# Sample files
cursor.execute('SELECT filename, extension, map_name FROM files WHERE system="Apple-II" AND map_name="FDs" LIMIT 3')
rows = cursor.fetchall()
if rows:
    print("\nSample FDs files:")
    for row in rows:
        print(f"  {row[0]} ({row[1]}) in {row[2]}")
else:
    print("\nNo FDs files found!")

conn.close()
