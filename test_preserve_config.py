#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config

cfg = read_config()
print("=" * 60)
print("Testing preserve_structure configuration loading")
print("=" * 60)

for client in cfg.get('clients', []):
    if client.get('name') == 'RetroBat':
        for system in client.get('systems', []):
            if system.get('name') == 'AcornAtom':
                for map_entry in system.get('maps', []):
                    if 'FDs' in map_entry:
                        fds_map = map_entry['FDs']
                        query_cfg = fds_map.get('query', {})
                        preserve = query_cfg.get('preserve_structure', 'NOT SET')
                        print(f"\nFDs map configuration:")
                        print(f"  preserve_structure = {preserve}")
                        print(f"  source_dir = {query_cfg.get('source_dir')}")
                        print(f"  extensions = {query_cfg.get('extensions')}")
                        print(f"\nFull query config:")
                        for key, val in query_cfg.items():
                            print(f"  {key} = {val}")
