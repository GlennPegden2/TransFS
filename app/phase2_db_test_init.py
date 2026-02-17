#!/usr/bin/env python3
"""Phase 2.2: Database Query Test - WITH INITIALIZATION"""

import sys
sys.path.insert(0, '/app')

print('=== PHASE 2.2: DATABASE QUERY TEST (WITH INIT) ===')
print()

try:
    # First initialize the database
    from db.connection import init_database
    print('Initializing database...')
    init_database('/mnt/filestorefs/.transfs_metadata.db')
    print('✓ Database initialized')
    print()
    
    # Now import queries
    from db.queries import (
        query_files_by_system_and_extensions,
        query_all_systems,
        query_extensions_by_system,
        query_system_statistics
    )
    
    # Check if system is in database
    print('Checking for MITS/Altair8800...')
    all_systems = query_all_systems()
    print(f'Total systems: {len(all_systems)}')
    
    if 'MITS/Altair8800' in all_systems:
        print('✓ MITS/Altair8800 found')
    else:
        print('✗ NOT found. Available:', list(all_systems)[:3])
    
    print()
    print('Extensions for MITS/Altair8800:')
    exts = query_extensions_by_system('MITS/Altair8800')
    print(f'  {exts}')
    
    print()
    print('Query files (limit 10):')
    files = query_files_by_system_and_extensions('MITS/Altair8800', exts, limit=10)
    print(f'  Found: {len(files)} files')
    if files:
        for f in files[:3]:
            fname = f.get('filename', 'N/A')
            vpath = f.get('virtual_path', 'N/A')
            print(f'    {fname}')
            print(f'      -> {vpath}')
    
    print()
    print('System statistics:')
    stats = query_system_statistics('MITS/Altair8800')
    if stats:
        print(f'  File count: {stats.get("file_count")}')
        print(f'  Total size: {stats.get("total_size_bytes")} bytes')
        print(f'  Extensions: {stats.get("extension_count")}')
    
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
