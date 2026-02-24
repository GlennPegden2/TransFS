#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config
from dirlisting import parse_trans_path

config = read_config()
maps = list(parse_trans_path(config, '/mnt/transfs', '/mnt/transfs/RetroBat/AcornAtom'))
print(f"RetroBat/AcornAtom maps from config: {maps}")
