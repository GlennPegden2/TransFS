#!/usr/bin/env python3
"""Quick test script to verify client config loading."""
import sys
sys.path.insert(0, '/app')

from app.config import read_config

config = read_config()
clients = config.get("clients", [])

print(f"✓ Loaded {len(clients)} clients:")
for client in clients:
    name = client.get("name", "UNNAMED")
    systems = client.get("systems", [])
    print(f"  - {name}: {len(systems)} systems")

print("\nSample system from MiSTer:")
mister = next((c for c in clients if c.get("name") == "MiSTer"), None)
if mister and mister.get("systems"):
    first_system = mister["systems"][0]
    print(f"  Name: {first_system.get('name')}")
    print(f"  Manufacturer: {first_system.get('manufacturer')}")
    print(f"  Maps: {len(first_system.get('maps', []))}")
