#!/usr/bin/env python3
"""Check what transformations are being applied"""
import sys
sys.path.insert(0, '/app')

from sourcepath import get_source_path
from config import read_config
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config = read_config()
root = '/mnt/transfs'

# Check the file map
paths = [
    '/mnt/transfs/MiSTer/AcornAtom/boot.vhd',
    '/mnt/transfs/MiSTer/AcornAtom/HDs/hoglet67.vhd',
]

for path in paths:
    print(f"\nChecking: {path}")
    result = get_source_path(logger, config, root, path)
    print(f"Result type: {type(result)}")
    if isinstance(result, dict):
        print(f"  Path: {result.get('path')}")
        print(f"  Transform: {result.get('transform_pipeline')}")
    else:
        print(f"  Result: {result}")
