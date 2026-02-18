#!/usr/bin/env python3
import os
import sys

# Try to open a file from the HDs query map
hds_path = '/mnt/transfs/MiSTer/AcornAtom/HDs'

try:
    print(f"Listing {hds_path}...")
    files = os.listdir(hds_path)
    print(f"Found {len(files)} files:")
    for f in files[:5]:
        print(f"  - {f}")
    
    if files:
        # Try to access the first VHD file
        test_file = [f for f in files if f.lower().endswith('.vhd')][0] if any(f.lower().endswith('.vhd') for f in files) else files[0]
        full_path = os.path.join(hds_path, test_file)
        
        print(f"\nTrying to access: {full_path}")
        with open(full_path, 'rb') as f:
            header = f.read(512)
            print(f"Successfully read {len(header)} bytes from {test_file}")
            print(f"File accessible via query map!")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
