import os
import pytest

@pytest.mark.parametrize("system_name,virtual_path", [
    ("BBCMicro", "MiSTer/BBCMicro"),
    # Add more systems as needed
])
def test_all_virtual_files_openable(fuse_mount, system_name, virtual_path):
    root = os.path.join(fuse_mount, virtual_path)
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            print(f"Checking file: {fname} in {dirpath}")
            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, fuse_mount)
            try:
                with open(fpath, "rb") as f:
                    f.read(1)  # Try to read at least one byte
            except Exception as e:
                pytest.fail(f"Could not open/read {relpath}: {e}")