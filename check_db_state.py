#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Check what clients exist
print("=== Clients in database ===")
cur.execute("SELECT DISTINCT client FROM files ORDER BY client")
for row in cur.fetchall():
    print(f"  {row[0]}")

# Check what systems exist
print("\n=== Systems in database ===")
cur.execute("SELECT DISTINCT client, system FROM files ORDER BY client, system")
for row in cur.fetchall():
    print(f"  {row[0]} / {row[1]}")

# Check what map names exist  
print("\n=== Map names in database ===")
cur.execute("SELECT DISTINCT client, system, map_name, COUNT(*) FROM files GROUP BY client, system, map_name ORDER BY client, system, map_name")
for row in cur.fetchall():
    print(f"  {row[0]} / {row[1]} / {row[2]}: {row[3]} files")

# Show all files
print("\n=== All files ===")
cur.execute("SELECT client, system, map_name, filename, virtual_path FROM files LIMIT 20")
for row in cur.fetchall():
    print(f"  {row[0]}/{row[1]}/{row[2]}: {row[3]}")
    print(f"    → {row[4]}")

conn.close()
