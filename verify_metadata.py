#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect('dbname=transfs user=transfs host=postgres')
cursor = conn.cursor()

# Check metadata table
cursor.execute("SELECT COUNT(*) FROM file_metadata")
count = cursor.fetchone()[0]
print(f"✓ file_metadata table has {count} rows")

# Check boot.vhd metadata
cursor.execute("""
    SELECT f.file_id, f.filename, f.map_name, fm.title, fm.media_type_id
    FROM files f 
    LEFT JOIN file_metadata fm ON f.file_id = fm.file_id 
    WHERE f.map_name = 'boot.vhd'
""")
rows = cursor.fetchall()
print(f"\n✓ boot.vhd file details ({len(rows)} rows):")
for file_id, filename, map_name, title, media_type_id in rows:
    print(f"  - {filename}: title={title}, media_type_id={media_type_id}")

cursor.close()
conn.close()
