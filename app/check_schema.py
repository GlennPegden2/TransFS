#!/usr/bin/env python3
"""Check current database schema"""

import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

print("Current 'files' table schema:")
cursor.execute("PRAGMA table_info(files)")
columns = cursor.fetchall()
for col in columns:
    col_name, col_type = col[1], col[2]
    notnull = col[3]
    pk = col[5]
    print(f"  {col_name:20s} {col_type:10s} notnull={notnull} pk={pk}")

print()
print("File count in database:")
cursor.execute("SELECT COUNT(*) FROM files")
count = cursor.fetchone()[0]
print(f"  {count} entries")

conn.close()
