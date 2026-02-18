#!/usr/bin/env python3
import os
import sys
import hashlib

boot_vhd_path = '/mnt/transfs/MiSTer/AcornAtom/boot.vhd'

try:
    print(f"Reading full {boot_vhd_path}...")
    md5 = hashlib.md5()
    total = 0
    chunk_num = 0
    
    with open(boot_vhd_path, 'rb') as f:
        chunk_size = 131072
        
        while True:
            chunk_num += 1
            data = f.read(chunk_size)
            if not data:
                print(f"\nEOF reached at {total} bytes")
                break
            total += len(data)
            md5.update(data)
            
            if chunk_num % 100 == 0:
                print(f"  Chunk {chunk_num}: {total} bytes ({total/1024/1024:.1f} MB)")
    
    print(f"\nComplete read: {total} bytes ({total/1024/1024:.1f} MB)")
    print(f"MD5: {md5.hexdigest()}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
