#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect(
    host='postgres',
    database='transfs',
    user='transfs',
    password='transfs_pass'
)
cur = conn.cursor()

# Delete the 6 files with incorrect virtual paths (have /./ in them)
print("Deleting 6 files with incorrect virtual paths...")
cur.execute("DELETE FROM files WHERE client='RetroBat' AND system='AcornAtom' AND map_name='.' AND virtual_path LIKE '%/./%'")
deleted = cur.rowcount
print(f"Deleted {deleted} records")

# Update the 3883 files with map_name='bios' to map_name='.'
print("\nUpdating map_name from 'bios' to '.' for remaining files...")
cur.execute("UPDATE files SET map_name='.' WHERE client='RetroBat' AND system='AcornAtom' AND map_name='bios'")
updated = cur.rowcount
print(f"Updated {updated} records")

# Also update the file-based atom.zip entry
print("\nUpdating atom.zip map entry...")
cur.execute("UPDATE files SET map_name='atom.zip' WHERE client='RetroBat' AND system='AcornAtom' AND map_name='bios/atom.zip'")
updated_zip = cur.rowcount
print(f"Updated {updated_zip} zip record")

conn.commit()

# Verify the changes
print("\n=== Final state ===")
cur.execute("SELECT map_name, COUNT(*) FROM files WHERE client='RetroBat' AND system='AcornAtom' GROUP BY map_name ORDER BY map_name")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} files")

conn.close()
print("\nDatabase cleanup complete!")
