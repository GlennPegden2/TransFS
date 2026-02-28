#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Check ALL clients
print("=== ALL Clients ===")
cur.execute("SELECT DISTINCT client FROM files ORDER BY client")
for row in cur.fetchall():
    print(f"  {row[0]}")

# Check for ANY RetroBat files
print("\n=== Files by client ===")
cur.execute("SELECT client, COUNT(*) FROM files GROUP BY client ORDER BY COUNT DESC")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} files")

# Check if SharedBIOS system exists
print("\n=== All systems ===")
cur.execute("SELECT DISTINCT client, system FROM files ORDER BY client, system")
count= cur.rowcount
for row in cur.fetchall():
    print(f"  {row[0]}/{row[1]}")
print(f"Total: {count} unique client/system pairs")

conn.close()
