import os
import pytest

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")

def load_snapshot(emu_name,system_name):
    with open(os.path.join(SNAPSHOT_DIR, f"{emu_name}", f"{system_name}.txt")) as f:
        return sorted(line.strip() for line in f if line.strip())

def walk_virtual_folder(root):
    """Yield all files and dirs under root, relative to root."""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        for d in dirnames:
            results.append(os.path.join(rel_dir, d) + "/")
        for f in filenames:
            results.append(os.path.join(rel_dir, f))
    return sorted(results)

@pytest.mark.parametrize("emu_name,system_name,virtual_path", [
    ("MiSTer","BBCMicro", "/"),
    # Add more systems here
])
def test_virtual_folder_snapshot(fuse_mount, emu_name, system_name, virtual_path):
    expected = load_snapshot(emu_name, system_name)
    actual = walk_virtual_folder(os.path.join(fuse_mount, virtual_path))
    assert actual == expected, f"Mismatch for {system_name}"