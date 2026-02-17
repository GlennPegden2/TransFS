#!/usr/bin/env python3
"""Check BBC_B database migration."""

import sqlite3

db = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cur = db.cursor()

print("=== BBC_B DATABASE STATUS AFTER MIGRATION ===\n")

# Count BBC_B entries
cur.execute('SELECT COUNT(*) FROM files WHERE source_path LIKE ?', ('%BBC_B%',))
count = cur.fetchone()[0]
print(f'BBC_B files in database: {count}')

# Get sample entries
cur.execute('SELECT source_path, filename, extension FROM files WHERE source_path LIKE ? LIMIT 5', ('%BBC_B%',))
print('\nSample BBC_B entries:')
for row in cur.fetchall():
    print(f'  {row}')

# Check system extraction
cur.execute('SELECT DISTINCT system FROM files WHERE source_path LIKE ? ORDER BY system', ('%BBC_B%',))
systems = cur.fetchall()
print(f'\nSystem values for BBC_B: {[s[0] if s[0] else "EMPTY" for s in systems]}')

# Get breakdown by folder/extension
cur.execute('''
SELECT extension, COUNT(*) as count FROM files 
WHERE source_path LIKE ? 
GROUP BY extension 
ORDER BY count DESC
''', ('%BBC_B%',))
print('\nBBC_B files by extension:')
for ext, cnt in cur.fetchall():
    print(f'  {ext:10s}: {cnt:3d}')

db.close()
