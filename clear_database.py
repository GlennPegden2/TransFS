#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Delete ALL files from database
print("Clearing entire database...")
cur.execute("DELETE FROM file_metadata")
cur.execute("DELETE FROM files")
cur.execute("VACUUM ANALYZE files")

conn.commit()

# Verify it's empty
cur.execute("SELECT COUNT(*) FROM files")
count = cur.fetchone()[0]
print(f"Database cleared. Total files remaining: {count}")

conn.close()
