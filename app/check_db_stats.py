#!/usr/bin/env python3
"""
Analyze database performance and statistics.
"""
import sqlite3
import time

db_path = '/mnt/filestorefs/.transfs_metadata.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Count statistics
cursor.execute('SELECT COUNT(*) FROM files')
total = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE is_directory = 1')
dirs = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE is_directory = 0')
files = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE virtual_path LIKE ?', ('/mnt/transfs/MiSTer%',))
mister = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM files WHERE virtual_path LIKE ?', ('/mnt/transfs/Native%',))
native = cursor.fetchone()[0]

print('DATABASE STATISTICS')
print('=' * 50)
print(f'Total entries:    {total:,}')
print(f'  Directories:    {dirs:,}')
print(f'  Files:          {files:,}')
print()
print('BY CLIENT:')
print(f'  MiSTer:         {mister:,}')
print(f'  Native:         {native:,}')
print()

# Performance test
print('PERFORMANCE TEST (10 random queries)')
print('=' * 50)

# Sample 10 random MiSTer entries
cursor.execute('''
    SELECT virtual_path FROM files 
    WHERE virtual_path LIKE '/mnt/transfs/MiSTer%'
    ORDER BY RANDOM() LIMIT 10
''')

paths = [row[0] for row in cursor.fetchall()]
total_time = 0

for path in paths:
    start = time.time()
    cursor.execute('SELECT * FROM files WHERE virtual_path = ?', (path,))
    result = cursor.fetchone()
    elapsed = (time.time() - start) * 1000  # Convert to ms
    total_time += elapsed
    status = 'OK' if result else 'FAIL'
    filename = path.split('/')[-1]
    print(f'{status} {filename[:30]:<30} {elapsed:.3f}ms')

avg = total_time / len(paths)
print()
print(f'Average query time: {avg:.3f}ms')
print(f'Total for 10 queries: {total_time:.2f}ms')

conn.close()
