#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check which 2mg files are in the database
cursor.execute("SELECT filename FROM files WHERE LOWER(extension)='2mg' ORDER BY filename")
rows = cursor.fetchall()
print("2MG files in database:")
for (filename,) in rows:
    print(f"  {filename}")

conn.close()
