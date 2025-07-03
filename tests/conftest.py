import pytest

@pytest.fixture(scope="session")
def fuse_mount():
    # Change this to your actual FUSE mount path
    return "/mnt/transfs"