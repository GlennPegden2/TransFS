#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from config import read_config
from dirlisting import parse_trans_path

config = read_config()
entries = parse_trans_path(config, '/mnt/transfs', '/mnt/transfs/MiSTer/Atari5200/ROMs/Prototype Games')
print(f'Found {len(entries)} entries')
print('First 10:', entries[:10] if len(entries) > 10 else entries)

# Check if Astro Chase is in the list
for e in entries:
    if 'Astro Chase' in e:
        print(f'Found: {e}')
