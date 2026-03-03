#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '/app')

from config import read_config
from pathutils import get_client

config = read_config()

# Find the RetroBat client and check its BIOS map configuration
client = get_client(config, ['RetroBat'])
if client:
    client_name = client.get('name')
    print(f'Found client: {client_name}')
    print(f'\nSystems count: {len(client.get("systems", []))}')
    
    # Look for BIOS-related maps
    for system in client.get('systems', []):
        system_name = system.get('name', 'unnamed')
        maps = system.get('maps', [])
        
        for map_entry in maps:
            map_name = list(map_entry.keys())[0]
            if 'bios' in map_name.lower():
                print(f'\nSystem: {system_name}')
                print(f'  Map: {map_name}')
                map_config = map_entry.get(map_name, {})
                if isinstance(map_config, dict):
                    source_dir = map_config.get('source_dir', 'N/A')
                    print(f'    source_dir: {source_dir}')
                    
                    # Check if this source_dir exists and what's in it
                    filestore = config.get('filestore', '/mnt/filestorefs')
                    local_base = system.get('local_base_path', '')
                    full_source_dir = os.path.join(filestore, 'Native', local_base, source_dir)
                    print(f'    full_path: {full_source_dir}')
                    
                    if os.path.exists(full_source_dir):
                        print(f'    exists: True')
                        entries = os.listdir(full_source_dir)
                        print(f'    contains {len(entries)} entries')
                        # Check for test files
                        test_files = [e for e in entries if 'transfs_write_test' in e.lower()]
                        if test_files:
                            print(f'    TEST FILES: {test_files[:3]}')
                    else:
                        print(f'    exists: False')
