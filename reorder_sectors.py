#!/usr/bin/env python3
"""
Reorder Apple II disk sectors between DOS 3.3 and ProDOS interleave.

Apple II disks have 35 tracks, 16 sectors per track, 256 bytes per sector.
DOS 3.3 and ProDOS use different sector interleaving patterns.
"""

import sys
import struct
import os

# DOS 3.3 physical sector interleave (DOS logical sector -> physical sector)
# This is the order DOS 3.3 reads sectors from the disk
DOS33_INTERLEAVE = [0x0, 0x7, 0xE, 0x6, 0xD, 0x5, 0xC, 0x4, 
                    0xB, 0x3, 0xA, 0x2, 0x9, 0x1, 0x8, 0xF]

# ProDOS uses sequential physical sector order (0-15)
PRODOS_INTERLEAVE = list(range(16))

# Reverse lookup tables
DOS33_TO_PHYSICAL = DOS33_INTERLEAVE
PHYSICAL_TO_DOS33 = [DOS33_INTERLEAVE.index(i) for i in range(16)]

PRODOS_TO_PHYSICAL = PRODOS_INTERLEAVE
PHYSICAL_TO_PRODOS = list(range(16))


def reorder_track(track_data: bytes, from_format: str, to_format: str) -> bytes:
    """
    Reorder sectors within a track.
    
    Args:
        track_data: 4096 bytes (16 sectors * 256 bytes each)
        from_format: 'dos33' or 'prodos'
        to_format: 'dos33' or 'prodos'
    
    Returns:
        Reordered track data
    """
    if len(track_data) != 4096:
        raise ValueError(f"Track data must be 4096 bytes, got {len(track_data)}")
    
    if from_format == to_format:
        return track_data  # No reordering needed
    
    sectors = [track_data[i*256:(i+1)*256] for i in range(16)]
    reordered = [b''] * 16
    
    if from_format == 'dos33' and to_format == 'prodos':
        # Convert DOS 3.3 logical order to ProDOS physical order
        for dos_sector in range(16):
            physical_sector = DOS33_TO_PHYSICAL[dos_sector]
            reordered[physical_sector] = sectors[dos_sector]
    elif from_format == 'prodos' and to_format == 'dos33':
        # Convert ProDOS physical order to DOS 3.3 logical order
        for prodos_sector in range(16):
            dos_sector = PHYSICAL_TO_DOS33[prodos_sector]
            reordered[dos_sector] = sectors[prodos_sector]
    else:
        raise ValueError(f"Unsupported conversion: {from_format} -> {to_format}")
    
    return b''.join(reordered)


def reorder_disk(disk_data: bytes, from_format: str, to_format: str) -> bytes:
    """
    Reorder all tracks on a disk.
    
    Args:
        disk_data: Full disk data (typically 143360 bytes for 35 tracks)
        from_format: 'dos33' or 'prodos'
        to_format: 'dos33' or 'prodos'
    
    Returns:
        Reordered disk data
    """
    if len(disk_data) % 4096 != 0:
        print(f"WARNING: Disk size {len(disk_data)} is not a multiple of 4096")
    
    num_tracks = len(disk_data) // 4096
    print(f"Reordering {num_tracks} tracks from {from_format} to {to_format}...")
    
    reordered_tracks = []
    for track_num in range(num_tracks):
        track_start = track_num * 4096
        track_end = track_start + 4096
        track_data = disk_data[track_start:track_end]
        
        if len(track_data) < 4096:
            # Pad last track if needed
            track_data += b'\x00' * (4096 - len(track_data))
        
        reordered_track = reorder_track(track_data, from_format, to_format)
        reordered_tracks.append(reordered_track)
    
    return b''.join(reordered_tracks)


def process_2mg_file(input_path: str, output_base: str):
    """
    Process a 2MG file and create reordered versions.
    
    Args:
        input_path: Path to input .2mg file
        output_base: Base path for output files (will add .do/.po)
    """
    print(f"\nProcessing: {os.path.basename(input_path)}")
    print("="*60)
    
    with open(input_path, 'rb') as f:
        # Read and parse header
        header = f.read(64)
        if header[:4] != b'2IMG':
            print("ERROR: Not a 2MG file!")
            return
        
        hdr_size = struct.unpack('<H', header[8:10])[0]
        data_off = struct.unpack('<I', header[28:32])[0]
        data_len = struct.unpack('<I', header[32:36])[0]
        format_byte = struct.unpack('<I', header[16:20])[0]
        
        print(f"2MG Header:")
        print(f"  Format byte: {format_byte} ({'DOS 3.3' if format_byte == 0 else 'ProDOS' if format_byte == 1 else 'Unknown'})")
        print(f"  Header size: {hdr_size}")
        print(f"  Data offset: {data_off} (using {hdr_size if data_off == 0 else data_off})")
        print(f"  Data length: {data_len}")
        
        # Determine source format from format byte
        source_format = 'dos33' if format_byte == 0 else 'prodos'
        
        # Read disk data
        f.seek(0, 2)
        file_size = f.tell()
        effective_offset = data_off if (data_off > 0 and data_off < file_size) else hdr_size
        
        f.seek(effective_offset)
        disk_data = f.read()
        
        print(f"  Disk data: {len(disk_data)} bytes")
        print(f"  Source format: {source_format}")
    
    # Create both orderings
    print(f"\nCreating reordered versions...")
    
    # Version 1: Keep original ordering, just strip header
    output_original = f"{output_base}.{source_format}-original.dsk"
    with open(output_original, 'wb') as f:
        f.write(disk_data)
    print(f"  ✓ Original ordering: {output_original}")
    
    # Version 2: Reorder to opposite format
    target_format = 'prodos' if source_format == 'dos33' else 'dos33'
    reordered_data = reorder_disk(disk_data, source_format, target_format)
    
    output_reordered = f"{output_base}.{target_format}-reordered.dsk"
    with open(output_reordered, 'wb') as f:
        f.write(reordered_data)
    print(f"  ✓ Reordered to {target_format}: {output_reordered}")
    
    # Version 3: Keep as DOS but write as .do
    output_do = f"{output_base}.do"
    if source_format == 'dos33':
        with open(output_do, 'wb') as f:
            f.write(disk_data)
        print(f"  ✓ DOS 3.3 order (.do): {output_do}")
    else:
        reordered_to_dos = reorder_disk(disk_data, 'prodos', 'dos33')
        with open(output_do, 'wb') as f:
            f.write(reordered_to_dos)
        print(f"  ✓ Converted to DOS 3.3 (.do): {output_do}")
    
    # Version 4: Keep as ProDOS but write as .po
    output_po = f"{output_base}.po"
    if source_format == 'prodos':
        with open(output_po, 'wb') as f:
            f.write(disk_data)
        print(f"  ✓ ProDOS order (.po): {output_po}")
    else:
        reordered_to_prodos = reorder_disk(disk_data, 'dos33', 'prodos')
        with open(output_po, 'wb') as f:
            f.write(reordered_to_prodos)
        print(f"  ✓ Converted to ProDOS (.po): {output_po}")
    
    print(f"\nCreated 4 versions - try each on MiSTer to see which boots!")


if __name__ == "__main__":
    # Test with 4th & Inches
    input_file = "/mnt/filestorefs/Native/Apple/AppleII/Software/2MG/4th & Inches (1987)(Accolade)(Disk 1 of 2).2mg"
    output_base = "/tmp/4th_inches_disk1"
    
    if os.path.exists(input_file):
        process_2mg_file(input_file, output_base)
        
        print(f"\n{'='*60}")
        print("Testing complete! Files created in /tmp/")
        print("Copy these to MiSTer and try booting each version:")
        print("  1. .dos33-original.dsk - Original DOS 3.3 ordering")
        print("  2. .prodos-reordered.dsk - Reordered to ProDOS")
        print("  3. .do - DOS 3.3 format")
        print("  4. .po - ProDOS format")
    else:
        print(f"ERROR: File not found: {input_file}")
