#!/usr/bin/env python3
"""Quick test to verify 3DO path handling in dirlisting."""
import sys
import os
sys.path.insert(0, '/app')

import yaml
config = yaml.safe_load(open('/app/transfs.yaml'))
from dirlisting import parse_trans_path

root = '/mnt/transfs'

# Test 1: listing under ROMS/3DO
path = '/mnt/transfs/RetroBat/ROMS/3DO'
entries = list(parse_trans_path(config, root, path))
print(f'ROMS/3DO entries: {entries}')

# Test 2: listing under ROMS/3DO/CDs
path2 = '/mnt/transfs/RetroBat/ROMS/3DO/CDs'
entries2 = list(parse_trans_path(config, root, path2))
print(f'ROMS/3DO/CDs entry count: {len(entries2)}')
print(f'ROMS/3DO/CDs entries (first 3): {entries2[:3]}')

# Test 3: check BIOS map
path3 = '/mnt/transfs/RetroBat/ROMS/3DO/BIOS'
entries3 = list(parse_trans_path(config, root, path3))
print(f'ROMS/3DO/BIOS entry count: {len(entries3)}')
print(f'ROMS/3DO/BIOS entries (first 3): {entries3[:3]}')

# Test 4: Check bios path (where flatten map goes)
path4 = '/mnt/transfs/RetroBat/bios'
entries4 = list(parse_trans_path(config, root, path4))
print(f'bios entries (first 5): {entries4[:5]}')
print(f'bios - any 3DO BIOS files (panafz)? {any("pana" in e.lower() or "3do" in e.lower() for e in entries4)}')
