import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check Apple-II files
cursor.execute('SELECT source_path, virtual_path, extension FROM files WHERE system="Apple-II" ORDER BY map_name LIMIT 5')
rows = cursor.fetchall()
print("Sample Apple-II files:")
for row in rows:
    print(f"  {row[0]} → {row[1]} ({row[2]})")

# Count by map
cursor.execute('SELECT map_name, COUNT(*) FROM files WHERE system="Apple-II" GROUP BY map_name')
rows = cursor.fetchall()
print("\nFiles by map:")
for map_name, count in rows:
    print(f"  {map_name}: {count}")

# Extensions found
cursor.execute('SELECT DISTINCT extension FROM files WHERE system="Apple-II" ORDER BY extension')
exts = [row[0] for row in cursor.fetchall()]
print(f"\nExtensions: {exts}")

# Check for 2MG and transformed files
cursor.execute('SELECT COUNT(*) FROM files WHERE system="Apple-II" AND extension IN ("2MG", "DO", "PO", "HDV")')
print(f"\nDisk image files (2MG/DO/PO/HDV): {cursor.fetchone()[0]}")

conn.close()
