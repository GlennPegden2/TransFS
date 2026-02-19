#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check extensions in 2mg directory
cursor.execute("SELECT DISTINCT LOWER(extension) FROM files WHERE source_path LIKE '%2mg%' ORDER BY extension")
rows = cursor.fetchall()
print("Extensions in 2mg directory:")
for (ext,) in rows:
    cursor.execute("SELECT COUNT(*) FROM files WHERE LOWER(extension) = ? AND source_path LIKE '%2mg%'", (ext,))
    count = cursor.fetchone()[0]
    print(f"  .{ext}: {count} files")

# Check if Accolade files are there
print("\nChecking for Accolade files:")
cursor.execute("SELECT COUNT(*) FROM files WHERE filename LIKE '%Accolade%' AND source_path LIKE '%2mg%'")
count = cursor.fetchone()[0]
print(f"  Total Accolade files in 2mg: {count}")

# Check for any 4th files
cursor.execute("SELECT COUNT(*) FROM files WHERE (filename LIKE '%4th%' OR filename LIKE '%Inches%')")
count = cursor.fetchone()[0]
print(f"  Total files with 4th or Inches: {count}")

conn.close()
