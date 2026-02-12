#!/usr/bin/env python3
import sqlite3
import sys

db_path = "/mnt/filestorefs/.transfs_metadata.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get table schema
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='files'")
result = cursor.fetchone()
if result:
    print("Files table schema:")
    print(result[0])
else:
    print("Files table not found")
    print("\nAvailable tables:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for table in cursor.fetchall():
        print(f"  - {table[0]}")

conn.close()
