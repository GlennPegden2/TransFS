#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Check for duplicate filenames
cur.execute("""
    SELECT filename, COUNT(*) as cnt 
    FROM files 
    WHERE client='RetroBat' AND system='AcornAtom' AND map_name='.'
    GROUP BY filename 
    HAVING COUNT(*) > 1 
    ORDER BY cnt DESC 
    LIMIT 10
""")

rows = cur.fetchall()
if rows:
    print("Files with duplicate names:")
    for row in rows:
        print(f"  {row[0]}: {row[1]} copies")
else:
    print("No duplicate filename entries found")

# Check total file count
cur.execute("SELECT COUNT(*) FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='.'")
total = cur.fetchone()[0]
print(f"\nTotal files in database: {total}")

conn.close()
