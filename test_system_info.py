#!/usr/bin/env python3
"""Test script to debug get_system_info for AcornAtom."""
import sys
sys.path.insert(0, '/app')

from config import read_config
from pathutils import get_client, get_system_info

config = read_config()
rel_parts = ('RetroBat', 'ROMS', 'AcornAtom')
client = get_client(config, rel_parts)
print(f"Client: {client['name'] if client else None}")

if client:
    system_info = get_system_info(client, rel_parts)
    if system_info:
        print(f"System: {system_info['name']}")
        print(f"System at position: {rel_parts.index(system_info['name'])}")
    else:
        print("System not found")
        print(f"Available systems: {[s['name'] for s in client.get('systems', [])]}")
else:
    print("Client not found")
