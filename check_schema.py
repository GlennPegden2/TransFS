#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Get table info
cursor.execute("PRAGMA table_info(files)")
rows = cursor.fetchall()
print("Files table schema:")
for row in rows:
    print(f"  {row}")

conn.close()
