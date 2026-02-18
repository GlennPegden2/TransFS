#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from pathlib import Path
from config import read_config

config = read_config()

# Test _extract_map_info logic
mount_path = "/mnt/transfs"
path = "/mnt/transfs/MiSTer/Apple-II/FDs"

rel_parts = Path(path).parts[len(Path(mount_path).parts):]
print(f"path: {path}")
print(f"mount_path: {mount_path}")
print(f"rel_parts: {rel_parts}")
print(f"len(rel_parts): {len(rel_parts)}")

if len(rel_parts) >= 3:
    client_name = rel_parts[0]
    system_name = rel_parts[1]
    map_name = rel_parts[2]
    print(f"\nExtracted: client={client_name}, system={system_name}, map={map_name}")
    
    # Check if client exists
    client_config = next((c for c in config.get('clients', []) if c['name'] == client_name), None)
    print(f"Client found: {client_config is not None}")
    if client_config:
        print(f"  name: {client_config['name']}")
        print(f"  default_target_path: {client_config['default_target_path']}")
        
        # Check system
        system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
        print(f"System found: {system_info is not None}")
        if system_info:
            print(f"  name: {system_info['name']}")
            print(f"  maps: {[m['name'] for m in system_info.get('maps', [])]}")
