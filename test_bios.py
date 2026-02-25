#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config
from dirlisting import parse_trans_path

config = read_config()

path = "/mnt/transfs/RetroBat/BIOS/AcornAtom"
entries = parse_trans_path(config, "/mnt/transfs", path)
print(f"parse_trans_path({path}):")
print(f"  Result: {entries}")
