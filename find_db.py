#!/usr/bin/env python3
import sqlite3
import os

# Find database files
print("=== Looking for database files ===")
for root, dirs, files in os.walk('/app'):
    for file in files:
        if file.endswith('.db'):
            path = os.path.join(root, file)
            print(f"Found: {path}")
            try:
                conn = sqlite3.connect(path)
                cursor = conn.cursor()
                tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                print(f"  Tables: {[t[0] for t in tables]}")
                conn.close()
            except Exception as e:
                print(f"  Error: {e}")
