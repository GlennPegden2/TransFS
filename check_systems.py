#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check what system names we have
cursor.execute("SELECT DISTINCT system FROM files WHERE system IS NOT NULL")
rows = cursor.fetchall()
print("System names in database:")
for (system,) in rows:
    print(f"  {system}")

# Check files for FDs with different system names
cursor.execute("SELECT COUNT(*) FROM files WHERE client='MiSTer' AND map_name='FDs'")
count = cursor.fetchone()[0]
print(f"\nFiles with map_name='FDs': {count}")

cursor.execute("SELECT COUNT(*) FROM files WHERE system LIKE '%AppleII%' AND map_name='FDs'")
count = cursor.fetchone()[0]
print(f"Files with system LIKE '%AppleII%' and map_name='FDs': {count}")

conn.close()
