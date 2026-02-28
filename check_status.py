#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

print("=== RetroBat Client Status ===")
cur.execute("SELECT system, map_name, COUNT(*) FROM files WHERE client='RetroBat' GROUP BY system, map_name ORDER BY system, map_name")
for row in cur.fetchall():
    print(f"  {row[0]:15} {row[1]:20} {row[2]:6} files")

print("\n=== Sample bios files (shared) ===")
cur.execute("SELECT client, system, map_name, filename, COUNT(*) FROM files WHERE map_name='bios' GROUP BY client, system, map_name, filename LIMIT 15")
for row in cur.fetchall():
    print(f"  {row[0]}/{row[1]}/{row[2]}: {row[3]} (count:{row[4]})")

conn.close()
