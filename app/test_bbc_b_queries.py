#!/usr/bin/env python3
"""BBC_B database query tests."""

import sqlite3

db = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cur = db.cursor()

print("=== PHASE 2.3: BBC_B DATABASE QUERY TESTS ===\n")

# 1. Count BBC_B files
cur.execute('SELECT COUNT(*) FROM files WHERE system = ?', ('Acorn/BBC_B',))
total = cur.fetchone()[0]
print(f"1. Total BBC_B files: {total}")

# 2. Files by extension
cur.execute('''
SELECT extension, COUNT(*) as count FROM files 
WHERE system = ? 
GROUP BY extension 
ORDER BY count DESC
''', ('Acorn/BBC_B',))
print("\n2. BBC_B files by extension:")
for ext, cnt in cur.fetchall():
    print(f"   .{ext:8s}: {cnt:3d} files")

# 3. Files by folder/type
cur.execute('''
SELECT 
  CASE 
    WHEN source_path LIKE '%/SSD/%' THEN 'Floppies (SSD)'
    WHEN source_path LIKE '%/MMB/%' THEN 'Hard Disks (MMB)'
    ELSE 'Other'
  END as type,
  COUNT(*) as count
FROM files WHERE system = ?
GROUP BY type
ORDER BY type
''', ('Acorn/BBC_B',))
print("\n3. BBC_B files by type:")
for ftype, cnt in cur.fetchall():
    print(f"   {ftype:20s}: {cnt:3d} files")

# 4. Sample files from each type
print("\n4. Sample BBC_B files:")
cur.execute('''
SELECT filename, extension FROM files 
WHERE system = ? AND source_path LIKE '%/SSD/%'
LIMIT 3
''', ('Acorn/BBC_B',))
print("   Floppies (SSD):")
for fname, ext in cur.fetchall():
    print(f"     • {fname}")

cur.execute('''
SELECT filename, extension FROM files 
WHERE system = ? AND source_path LIKE '%/MMB/%'
LIMIT 3
''', ('Acorn/BBC_B',))
print("   Hard Disks (MMB):")
for fname, ext in cur.fetchall():
    print(f"     • {fname}")

# 5. File size summary
cur.execute('SELECT SUM(size) FROM files WHERE system = ?', ('Acorn/BBC_B',))
total_size_bytes = cur.fetchone()[0] or 0
total_size_mb = total_size_bytes / (1024 * 1024)
print(f"\n5. Total BBC_B size: {total_size_mb:.2f} MB")

# 6. Verify content_type field
cur.execute('SELECT DISTINCT content_type FROM files WHERE system = ?', ('Acorn/BBC_B',))
content_types = cur.fetchall()
print(f"\n6. Content types: {[ct[0] if ct[0] else 'NULL' for ct in content_types]}")

print("\n✓ All BBC_B database queries successful!")

db.close()
