#!/usr/bin/env python3
"""Test reading VHD file through different paths"""
import os
import hashlib

paths = [
    '/mnt/filestorefs/Native/Acorn/Atom/Software/VHD/hoglet67.vhd',  # Direct filesystem
    '/mnt/transfs/MiSTer/AcornAtom/boot.vhd',  # File map
    '/mnt/transfs/MiSTer/AcornAtom/HDs/hoglet67.vhd',  # Query map
]

for path in paths:
    try:
        print(f"\nTesting: {path}")
        if not os.path.exists(path):
            print(f"  ❌ Does not exist")
            continue
            
        with open(path, 'rb') as f:
            # Read first and last chunk
            f.seek(0)
            first_chunk = f.read(512)
            
            f.seek(-512, 2)
            last_chunk = f.read(512)
            
            # Calculate full file hash
            f.seek(0)
            md5 = hashlib.md5()
            total = 0
            while True:
                chunk = f.read(1024*1024)
                if not chunk:
                    break
                md5.update(chunk)
                total += len(chunk)
            
            print(f"  ✅ Readable: {total} bytes")
            print(f"     MD5: {md5.hexdigest()}")
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
