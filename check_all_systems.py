#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Check all systems acorss all clients
print("=== All systems in database ===")
cur.execute("SELECT DISTINCT client, system FROM files ORDER BY client, system LIMIT 20")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

print(f"\nTotal unique client/system pairs: {cur.rowcount}")

# Check RetroBat specifically
print("\n=== RetroBat systems ===")
cur.execute("SELECT system, COUNT(*) FROM files WHERE client='RetroBat' GROUP BY system")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} files")

# Check for bios map
print("\n=== Files with map_name='bios' ===")
cur.execute("SELECT client, COUNT(*) FROM files WHERE map_name='bios' GROUP BY client")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} files")

conn.close()
