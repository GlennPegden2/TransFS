#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from dirlisting import _get_subdirectories_from_db

mount_path = "/mnt/transfs"
test_paths = [
    "RetroBat",
    "RetroBat/ROMS",
    "RetroBat/ROMS/AcornAtom",
    "RetroBat/BIOS",
    "RetroBat/BIOS/AcornAtom"
]

for path in test_paths:
    result = _get_subdirectories_from_db(mount_path, path)
    print(f"{path}: {result}")
