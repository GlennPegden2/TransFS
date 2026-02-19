#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check 4th & Inches files
cursor.execute("""
SELECT filename, size, map_name 
FROM files 
WHERE filename LIKE '%4th%' 
ORDER BY filename
""")

print("4th & Inches files in database:")
for filename, size, map_name in cursor.fetchall():
    print(f"  {filename:50} | Size: {size:10} | Map: {map_name}")

conn.close()
