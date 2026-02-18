#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from config import read_config

config = read_config()

# Check MiSTer client
client = next((c for c in config.get('clients', []) if c['name'] == 'MiSTer'), None)
if client:
    print(f"MiSTer client found")
    apple_ii = next((s for s in client.get('systems', []) if s['name'] == 'Apple-II'), None)
    if apple_ii:
        print(f"Apple-II system found")
        print(f"Maps in Apple-II:")
        for key, value in apple_ii.items():
            if isinstance(value, dict) and 'extensions' in value:
                print(f"  {key}: {value.get('extensions', [])}")
