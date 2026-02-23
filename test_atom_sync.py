#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from sync_database import DatabaseSync
from config import read_config
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

config = read_config('config')
sync = DatabaseSync(config)
sync.init_database()

from db.connection import get_connection
sync.conn = get_connection()
sync.cursor = sync.conn.cursor()

source_path = "/mnt/filestorefs/Native/Acorn/Atom/Software"
extensions = ["ATM"]
extension_map = {}
transforms = {}

print(f"\n=== Testing recursive scan ===")
print(f"Source path: {source_path}")
print(f"Extensions: {extensions}")

count = sync._scan_directory_recursive(
    source_path, "RetroBat", "AcornAtom", "FDs",
    extensions, extension_map, transforms, 0, True
)

print(f"\n=== Results ===")
print(f"Files found: {count}")
print(f"Batch size: {len(sync.file_batch)}")
if sync.file_batch:
    print(f"\nFirst 5 files in batch:")
    for i, file_info in enumerate(sync.file_batch[:5]):
        print(f"  {i+1}. {file_info['filename']} (ext: {file_info['extension']})")
