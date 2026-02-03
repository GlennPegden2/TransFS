"""Snapshot tests for system directory structures.

These tests capture the complete directory tree for each system,
making it easy to spot unexpected changes in the filesystem mapping.

Run with `pytest --snapshot-update` to update snapshots after expected changes.
"""

import pytest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_directory_tree(path: Path, max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
    """Recursively get directory tree structure.
    
    Args:
        path: Root path to start tree from
        max_depth: Maximum directory depth to traverse
        current_depth: Current depth (internal)
    
    Returns:
        Dictionary representing directory structure
    """
    if current_depth >= max_depth:
        return {"_type": "truncated"}
    
    tree = {
        "_type": "directory",
        "_items": {},
    }
    
    try:
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        
        for item in items:
            # Skip hidden files
            if item.name.startswith("."):
                continue
            
            try:
                if item.is_dir():
                    tree["_items"][item.name] = get_directory_tree(
                        item,
                        max_depth=max_depth,
                        current_depth=current_depth + 1
                    )
                else:
                    # For files, capture: name, size, is_symlink
                    file_info = {
                        "_type": "file",
                        "size": item.stat().st_size,
                    }
                    if item.is_symlink():
                        file_info["target"] = str(item.resolve().relative_to(path.parent))
                    tree["_items"][item.name] = file_info
            except (OSError, PermissionError) as e:
                tree["_items"][item.name] = {"_type": "error", "reason": str(e)}
    
    except (OSError, PermissionError) as e:
        tree["_type"] = "error"
        tree["reason"] = str(e)
    
    return tree


@dataclass
class SnapshotTarget:
    """Configuration for a snapshot test target."""
    system_name: str
    start_path: str
    snapshot_name: str
    max_depth: int = 3
    skip_reason: Optional[str] = None


SNAPSHOT_TARGETS: List[SnapshotTarget] = [
    SnapshotTarget(
        system_name="MiSTer root",
        start_path="/mnt/transfs/MiSTer",
        snapshot_name="mister_root",
        max_depth=2,
    ),
    SnapshotTarget(
        system_name="Amstrad CPC",
        start_path="/mnt/transfs/MiSTer/Amstrad/",
        snapshot_name="amstrad_cpc_structure",
        max_depth=2,
    ),
    SnapshotTarget(
        system_name="Acorn Electron",
        start_path="/mnt/transfs/MiSTer/AcornElectron",
        snapshot_name="acorn_electron_structure",
        max_depth=2,
    ),
]


@pytest.mark.parametrize("target", SNAPSHOT_TARGETS, ids=lambda t: t.system_name)
def test_snapshot_directory_tree(snapshot, target: SnapshotTarget):
    """Recursively capture a system's directory tree and compare to stored snapshot."""
    if target.skip_reason:
        pytest.skip(f"{target.system_name}: {target.skip_reason}")
    
    start = Path(target.start_path)
    if not start.exists():
        pytest.skip(f"{target.system_name}: start path not available at {start}")
    
    tree = get_directory_tree(start, max_depth=target.max_depth)
    assert tree == snapshot(name=target.snapshot_name)
