#!/usr/bin/env python3
"""Fix BBC_B system extraction in database."""

import sqlite3
import re
from pathlib import Path

db = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cur = db.cursor()

print("=== FIXING BBC_B SYSTEM EXTRACTION ===\n")

# Get all BBC_B entries
cur.execute('SELECT file_id, source_path FROM files WHERE source_path LIKE ?', ('%BBC_B%',))
bbc_b_files = cur.fetchall()

print(f"Found {len(bbc_b_files)} BBC_B entries\n")

# Parse system correctly: Native/Acorn/BBC_B/Software/...
# Extract as Acorn/BBC_B
fixed_count = 0
for file_id, source_path in bbc_b_files:
    # Pattern: .../Native/Acorn/BBC_B/...
    match = re.search(r'Native/(\w+)/([^/]+)/Software/', source_path)
    if match:
        system = f"{match.group(1)}/{match.group(2)}"
        cur.execute('UPDATE files SET system = ? WHERE file_id = ?', (system, file_id))
        fixed_count += 1
        if fixed_count <= 3:  # Show first few examples
            print(f"✓ Fixed {source_path}")
            print(f"  System: {system}\n")

print(f"✓ Updated {fixed_count} BBC_B entries with correct system\n")

# Verify
cur.execute('SELECT DISTINCT system FROM files WHERE source_path LIKE ? ORDER BY system', ('%BBC_B%',))
systems = cur.fetchall()
print(f"BBC_B system values after fix: {[s[0] for s in systems]}")

db.commit()
db.close()

print("\n✓ BBC_B system extraction fixed!")
