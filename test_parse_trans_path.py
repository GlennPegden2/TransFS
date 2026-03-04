#!/usr/bin/env python3
"""Test what parse_trans_path returns for /RetroBat/ROMS/AcornAtom."""
import sys
sys.path.insert(0, '/app')

from config import read_config
from dirlisting import parse_trans_path

config = read_config()
path = '/mnt/transfs/RetroBat/ROMS/AcornAtom'
entries = list(parse_trans_path(config, '/mnt/transfs', path))
print(f"parse_trans_path returned for {path}:")
print(f"Entries: {sorted(entries)}")
