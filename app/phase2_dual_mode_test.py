#!/usr/bin/env python3
"""
Phase 2.3: Test list_dynamic_map() Dual-Mode (YAML vs Database)

Tests that both YAML-driven and database-driven modes produce identical results
for Altair8800 ROMs.
"""

import sys
sys.path.insert(0, '/app')

from pathlib import Path
from config import get_system_config, read_config
from dirlisting import list_dynamic_map
from pathutils import get_system_info, find_software_archive_entry
from db.connection import init_database

print('=== PHASE 2.3: DUAL-MODE list_dynamic_map() TEST ===')
print()

try:
    # Initialize database
    print('Initializing database...')
    init_database('/mnt/filestorefs/.transfs_metadata.db')
    print('✓ Database initialized\n')
    
    # Load configuration
    print('Loading TransFS configuration...')
    config = read_config()
    print(f'✓ Config loaded')
    print(f'  Filestore: {config.get("filestore")}')
    print(f'  Mountpoint: {config.get("mountpoint")}\n')
    
    # Get system config for Altair8800
    print('Getting Altair8800 system configuration...')
    system_config = get_system_config('MiSTer', 'Altair8800', '/app/config')
    print(f'✓ Config retrieved')
    print(f'  System: {system_config.name}')
    print(f'  Layout: {system_config.download_layout}')
    print(f'  Filetypes: {system_config.maps}\n')
    
    # Get software archive entry
    print('Finding SoftwareArchives entry...')
    system = {'name': 'Altair8800', 'local_base_path': 'MITS/Altair8800'}
    sa_entry = None
    
    # Parse maps from system config
    if hasattr(system_config, 'maps'):
        for map_item in system_config.maps:
            if isinstance(map_item, dict):
                for key in map_item:
                    if '...SoftwareArchives...' in key:
                        sa_entry = map_item[key]
                        break
    
    if sa_entry:
        print(f'✓ Found SoftwareArchives entry')
        print(f'  Source dir: {sa_entry.get("source_dir")}')
        print(f'  Filetypes: {sa_entry.get("filetypes")}\n')
    else:
        print('⚠️ No SoftwareArchives entry found\n')
        sa_entry = {
            'source_dir': 'Software',
            'filetypes': {'ROMs': 'ROM, BIN:ROM, HEX:ROM'}
        }
    
    # Prepare for list_dynamic_map testing
    root_parts = ('transfs',)
    path_yaml = Path('/transfs/MiSTer/Altair8800/ROMs')
    map_name = 'ROMs'
    
    print('Testing list_dynamic_map()...\n')
    
    # Test 1: YAML-driven mode (db_mode=False)
    print('[Test 1] YAML-Driven Mode (db_mode=False)')
    try:
        entries_yaml = list_dynamic_map(
            config, 
            path_yaml, 
            root_parts, 
            system, 
            sa_entry, 
            map_name,
            db_mode=False
        )
        print(f'✓ YAML mode succeeded')
        print(f'  Entries returned: {len(entries_yaml)}')
        print(f'  Sample entries (first 5):')
        for entry in sorted(entries_yaml)[:5]:
            if hasattr(entry, 'name'):
                print(f'    {entry.name}')
            elif isinstance(entry, dict):
                print(f'    {entry.get("name", entry)}')
            else:
                print(f'    {entry}')
    except Exception as e:
        print(f'✗ YAML mode failed: {e}')
        entries_yaml = []
    
    print()
    
    # Test 2: Database-driven mode (db_mode=True)
    print('[Test 2] Database-Driven Mode (db_mode=True)')
    try:
        # Get extensions for Altair8800
        from db.queries import query_extensions_by_system
        extensions = query_extensions_by_system('MITS/Altair8800')
        print(f'  Extensions for Altair8800: {extensions}')
        
        entries_db = list_dynamic_map(
            config,
            path_yaml,
            root_parts,
            system,
            sa_entry,
            map_name,
            db_mode=True,
            extensions=extensions
        )
        print(f'✓ Database mode succeeded')
        print(f'  Entries returned: {len(entries_db)}')
        print(f'  Sample entries (first 5):')
        for entry in sorted(entries_db)[:5]:
            if hasattr(entry, 'name'):
                print(f'    {entry.name}')
            elif isinstance(entry, dict):
                print(f'    {entry.get("name", entry)}')
            else:
                print(f'    {entry}')
    except Exception as e:
        print(f'✗ Database mode failed: {e}')
        import traceback
        traceback.print_exc()
        entries_db = []
    
    print()
    print('=' * 70)
    print('COMPARISON')
    print('=' * 70)
    
    yaml_count = len(entries_yaml)
    db_count = len(entries_db)
    
    print(f'YAML mode entries:      {yaml_count}')
    print(f'Database mode entries:  {db_count}')
    print()
    
    if yaml_count == db_count == 0:
        print('⚠️ Both modes returned 0 entries')
        print('   Possible causes:')
        print('   - Altair8800 ROMs not in YAML config')
        print('   - Database query returned no results')
        print('   - Virtual path not accessible in sandbox')
    elif yaml_count > 0 and db_count > 0:
        # Convert to sets for comparison
        yaml_names = set()
        db_names = set()
        
        for entry in entries_yaml:
            if hasattr(entry, 'name'):
                yaml_names.add(entry.name)
            elif isinstance(entry, dict):
                yaml_names.add(entry.get('name', str(entry)))
            else:
                yaml_names.add(str(entry))
        
        for entry in entries_db:
            if hasattr(entry, 'name'):
                db_names.add(entry.name)
            elif isinstance(entry, dict):
                db_names.add(entry.get('name', str(entry)))
            else:
                db_names.add(str(entry))
        
        matching = yaml_names & db_names
        only_yaml = yaml_names - db_names
        only_db = db_names - yaml_names
        
        print(f'Matching entries:       {len(matching)}')
        print(f'Only in YAML:           {len(only_yaml)}')
        print(f'Only in Database:       {len(only_db)}')
        
        if len(matching) == yaml_count == db_count:
            print('\n✅ SUCCESS: Both modes returned identical results!')
        else:
            print('\n⚠️ Results differ between modes')
            if only_yaml:
                print(f'\nOnly in YAML mode (first 5):')
                for name in sorted(only_yaml)[:5]:
                    print(f'  {name}')
            if only_db:
                print(f'\nOnly in Database mode (first 5):')
                for name in sorted(only_db)[:5]:
                    print(f'  {name}')
    else:
        print(f'⚠️ One mode succeeded, other failed')
        print(f'   YAML entries:     {yaml_count}')
        print(f'   Database entries: {db_count}')
    
    print()
    print('=' * 70)
    print('TEST COMPLETE')
    print('=' * 70)

except Exception as e:
    print(f'❌ Test failed: {e}')
    import traceback
    traceback.print_exc()
