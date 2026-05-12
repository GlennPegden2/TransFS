import asyncio
from collections import defaultdict

import pyfuse3
import transfs as transfs_module
from transfs import TransFS


def test_root_lookup_mount_alias_returns_root(monkeypatch):
    """A hidden root alias like /mnt/transfs/transfs should resolve to root."""
    fs = TransFS.__new__(TransFS)
    fs.mount_path = "/mnt/transfs"
    fs.root = "/mnt/filestorefs"
    fs.config = {"filestore": "/mnt/filestorefs"}
    fs._inode_path_map = {pyfuse3.ROOT_INODE: "/mnt/filestorefs"}
    fs._lookup_cnt = defaultdict(int)
    fs._add_path = lambda inode, path: fs._inode_path_map.__setitem__(inode, path)
    fs._increment_lookup_count = lambda inode: None
    fs._make_synthetic_inode = lambda path: 42
    fs._normalize_to_virtual_path = TransFS._normalize_to_virtual_path.__get__(fs, TransFS)
    fs._get_parent_entries_for_lookup = lambda parent_path: {"Generic", "MAME", "MiSTer", "RetroBat", "RetroPie"}

    async def fake_getattr(inode, ctx=None):
        return {"inode": inode}

    fs.getattr = fake_getattr

    monkeypatch.setattr(transfs_module, "get_source_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(transfs_module, "get_source_path_for_write", lambda *args, **kwargs: None)

    result = asyncio.run(TransFS.lookup(fs, pyfuse3.ROOT_INODE, b"transfs"))
    assert result == {"inode": 42}
