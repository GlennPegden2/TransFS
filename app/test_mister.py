#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config
from dirlisting import parse_trans_path

config = read_config()
root = "/mnt/transfs"

# Test MiSTer/AcornAtom
path = "/mnt/transfs/MiSTer/AcornAtom"
maps = list(parse_trans_path(config, root, path))
print(f"MiSTer AcornAtom maps: {maps}")

# Test RetroBat/AcornAtom  
path = "/mnt/transfs/RetroBat/AcornAtom"
maps = list(parse_trans_path(config, root, path))
print(f"RetroBat AcornAtom maps: {maps}")
