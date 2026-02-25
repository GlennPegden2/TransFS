#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from pathlib import Path
from config import read_config

# Load config
config = read_config()

# Test the path "/mnt/transfs/RetroBat/ROMS/AcornAtom" - this is lev==2 in the old fixed structure
# But with categories, it's deeper. Let's simulate what parse_trans_path would do

print("Testing directory listing at different levels:\n")

test_paths = [
    "/mnt/transfs/RetroBat",
    "/mnt/transfs/RetroBat/ROMS",
    "/mnt/transfs/RetroBat/ROMS/AcornAtom",
    "/mnt/transfs/RetroBat/BIOS",
    "/mnt/transfs/RetroBat/BIOS/AcornAtom",
]

from dirlisting import parse_trans_path

for path in test_paths:
    entries = parse_trans_path(config, "/mnt/transfs", path)
    print(f"{path}: {entries}")
