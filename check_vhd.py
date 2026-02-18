#!/usr/bin/env python3
import struct

with open('/mnt/filestorefs/Native/Acorn/Atom/Software/VHD/hoglet67.vhd', 'rb') as f:
    # Read last 512 bytes (VHD footer)
    f.seek(-512, 2)
    footer = f.read(512)
    
    print("VHD Footer Analysis:")
    print("=" * 60)
    
    # VHD footer structure
    cookie = footer[0:8].decode('latin1')
    features = struct.unpack('>I', footer[8:12])[0]
    file_format_version = struct.unpack('>I', footer[12:16])[0]
    data_offset = struct.unpack('>Q', footer[16:24])[0]
    timestamp = struct.unpack('>I', footer[24:28])[0]
    creator_app = footer[28:32]
    creator_version = struct.unpack('>I', footer[32:36])[0]
    creator_os = footer[36:40]
    physical_size = struct.unpack('>Q', footer[40:48])[0]
    virtual_size = struct.unpack('>Q', footer[48:56])[0]
    
    # Disk geometry
    cylinder = struct.unpack('>H', footer[56:58])[0]
    heads = footer[58]
    sectors = footer[59]
    
    disk_type = struct.unpack('>I', footer[60:64])[0]
    checksum = struct.unpack('>I', footer[64:68])[0]
    uuid = footer[68:84]
    saved_state = footer[84]
    
    print(f"Cookie: {cookie}")
    print(f"Features: 0x{features:08x}")
    print(f"File Format Version: {file_format_version}")
    print(f"Data Offset: {data_offset}")
    print(f"Physical Size: {physical_size} bytes ({physical_size/1024/1024:.2f} MB)")
    print(f"Virtual Size: {virtual_size} bytes ({virtual_size/1024/1024:.2f} MB)")
    print(f"\nDisk Geometry:")
    print(f"  Cylinders: {cylinder}")
    print(f"  Heads: {heads}")
    print(f"  Sectors: {sectors}")
    print(f"\nDisk Type: {disk_type} (0=Fixed, 1=Dynamic, 2=Differencing)")
    print(f"Checksum: 0x{checksum:08x}")
    print(f"UUID: {uuid.hex()}")
    print(f"Saved State: {saved_state}")
    
    # Check geometry validity
    print(f"\nGeometry Validity Check:")
    max_capacity = cylinder * heads * sectors * 512
    print(f"  Max Capacity from Geometry: {max_capacity} bytes ({max_capacity/1024/1024:.2f} MB)")
    print(f"  Virtual Size from Footer: {virtual_size} bytes ({virtual_size/1024/1024:.2f} MB)")
    
    if cylinder > 65535 or heads > 255 or sectors > 63:
        print(f"  ❌ INVALID: Geometry exceeds CHS limits!")
    elif max_capacity != virtual_size:
        print(f"  ⚠️  MISMATCH: Geometry doesn't match virtual size")
    else:
        print(f"  ✅ OK: Geometry is valid")
