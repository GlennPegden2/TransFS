#!/usr/bin/env python3
import os
import sys

# Read directly from FUSE mount
boot_vhd_path = '/mnt/transfs/MiSTer/AcornAtom/boot.vhd'

try:
    print(f"Reading {boot_vhd_path}...")
    with open(boot_vhd_path, 'rb') as f:
        chunk_size = 131072
        total = 0
        chunk_num = 0
        
        while True:
            chunk_num += 1
            data = f.read(chunk_size)
            if not data:
                print(f"EOF reached after {chunk_num-1} chunks")
                break
            total += len(data)
            print(f"Chunk {chunk_num}: {len(data)} bytes (total: {total})")
            
            if chunk_num > 10:  # Safety limit
                print("Stopping after 10 chunks for testing")
                break
    
    print(f"Total bytes read: {total}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
