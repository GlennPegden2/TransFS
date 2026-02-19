#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cursor = conn.cursor()

# Check all 4th & Inches files
cursor.execute("SELECT filename, size, extension, map_name FROM files WHERE filename LIKE ? AND system=?", ('%Inches%', 'Apple/AppleII'))
rows = cursor.fetchall()

print("Files in database with 'Inches' in filename:")
for filename, size, ext, map_name in rows:
    print(f"  {filename}")
    print(f"    Size: {size} bytes ({size/1024:.2f} KB)")
    print(f"    Extension: {ext}")
    print(f"    Map: {map_name}")
    print()

# Check filter thresholds
print(f"\nFilter thresholds:")
print(f"  FDs max_size: 908288 bytes (889.0 KB)")
print(f"  HDs min_size: 908289 bytes (889.0 KB)")
print(f"  4th & Inches size: 819273 bytes (800.07 KB)")
print(f"  Should be in: FDs (800.07 < 908.0)")

conn.close()
