#!/usr/bin/env python3
"""Check what files the query map returns"""
import sys
sys.path.insert(0, '/app')

from db.queries import query_files_by_system_and_query
from pathutils import get_system_identifier
from config import read_config

config = read_config()

# AcornAtom system info
system_info = {
    'name': 'AcornAtom',
    'local_base_path': 'Acorn/Atom'
}

# HDs query config
query_cfg = {
    'source_dir': 'Software',
    'extensions': ['VHD'],
    'supports_zip': False,
    'supports_zaparoo': True
}

system_id = get_system_identifier(system_info)
print(f"System ID: {system_id}")

files = query_files_by_system_and_query(system_id, query_cfg, system_info)
print(f"\nQuery found {len(files)} files:")
for f in files:
    print(f"  Filename: {f.get('filename')}")
    print(f"  Source Path: {f.get('source_path')}")
    print(f"  Virtual Path: {f.get('virtual_path')}")
    print()
