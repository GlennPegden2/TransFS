#!/usr/bin/env python3
"""Validate Apple II boot sector from 2MG files."""

import sys
import struct

def validate_6502_boot_sector(data: bytes, label: str = ""):
    """Check if boot sector contains valid-looking 6502 code."""
    print(f"\n{'='*60}")
    print(f"Validating: {label}")
    print(f"{'='*60}")
    
    # Check for all zeros (bad)
    if data[:256] == b'\x00' * 256:
        print("❌ ERROR: First sector is all zeros!")
        return False
    
    # Check first few bytes for common 6502 opcodes
    first_byte = data[0]
    print(f"First byte: 0x{first_byte:02x} ({first_byte})")
    
    # Common valid opcodes at start of Apple II boot sectors:
    # 0x01 = ORA (ind,X)
    # 0x4C = JMP absolute
    # 0xA9 = LDA immediate
    # 0xA2 = LDX immediate
    # 0x20 = JSR
    # 0x78 = SEI
    # 0xD8 = CLD
    valid_first_opcodes = [0x01, 0x4C, 0xA9, 0xA2, 0x20, 0x78, 0xD8, 0x60, 0x8D]
    
    if first_byte in valid_first_opcodes:
        print(f"✓ First byte is valid 6502 opcode: 0x{first_byte:02x}")
    else:
        print(f"⚠ First byte 0x{first_byte:02x} is unusual for boot sector")
    
    # Show first 32 bytes
    print(f"\nFirst 32 bytes:")
    for i in range(0, 32, 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[i:i+16])
        print(f"  {i:04x}: {hex_str}")
    
    # Check for DOS 3.3 patterns
    # DOS 3.3 typically has specific byte patterns
    dos33_indicators = [
        (0x01, 0x38),  # Common start: ORA, SEC
        (0x01, 0x60),  # Another pattern: ORA, RTS
    ]
    
    has_dos33_pattern = any(
        data[0] == a and data[1] == b 
        for a, b in dos33_indicators
    )
    
    # Check for ProDOS patterns  
    # ProDOS boot blocks often start with 0x01
    has_prodos_pattern = data[0] == 0x01
    
    # Look for jump instructions (4C xx xx)
    jmp_count = sum(1 for i in range(256) if data[i] == 0x4C)
    print(f"\nJMP instructions (0x4C) found: {jmp_count}")
    
    # Check for reasonable code density (not all same byte)
    unique_bytes = len(set(data[:256]))
    print(f"Unique bytes in first sector: {unique_bytes}/256")
    
    if unique_bytes < 20:
        print("⚠ WARNING: Very low code diversity - may not be valid boot sector")
    
    # Look for ASCII strings (Apple II software often has credits/titles)
    printable = sum(1 for b in data[:256] if 0x20 <= b <= 0x7E)
    print(f"Printable ASCII characters: {printable}/256 ({printable*100//256}%)")
    
    print(f"\nLikely format:")
    if has_dos33_pattern:
        print("  ✓ DOS 3.3 pattern detected")
    if has_prodos_pattern:
        print("  ✓ ProDOS pattern detected (starts with 0x01)")
    
    # Overall assessment
    print(f"\n{'─'*60}")
    if first_byte in valid_first_opcodes and unique_bytes > 20:
        print("✓ Boot sector looks valid")
        return True
    elif unique_bytes < 10:
        print("❌ Boot sector likely corrupted (too uniform)")
        return False
    else:
        print("⚠ Boot sector structure uncertain")
        return None

if __name__ == "__main__":
    import os
    
    # Test file
    test_file = "/mnt/filestorefs/Native/Apple/AppleII/Software/2MG/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg"
    
    print("Apple II Boot Sector Validator")
    print("="*60)
    
    # Read original 2MG file
    print(f"\nReading: {os.path.basename(test_file)}")
    with open(test_file, 'rb') as f:
        # Parse header
        header = f.read(64)
        if header[:4] != b'2IMG':
            print("ERROR: Not a 2MG file!")
            sys.exit(1)
        
        hdr_size = struct.unpack('<H', header[8:10])[0]
        data_off = struct.unpack('<I', header[28:32])[0]
        format_byte = struct.unpack('<I', header[16:20])[0]
        
        print(f"2MG Header:")
        print(f"  Header size: {hdr_size}")
        print(f"  Data offset: {data_off} (0 = use header size)")
        print(f"  Format byte: {format_byte} (0=DOS 3.3, 1=ProDOS)")
        
        # Read boot sector
        effective_offset = data_off if data_off > 0 and data_off < 1000 else hdr_size
        f.seek(effective_offset)
        boot_sector = f.read(256)
        
        validate_6502_boot_sector(boot_sector, f"Original 2MG @ offset {effective_offset}")
    
    # Now test transformed file
    trans_file_do = "/mnt/transfs/MiSTer/Apple-II/Disks/4th & Inches (1987)(Accolade)(Disk 1 of 2).do"
    trans_file_po = "/mnt/transfs/MiSTer/Apple-II/Disks/4th & Inches (1987)(Accolade)(Disk 1 of 2).po"
    
    for trans_file in [trans_file_do, trans_file_po]:
        if os.path.exists(trans_file):
            print(f"\nReading transformed: {os.path.basename(trans_file)}")
            with open(trans_file, 'rb') as f:
                boot_sector = f.read(256)
                validate_6502_boot_sector(boot_sector, f"Transformed {os.path.basename(trans_file)}")
