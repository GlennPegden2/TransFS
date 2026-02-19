#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# First, populate system column if empty (from source_path)
cursor.execute("UPDATE files SET system = ? WHERE system IS NULL AND source_path LIKE ?", ("Apple/AppleII", "%Apple/AppleII%"))
cursor.execute("UPDATE files SET system = ? WHERE system IS NULL AND source_path LIKE ?", ("Nintendo/NES", "%Nintendo/NES%"))
print("Updated system columns")

# Extract client from system - use MiSTer for test
cursor.execute("UPDATE files SET client = 'MiSTer' WHERE client IS NULL")
print("Set client to MiSTer")

# Extract map_name from source_path
# Pattern: source_path contains /2mg/ or /hdv/ etc -> use that as the basis for map_name
cursor.execute("""
UPDATE files SET map_name = 
    CASE 
        WHEN source_path LIKE '%/2mg/%' THEN '2MG'
        WHEN source_path LIKE '%/2MG/%' THEN '2MG'
        WHEN source_path LIKE '%/hdv/%' THEN 'HDs'
        WHEN source_path LIKE '%/HDV/%' THEN 'HDs'
        WHEN source_path LIKE '%/dsk/%' THEN 'FDs'
        WHEN source_path LIKE '%/DSK/%' THEN 'FDs'
        WHEN source_path LIKE '%/do/%' THEN 'FDs'
        WHEN source_path LIKE '%/DO/%' THEN 'FDs'
        WHEN source_path LIKE '%/po/%' THEN 'FDs'
        WHEN source_path LIKE '%/PO/%' THEN 'FDs'
        ELSE NULL
    END
WHERE map_name IS NULL
""")
print("Set map_name based on source_path")

conn.commit()

# Verify
cursor.execute("SELECT COUNT(*) FROM files WHERE client IS NOT NULL")
count = cursor.fetchone()[0]
print(f"Total files with client: {count}")

cursor.execute("SELECT COUNT(*) FROM files WHERE map_name IS NOT NULL")
count = cursor.fetchone()[0]
print(f"Total files with map_name: {count}")

conn.close()
