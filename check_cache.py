#!/usr/bin/env python3
import pickle

c = pickle.load(open('/mnt/filestorefs/.transfs_getattr_cache.pkl', 'rb'))

# Check for Apple-II entries
apple_keys = [k for k in c.keys() if 'Apple-II' in k and '.2mg' in k]
print(f"Total Apple-II .2mg files in cache: {len(apple_keys)}")

# Check total
all_keys = list(c.keys())
print(f"Total cache entries: {len(all_keys)}")

# Show what Apple-II entries exist
if apple_keys:
    print(f"\nSample Apple-II keys:")
    for key in apple_keys[:3]:
        print(f"  {key}")
else:
    print("\nNo Apple-II .2mg files in cache. Checking for other Apple-II entries...")
    apple_any = [k for k in c.keys() if 'Apple-II' in k]
    print(f"Total Apple-II entries (any): {len(apple_any)}")
    if apple_any:
        for key in apple_any[:5]:
            print(f"  {key}")
