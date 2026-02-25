#!/usr/bin/env python3
"""Test MAME pack installation endpoint"""

import requests
import json

# API endpoint
url = "http://localhost:8000/api/clients/RetroBat/systems/AcornAtom/install-packs"

# Test request
payload = {
    "pack_ids": ["mame-atom-cassettes"]  # Adjust to actual pack ID
}

print(f"Testing MAME pack installation...")
print(f"URL: {url}")
print(f"Payload: {json.dumps(payload, indent=2)}\n")

try:
    # First, let's check what packs are available
    print("=" * 60)
    print("STEP 1: Getting available packs for AcornAtom...")
    print("=" * 60)
    
    packs_url = "http://localhost:8000/api/clients/RetroBat/systems/AcornAtom"
    resp = requests.get(packs_url, timeout=10)
    resp.raise_for_status()
    
    data = resp.json()
    print(f"System: {data.get('system', {}).get('name')}")
    
    packs = data.get('packs', [])
    print(f"\nFound {len(packs)} pack(s):")
    for pack in packs:
        print(f"  - {pack['id']}: {pack['name']}")
        if pack.get('sources'):
            print(f"    Sources: {pack['sources']}")
    
    if not packs:
        print("No packs found!")
        exit(1)
    
    # Use first pack
    pack_id = packs[0]['id']
    payload['pack_ids'] = [pack_id]
    
    print(f"\n" + "=" * 60)
    print(f"STEP 2: Installing pack '{pack_id}'...")
    print("=" * 60 + "\n")
    
    # Now try to install
    resp = requests.post(url.replace("install-packs", "install-packs"), 
                        json={"pack_ids": [pack_id]},
                        stream=True,
                        timeout=300)
    
    print(f"Status Code: {resp.status_code}\n")
    
    # Stream the response
    for line in resp.iter_lines():
        if line:
            print(line.decode() if isinstance(line, bytes) else line)
    
except requests.exceptions.RequestException as e:
    print(f"ERROR: {e}")
except Exception as e:
    print(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
