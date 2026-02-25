#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/app/files.db')
cursor = conn.cursor()
result = cursor.execute('SELECT DISTINCT virtual_path FROM files WHERE client = "RetroBat" ORDER BY virtual_path LIMIT 20').fetchall()
for row in result:
    print(row[0])
conn.close()
