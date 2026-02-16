import struct
import sys

path = "/mnt/filestorefs/Native/Apple/AppleII/Software/2MG/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg"
with open(path, "rb") as f:
    header = f.read(64)
    print("Raw header (first 40 bytes):")
    print(" ".join(f"{b:02x}" for b in header[:40]))
    print()
    
    # Correct parsing according to 2MG spec
    creator = struct.unpack("<I", header[4:8])[0]
    header_size = struct.unpack("<H", header[8:10])[0]
    version = struct.unpack("<H", header[12:14])[0]
    format_byte = struct.unpack("<I", header[16:20])[0]
    blocks = struct.unpack("<I", header[24:28])[0]
    data_offset = struct.unpack("<I", header[28:32])[0]
    data_length = struct.unpack("<I", header[32:36])[0]
    
    print("CORRECT PARSING:")
    print(f"  Creator: 0x{creator:08x}")
    print(f"  Header size: {header_size}")
    print(f"  Version: {version}")
    print(f"  Format: {format_byte} (0=DOS, 1=ProDOS)")
    print(f"  Blocks: {blocks}")
    print(f"  Data offset: {data_offset}")
    print(f"  Data length: {data_length}")
    f.seek(0, 2)
    print(f"  File size: {f.tell()}")
    print()
    
    # What our code is reading
    print("WHAT OUR CODE SEES (struct.unpack('<16I', header)):")
    vals = struct.unpack("<16I", header)
    print(f"  vals[2] (used as header_size): {vals[2]}")
    print(f"  vals[4] (used as format): {vals[4]}")
    print(f"  vals[6] (used as data_offset): {vals[6]}")
    print(f"  vals[7] (used as data_length): {vals[7]}")
    print()
    
    # The issue: vals includes the magic as first uint32
    print("ISSUE: vals[0] contains the magic '2IMG':")
    print(f"  vals[0]: 0x{vals[0]:08x} = {struct.pack('<I', vals[0])}")
    print(f"  So vals is offset by 1 from the actual fields!")
    print()
    
    # NEW: Test our fixed parsing
    print("FIXED PARSING (reading correct offsets):")
    hdr_size = struct.unpack('<H', header[8:10])[0]
    data_off = struct.unpack('<I', header[28:32])[0]
    data_len = struct.unpack('<I', header[32:36])[0]
    print(f"  Header size (offset 8): {hdr_size}")
    print(f"  Data offset (offset 28): {data_off} (0 = use header size)")
    print(f"  Data length (offset 32): {data_len} (0 = calculate from file)")
    print()
    print(f"  Effective data offset: {data_off if data_off > 0 else hdr_size}")
    print(f"  Effective data length: {data_len if data_len > 0 else (819264 - (data_off if data_off > 0 else hdr_size))}")

