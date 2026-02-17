#!/usr/bin/env python3
"""Check BBC_B status in database."""

import sqlite3
from pathlib import Path

db_path = Path('/mnt/filestorefs/.transfs_metadata.db')
db = sqlite3.connect(str(db_path))
cur = db.cursor()

print("=== BBC_B DATABASE STATUS ===\n")

# Check schema
cur.execute("PRAGMA table_info(files)")
columns = cur.fetchall()
print("Database columns:")
for col in columns:
    print(f"  {col[1]:20s} ({col[2]})")

# Check if BBC_B exists
cur.execute("SELECT COUNT(*) FROM files WHERE system LIKE ?", ('%BBC_B%',))
count = cur.fetchone()[0]
print(f"\nBBC_B entries in database: {count}")

if count == 0:
    print("\n⚠️  BBC_B files NOT in database yet - will need Phase 2 migration")
else:
    # Get extensions
    cur.execute("SELECT DISTINCT ? FROM files WHERE system LIKE ?", 
                (sqlite3.Row, '%BBC_B%'))
    
    # Sample files
    cur.execute("SELECT * FROM files WHERE system LIKE ? LIMIT 5", ('%BBC_B%',))
    print("\nSample BBC_B files in database:")
    for row in cur.fetchall():
        print(f"  {row}")

db.close()
