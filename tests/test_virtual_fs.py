import os

def test_uef_file_visible(fuse_mount):
    tape_dir = os.path.join(fuse_mount, "MiSTer", "AcornElectron", "Tape", "Apps")
    files = os.listdir(tape_dir)
    assert any(f.upper().endswith(".UEF") for f in files)