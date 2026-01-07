#!/usr/bin/env python3
"""Test CDT directory read performance on BOTH mounts."""
import os
import time

paths = [
    "/mnt/filestorefs/Native/Amstrad/CPC/Software/CDT",  # Direct bind mount
    "/mnt/transfs/Native/Amstrad/CPC/Software/CDT",       # Through FUSE
]

for path in paths:
    print(f"\n{'='*60}")
    print(f"Testing: {path}")
    print(f"{'='*60}")
    
    # Test: scandir
    start = time.time()
    try:
        with os.scandir(path) as entries:
            count = sum(1 for _ in entries)
        elapsed = time.time() - start
        print(f"scandir count: {count} entries in {elapsed:.2f}s ({count/elapsed:.0f} entries/sec)")
    except Exception as e:
        print(f"scandir FAILED: {e}")
        continue
    
    # If fast enough, try with stat
    if elapsed < 5:
        start = time.time()
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    entry.stat()
            elapsed = time.time() - start
            print(f"scandir+stat:  {count} entries in {elapsed:.2f}s ({count/elapsed:.0f} entries/sec)")
        except Exception as e:
            print(f"scandir+stat FAILED: {e}")
