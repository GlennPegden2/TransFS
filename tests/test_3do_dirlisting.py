#!/usr/bin/env python3
"""Quick test for 3DO path handling."""
import sys
import os
sys.path.insert(0, '/app')
os.chdir('/app')

from config import read_config
config = read_config()
from dirlisting import parse_trans_path

root = '/mnt/transfs'

e1 = list(parse_trans_path(config, root, '/mnt/transfs/RetroBat/ROMS/3DO'))
print('3DO maps:', e1)

e2 = list(parse_trans_path(config, root, '/mnt/transfs/RetroBat/ROMS/3DO/CDs'))
print('CDs count:', len(e2))
print('CDs first 3:', e2[:3])

# Check DB directly
from db.queries import query_files_by_client_system_and_map
files_lower = query_files_by_client_system_and_map('RetroBat', '3DO', 'CDs', ['bin','cue'], {})
print('DB CDs (bin/cue lowercase):', len(files_lower), files_lower[:1] if files_lower else [])

files_upper = query_files_by_client_system_and_map('RetroBat', '3DO', 'CDs', ['BIN','CUE'], {})
print('DB CDs (BIN/CUE uppercase):', len(files_upper))

files_none = query_files_by_client_system_and_map('RetroBat', '3DO', 'CDs', [], {})
print('DB CDs (no filter):', len(files_none), files_none[:1] if files_none else [])

# Check what extensions are configured in the map
from pathutils import find_map_entry, get_map_config, get_query_config
client = next((c for c in config.get('clients', []) if c['name'] == 'RetroBat'), None)
system = next((s for s in client.get('systems', []) if s['name'] == '3DO'), None) if client else None
if system:
    map_entry = find_map_entry(system, 'CDs')
    map_config = get_map_config(map_entry) if map_entry else None
    query_cfg = get_query_config(map_config) if map_config else None
    print('CDs map extensions config:', query_cfg.get('extensions') if query_cfg else 'no query cfg')
