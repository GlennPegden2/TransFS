#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from dirlisting import get_cached_getattr, _load_getattr_cache, _getattr_cache

# Manually load cache
_load_getattr_cache()

# Check a file
test_path = '/mnt/transfs/MiSTer/Apple-II/Disks/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg'
result = get_cached_getattr(test_path, '/mnt/filestorefs/Native/Apple/AppleII/Software/DSK')

print(f"Cache size after load: {len(_getattr_cache)}")
print(f"Test path in cache: {test_path in _getattr_cache}")
print(f"get_cached_getattr result: {result is not None}")

if not result:
    # Try showing what keys ARE in cache
    apple_keys = [k for k in _getattr_cache.keys() if 'Apple-II' in k][:3]
    print(f"\nApple-II keys in _getattr_cache: {len([k for k in _getattr_cache.keys() if 'Apple-II' in k])}")
    if apple_keys:
        print(f"Sample key: {apple_keys[0]}")
