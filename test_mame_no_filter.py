#!/usr/bin/env python3
"""Test MAME download with exclude_unsupported=False."""

import sys
sys.path.insert(0, '/app')

from config import read_config
from mame.manager import MAMEDownloadManager

config = read_config()
manager = MAMEDownloadManager(config)

print("Testing with exclude_unsupported=False...")
stats = manager.download_for_system(
    system="atom",
    media_type="cass",
    target_folder="Software/MAME/Cassettes",
    filters={"exclude_unsupported": False}
)

print(f"Total entries: {stats['total_entries']}")
print(f"Filtered entries: {stats['filtered_entries']}")
print(f"Files to download: {stats['total_files']}")
print(f"Downloaded: {stats['downloaded']}")
print(f"Already existed: {stats['already_existed']}")
print(f"Failed: {stats['failed']}")
