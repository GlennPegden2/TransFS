#!/usr/bin/env python3
from pathlib import Path

path_str = '/mnt/transfs/MiSTer/Atari5200/ROMs/Prototype Games'
root_parts = ("/", "mnt", "transfs")

path = Path(path_str)
print(f"path.parts = {path.parts}")
print(f"len(root_parts) = {len(root_parts)}")
print(f"len(root_parts) + 3 = {len(root_parts) + 3}")

subpath = path.parts[len(root_parts) + 3:]
print(f"subpath = {subpath}")
print(f"subpath type = {type(subpath)}")

# What would path_components be?
path_components = subpath if subpath else []
print(f"path_components = {path_components}")
