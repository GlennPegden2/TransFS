#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

print("=== Files with map_name='.' ===")
cur.execute("SELECT filename, source_path, virtual_path FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='.'")
for row in cur.fetchall():
    print(f"  {row[0]}")
    print(f"    Source: {row[1]}")
    print(f"    Virtual: {row[2]}")
    print()

print("\n=== Sample files with map_name='bios' ===")
cur.execute("SELECT filename, source_path, virtual_path FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='bios' LIMIT 10")
for row in cur.fetchall():
    print(f"  {row[0]}")
    print(f"    Source: {row[1]}")
    print(f"    Virtual: {row[2]}")
    print()

conn.close()
