#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II"')
total = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II" AND map_name="FDs"')
fds = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II" AND map_name="HDs"')
hds = cursor.fetchone()[0]

print(f'Total Apple-II files: {total}')
print(f'  FDs: {fds}')
print(f'  HDs: {hds}')

# Show breakdown by extension
cursor.execute('''
SELECT extension, COUNT(*) as count, map_name 
FROM files 
WHERE system="Apple-II" 
GROUP BY extension, map_name 
ORDER BY extension, map_name
''')

print('\nBreakdown by extension:')
for ext, count, map_name in cursor.fetchall():
    print(f'  {ext}: {count} in {map_name}')

conn.close()
