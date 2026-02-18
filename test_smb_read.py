#!/usr/bin/env python3
"""Test SMB read with large file chunks"""

import smbclient
import sys

try:
    # Connect to SMB share and read large chunks
    print("Attempting to read boot.vhd via SMB...")
    with smbclient.SMBFile('//172.18.0.2/TransFS/MiSTer/AcornAtom/boot.vhd', mode='rb') as f:
        # Read in 131KB chunks to trigger the retry logic
        chunk_size = 131072
        total = 0
        chunk_num = 0
        
        while True:
            chunk_num += 1
            data = f.read(chunk_size)
            if not data:
                print(f"\nEOF reached after {chunk_num-1} chunks")
                break
            total += len(data)
            print(f"Chunk {chunk_num}: {len(data)} bytes (total: {total})")
            
            if chunk_num > 10:  # Safety limit
                print("Stopping after 10 chunks for testing")
                break
                
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\nTotal bytes read: {total}")
