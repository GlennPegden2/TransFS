import sqlite3
conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()
cursor.execute('SELECT filename, size, extension, map_name FROM files WHERE system="Apple-II" AND map_name="HDs" AND (extension="2mg" OR extension="2MG")')
print("Large 2MG files in HDs:")
for filename, size, ext, map_name in cursor.fetchall():
    print(f"  {filename}: {size} bytes (ext={ext})")
conn.close()
