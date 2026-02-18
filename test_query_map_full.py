#!/usr/bin/env python3
import os
import hashlib

# Read the query map file completely
query_map_file = '/mnt/transfs/MiSTer/AcornAtom/HDs/hoglet67.vhd'

try:
    print(f"Reading {query_map_file}...")
    md5 = hashlib.md5()
    total = 0
    
    with open(query_map_file, 'rb') as f:
        while True:
            chunk = f.read(131072)
            if not chunk:
                break
            total += len(chunk)
            md5.update(chunk)
            if total % 10485760 == 0:  # Every 10MB
                print(f"  Read {total} bytes ({total/1024/1024:.1f} MB)")
    
    print(f"\nComplete read via query map:")
    print(f"  Total: {total} bytes ({total/1024/1024:.1f} MB)")
    print(f"  MD5: {md5.hexdigest()}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
