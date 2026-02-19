#!/usr/bin/env python3
"""Test that the database correctly returns files for Apple-II FDs."""
import sys
sys.path.insert(0, '/app')

from app.db.queries import query_files_by_client_system_and_map

# Query for Apple-II FDs files
files = query_files_by_client_system_and_map(
    client='MiSTer',
    system='Apple-II',
    map_name='FDs',
    allowed_extensions=['DSK', 'DO', 'PO', '2MG']
)

print(f"Found {len(files)} files in MiSTer/Apple-II/FDs with allowed extensions")

# Look for 4th & Inches files
fourth_inches = [f for f in files if '4th' in f['filename'].lower()]
print(f"\n4th & Inches files found: {len(fourth_inches)}")
for f in fourth_inches:
    print(f"  {f['filename']}: {f['size']} bytes")

# Summary
print(f"\nDatabase query successful: {len(files)} total files")
print(f"Expected: ~494 files (DSK, DO, PO, 2MG files ≤ 908288 bytes)")
