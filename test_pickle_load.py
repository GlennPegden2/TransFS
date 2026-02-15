#!/usr/bin/env python3
import pickle

try:
    with open('/mnt/filestorefs/.transfs_getattr_cache.pkl', 'rb') as f:
        cache = pickle.load(f)
    print(f"Pickle load successful: {len(cache)} entries")
    
    # Check for Apple-II entries
    apple = [k for k in cache.keys() if 'Apple-II' in k]
    print(f"Apple-II entries: {len(apple)}")
    
except Exception as e:
    print(f"Error loading pickle: {e}")
