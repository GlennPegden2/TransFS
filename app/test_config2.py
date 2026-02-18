#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config
import json

config = read_config()

# Check MiSTer client
client = next((c for c in config.get('clients', []) if c['name'] == 'MiSTer'), None)
if client:
    apple_ii = next((s for s in client.get('systems', []) if s['name'] == 'Apple-II'), None)
    if apple_ii:
        print(f"Apple-II keys: {list(apple_ii.keys())}")
        for key in apple_ii.keys():
            val = apple_ii[key]
            if isinstance(val, dict):
                print(f"{key}: {val}")
            elif isinstance(val, list):
                print(f"{key}: [... {len(val)} items ...]")
            else:
                print(f"{key}: {val}")
