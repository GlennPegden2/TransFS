#!/usr/bin/env python3
"""Debug script to test if exclusion logic works."""
import sys
import os
from pathlib import Path

# Simulate the exclusion logic from conftest.py
root_path = Path("/mnt/transfs/Native/Amstrad/CPC")
exclude_paths = ['Software/CDT', 'Software/Collections']

print(f"Root path: {root_path}")
print(f"Exclude patterns: {exclude_paths}")
print()

# Simulate walking the directory structure
for dirpath, dirnames, filenames in os.walk(root_path):
    rel_dir = os.path.relpath(dirpath, root_path)
    if rel_dir == ".":
        rel_dir = ""
    
    print(f"Walking: {rel_dir or '(root)'}")
    print(f"  Subdirs BEFORE filter: {dirnames[:5]}...")  # Show first 5
    
    # Apply the exclusion filter
    if dirnames and exclude_paths:
        original_dirnames = list(dirnames)
        dirnames[:] = [
            d for d in dirnames 
            if not any(
                (os.path.join(rel_dir, d) if rel_dir else d).startswith(excl) or
                (os.path.join(rel_dir, d) if rel_dir else d) == excl
                for excl in exclude_paths
            )
        ]
        excluded = set(original_dirnames) - set(dirnames)
        if excluded:
            print(f"  ✓ EXCLUDED: {excluded}")
    
    print(f"  Subdirs AFTER filter: {dirnames[:5]}...")  # Show first 5
    print()
    
    # Stop after first level to avoid huge output
    if rel_dir == "Software":
        break
