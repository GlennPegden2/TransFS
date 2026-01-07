#!/usr/bin/env python3
"""Test CDT directory read performance."""
import os
import time

path = "/mnt/transfs/Native/Amstrad/CPC/Software/CDT"

print(f"Testing scandir on {path}")
print(f"This directory has 3,537 CDT files")
print()

# Test 1: Just count entries
start = time.time()
try:
    count = len(list(os.scandir(path)))
    elapsed = time.time() - start
    print(f"✓ scandir (count only): {count} entries in {elapsed:.2f}s")
except Exception as e:
    print(f"✗ scandir failed: {e}")

# Test 2: Count + stat (what readdir does)
start = time.time()
try:
    entries = list(os.scandir(path))
    for entry in entries:
        entry.stat()
    elapsed = time.time() - start
    print(f"✓ scandir + stat all: {len(entries)} entries in {elapsed:.2f}s")
except Exception as e:
    print(f"✗ scandir+stat failed: {e}")

# Test 3: listdir + lstat (old method)
start = time.time()
try:
    names = os.listdir(path)
    for name in names:
        os.lstat(os.path.join(path, name))
    elapsed = time.time() - start
    print(f"✓ listdir + lstat (old): {len(names)} entries in {elapsed:.2f}s")
except Exception as e:
    print(f"✗ listdir+lstat failed: {e}")

print()
print("Comparison: scandir should be faster because stat info is cached from directory read")
