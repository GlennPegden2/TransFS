#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')

from app.config import load_config
from app.data_provider_db import DataProviderDatabase

config = load_config()
db = DataProviderDatabase(config)

# Check what files exist in the database for Acorn/Atom
print("Files in database for Acorn/Atom:")
results = db.conn.execute("""
    SELECT file_path, system, file_size 
    FROM files 
    WHERE system = 'Atom'
    ORDER BY file_path
""").fetchall()

for row in results:
    print(f"  {row[0]} (system={row[1]}, size={row[2]})")
    
print(f"\nTotal: {len(results)} files")

# Also check if HDs query would find VHD files
print("\n\nVHD files in Acorn/Atom/Software:")
results = db.conn.execute("""
    SELECT file_path, system, file_size 
    FROM files 
    WHERE system = 'Atom' AND file_path LIKE '%Software%' AND file_path LIKE '%.VHD'
    ORDER BY file_path
""").fetchall()

for row in results:
    print(f"  {row[0]} (system={row[1]}, size={row[2]})")
    
print(f"\nTotal: {len(results)} VHD files")
