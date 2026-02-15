#!/usr/bin/env python3
import pickle

cache = pickle.load(open('/mnt/filestorefs/.transfs_getattr_cache.pkl', 'rb'))
apple = [k for k in cache.keys() if 'Apple-II' in k and '.2mg' in k]
print(f"Total Apple-II .2mg in cache: {len(apple)}")

if apple:
    # Show the EXACT format of a cached key
    sample_key = apple[0]
    print(f"\nSample cached key:")
    print(f"  repr: {repr(sample_key)}")
    print(f"  type: {type(sample_key)}")
    print(f"  len: {len(sample_key)}")
    
    # Check if special characters like parentheses are handled correctly
    print(f"\nCharacter check:")
    for i, char in enumerate(sample_key):
        if not char.isascii() or char in "()[]":
            print(f"  Pos {i}: {repr(char)}")

# Now check what the EXPECTED path would be
print(f"\nExpected lookup path:")
print(f"  /mnt/transfs/MiSTer/Apple-II/Disks/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg")

# Check if this exact path is in the cache
test_path = "/mnt/transfs/MiSTer/Apple-II/Disks/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg"
in_cache = test_path in cache
print(f"\nTest path in cache: {in_cache}")

if not in_cache:
    # Try to find what variation might be in the cache
    print(f"\nSearching for similar keys...")
    for key in apple[:3]:
        if "4th & Inches" in key or "4th" in key:
            print(f"  Found: {repr(key)}")
