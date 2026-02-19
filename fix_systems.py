#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Fix system names - convert "Apple/AppleII" to "Apple-II" format
cursor.execute("""UPDATE files SET system = 'Apple-II' WHERE system = 'Apple/AppleII'""")
print("Updated system names")

# Verify
cursor.execute("SELECT DISTINCT system FROM files WHERE system IS NOT NULL")
rows = cursor.fetchall()
print("System names after fix:")
for (system,) in rows:
    print(f"  {system}")

# Check FDs count
cursor.execute("SELECT COUNT(*) FROM files WHERE system='Apple-II' AND map_name='FDs'")
count = cursor.fetchone()[0]
print(f"\nFiles with system='Apple-II' and map_name='FDs': {count}")

conn.commit()
conn.close()
