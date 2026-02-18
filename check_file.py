import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Query for the 4th & Inches file
cursor.execute("""
    SELECT filename, size, extension, map_name FROM files 
    WHERE filename LIKE '%4th%' AND system='Apple/AppleII'
""")

rows = cursor.fetchall()
for row in rows:
    filename, size, ext, map_name = row
    print(f"File: {filename}")
    print(f"  Size: {size} bytes ({size/1024:.2f} KB)")
    print(f"  Extension: {ext}")
    print(f"  Map: {map_name}")
    print()

conn.close()
