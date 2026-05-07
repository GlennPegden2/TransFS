"""Locked snapshot tests for verified TransFS client/system combinations.

Workflow:
1. Verify a client/system combo manually (for example via the Debug UI).
2. Capture a locked baseline from the Debug UI snapshot controls.
3. This test enforces that listing output remains unchanged unless intentionally re-captured.
"""

import json
from pathlib import Path
from typing import Any, Dict

import pytest


BASELINE_DIR = Path("/tests/snapshots/locked")


def get_directory_tree(path: Path, max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
    """Recursively capture deterministic directory structure for comparison."""
    if current_depth >= max_depth:
        return {"_type": "truncated"}

    tree: Dict[str, Any] = {"_type": "directory", "_items": {}}
    try:
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower(), p.name))
        for item in items:
            if item.name.startswith("."):
                continue
            try:
                if item.is_dir():
                    tree["_items"][item.name] = get_directory_tree(
                        item,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                    )
                else:
                    file_info: Dict[str, Any] = {
                        "_type": "file",
                        "size": item.stat().st_size,
                    }
                    if item.is_symlink():
                        file_info["target"] = str(item.resolve())
                    tree["_items"][item.name] = file_info
            except (OSError, PermissionError) as exc:
                tree["_items"][item.name] = {"_type": "error", "reason": str(exc)}
    except (OSError, PermissionError) as exc:
        return {"_type": "error", "reason": str(exc)}

    return tree


def _baseline_files() -> list[Path]:
    if not BASELINE_DIR.exists():
        return []
    return sorted(BASELINE_DIR.glob("*.json"))


def test_locked_snapshots_exist():
    """Ensure at least one locked baseline exists before running compare tests."""
    baselines = _baseline_files()
    if not baselines:
        pytest.skip("No locked snapshots found. Capture one from the Debug UI snapshot controls.")
    assert baselines


@pytest.mark.parametrize("baseline_file", _baseline_files(), ids=lambda p: p.stem)
def test_locked_snapshot_directory_tree(baseline_file: Path):
    """Compare current directory tree with the captured locked baseline."""
    with baseline_file.open("r", encoding="utf-8") as f:
        baseline = json.load(f)

    transfs_path = Path(baseline.get("transfs_path", ""))
    max_depth = int(baseline.get("max_depth", 3))
    expected_tree = baseline.get("tree")

    if not transfs_path.exists():
        pytest.skip(f"Baseline path missing: {transfs_path}")

    current_tree = get_directory_tree(transfs_path, max_depth=max_depth)
    assert current_tree == expected_tree
