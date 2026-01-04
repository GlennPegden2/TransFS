#!/usr/bin/env python3
"""
Quick validation script to verify TransFS functionality in Docker.
Runs fast checks without full filesystem walks.
"""
import os
import sys

def test_mount_accessible():
    """Test that FUSE mount is accessible"""
    if not os.path.exists('/mnt/transfs'):
        print("❌ FUSE mount /mnt/transfs not found")
        return False
    print("✓ FUSE mount accessible")
    return True

def test_amstrad_structure():
    """Test Amstrad CPC structure"""
    base = '/mnt/transfs/MiSTer/Amstrad'
    
    # Check directory exists
    if not os.path.isdir(base):
        print(f"❌ {base} not found")
        return False
    print(f"✓ {base} exists")
    
    # Check BIOS files
    bios_files = ['boot.rom', 'cpc464nd.eZ0']
    for f in bios_files:
        path = os.path.join(base, f)
        if not os.path.isfile(path):
            print(f"❌ {path} not found")
            return False
        print(f"✓ {path} exists")
    
    # Check Collections folder
    collections = os.path.join(base, 'Collections')
    if not os.path.isdir(collections):
        print(f"❌ {collections} not found")
        return False
    print(f"✓ {collections} exists")
    
    return True

def test_zip_navigation():
    """Test ZIP file navigation"""
    zip_path = '/mnt/transfs/MiSTer/Amstrad/Collections/AmstradCPC-CDT_Collection.zip'
    
    if not os.path.isdir(zip_path):
        print(f"❌ {zip_path} not navigable")
        return False
    print(f"✓ {zip_path} appears as directory")
    
    # Check subdirectory
    cdt_dir = os.path.join(zip_path, 'CDT')
    if not os.path.isdir(cdt_dir):
        print(f"❌ {cdt_dir} not accessible")
        return False
    print(f"✓ {cdt_dir} accessible")
    
    # Check we can list files (just count, don't list all)
    try:
        files = os.listdir(cdt_dir)
        count = len(files)
        print(f"✓ {cdt_dir} contains {count} files")
    except Exception as e:
        print(f"❌ Failed to list {cdt_dir}: {e}")
        return False
    
    return True

def test_file_reading():
    """Test reading a file from inside a ZIP"""
    test_file = '/mnt/transfs/MiSTer/Amstrad/Collections/AmstradCPC-CDT_Collection.zip/CDT/1942 (E).cdt'
    
    try:
        with open(test_file, 'rb') as f:
            header = f.read(8)
            if header.startswith(b'ZXTape!'):
                print(f"✓ File readable with correct content")
                return True
            else:
                print(f"❌ File content incorrect: {header}")
                return False
    except Exception as e:
        print(f"❌ Failed to read {test_file}: {e}")
        return False

def main():
    print("=== TransFS Docker Validation ===\n")
    
    tests = [
        ("Mount Accessibility", test_mount_accessible),
        ("Amstrad CPC Structure", test_amstrad_structure),
        ("ZIP Navigation", test_zip_navigation),
        ("File Reading", test_file_reading),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n{name}:")
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "="*40)
    passed = sum(results)
    total = len(results)
    
    if all(results):
        print(f"✅ All {total} tests passed")
        return 0
    else:
        print(f"❌ {passed}/{total} tests passed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
