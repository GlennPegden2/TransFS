#!/usr/bin/env python3
import os
import hashlib

path = '/mnt/transfs/MiSTer/AcornAtom/boot.vhd'

for attempt in range(3):
    print(f"\nAttempt {attempt + 1}:")
    try:
        with open(path, 'rb') as f:
            md5 = hashlib.md5()
            total = 0
            while True:
                chunk = f.read(1024*1024)
                if not chunk:
                    break
                md5.update(chunk)
                total += len(chunk)
            
            print(f"  Size: {total} bytes")
            print(f"  MD5: {md5.hexdigest()}")
            
    except Exception as e:
        print(f"  Error: {e}")
