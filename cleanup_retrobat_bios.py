#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Delete all old BIOS entries for RetroBat/AcornAtom
print("Deleting old RetroBat BIOS entries (map_name='.')")
cur.execute("DELETE FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='.'")
deleted = cur.rowcount
print(f"Deleted {deleted} records")

# Also delete the atom.zip entry if it exists with old map name
print("\nDeleting old atom.zip entry if exists...")
cur.execute("DELETE FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='atom.zip'")
deleted_zip = cur.rowcount
print(f"Deleted {deleted_zip} zip records")

conn.commit()

print("\n=== RetroBat/AcornAtom files remaining ===")
cur.execute("SELECT map_name, COUNT(*) FROM files WHERE client='RetroBat' AND system='AcornAtom' GROUP BY map_name ORDER BY map_name")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} files")

conn.close()
print("\nDatabase cleanup complete! Ready for resync.")
