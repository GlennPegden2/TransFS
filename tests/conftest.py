import os
import shutil
import tempfile
import time
import subprocess
import pytest

@pytest.fixture(scope="session")
def filestore_dir():
    # Create a temp filestore with sample data
    temp_dir = tempfile.mkdtemp(prefix="filestore_")
    # You can add sample files here for your tests
    os.makedirs(os.path.join(temp_dir, "Native", "Acorn", "Electron", "Software", "UEF", "Apps"), exist_ok=True)
    # Example file
    with open(os.path.join(temp_dir, "Native", "Acorn", "Electron", "Software", "UEF", "Apps", "Test.UEF"), "w") as f:
        f.write("dummy uef content")
    yield temp_dir
    shutil.rmtree(temp_dir)

@pytest.fixture(scope="session")
def fuse_mount(tmp_path_factory, filestore_dir):
    mount_dir = tmp_path_factory.mktemp("fusemnt")
    # Start your FUSE filesystem as a subprocess
    proc = subprocess.Popen([
        "python", "app/transfs.py",
        "--mount", str(mount_dir),
        "--root", filestore_dir
    ])
    # Wait for mount to be ready
    time.sleep(2)
    yield str(mount_dir)
    proc.terminate()
    proc.wait()