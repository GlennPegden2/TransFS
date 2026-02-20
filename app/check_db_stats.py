#!/usr/bin/env python3
import sqlite3
db = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = db.cursor()
cursor.execute("SELECT COUNT(*) FROM files")
count = cursor.fetchone()[0]
print(f'Total files in database: {count}')
cursor.execute("SELECT COUNT(*) FROM files WHERE system = 'Atari2600'")
atari_count = cursor.fetchone()[0]
print(f'Atari 2600 files: {atari_count}')
db.close()
