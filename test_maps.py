#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config

config = read_config()

client = next((c for c in config.get('clients', []) if c['name'] == 'MiSTer'), None)
apple_ii = next((s for s in client.get('systems', []) if s['name'] == 'Apple-II'), None)

print(f"Maps in Apple-II:")
for i, map_item in enumerate(apple_ii.get('maps', [])):
    print(f"\nMap {i}:")
    for key, val in map_item.items():
        if isinstance(val, list) and len(val) > 5:
            print(f"  {key}: [... {len(val)} items ...]")
        else:
            print(f"  {key}: {val}")
