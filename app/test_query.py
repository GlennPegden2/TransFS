#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from db.queries import query_files_by_client_system_and_map

# Test the query
files = query_files_by_client_system_and_map('MiSTer', 'Apple-II', 'FDs', ['DSK', 'DO', 'PO'])
print(f"Query returned {len(files)} files")
if files:
    for f in files[:3]:
        print(f"  {f}")
