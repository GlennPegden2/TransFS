#!/usr/bin/env python3
"""Query metadata enrichment results for Atari 2600 files."""

import sqlite3
import sys

db_path = '/mnt/filestorefs/.transfs_metadata.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check for Atari 2600 files
print("=== Atari 2600 Files in Database ===")
cursor.execute("""
    SELECT f.file_id, f.filename, fm.media_type_id, fm.app_type_id, fm.region_id, fm.publisher_id
    FROM files f
    LEFT JOIN file_metadata fm ON f.file_id = fm.file_id
    WHERE f.system = 'Atari2600'
    LIMIT 5
""")
rows = cursor.fetchall()
print(f"Found {len(rows)} Atari 2600 files (showing first 5)")
for row in rows[:5]:
    print(f"  {dict(row)}")

# Check media_types table
print("\n=== Media Types in Database ===")
cursor.execute("SELECT id, name FROM media_types LIMIT 10")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Check regions
print("\n=== Regions in Database ===")
cursor.execute("SELECT id, name FROM regions LIMIT 10")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Check app_types
print("\n=== App Types in Database ===")
cursor.execute("SELECT id, name FROM app_types LIMIT 10")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Check packs
print("\n=== Packs in Database ===")
cursor.execute("SELECT pack_id, name, ruleset FROM packs")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} (ruleset: {row[2]})")

# Check file_packs for Atari 2600
print("\n=== File Packs for Atari 2600 ===")
cursor.execute("""
    SELECT fp.file_id, p.name, f.filename
    FROM file_packs fp
    JOIN packs p ON fp.pack_id = p.pack_id
    JOIN files f ON fp.file_id = f.file_id
    WHERE f.system = 'Atari2600'
    LIMIT 10
""")
rows = cursor.fetchall()
print(f"Found {len(rows)} file-pack associations for Atari 2600 (showing first 10)")
for row in rows[:10]:
    print(f"  File {row[0]}: {row[2]} -> Pack {row[1]}")

# Detailed metadata for first Atari 2600 file
print("\n=== Detailed Metadata for First Atari 2600 File ===")
cursor.execute("""
    SELECT f.file_id, f.filename, f.extension, 
           mt.name as media_type, at.name as app_type, r.name as region, l.name as language
    FROM files f
    LEFT JOIN file_metadata fm ON f.file_id = fm.file_id
    LEFT JOIN media_types mt ON fm.media_type_id = mt.id
    LEFT JOIN app_types at ON fm.app_type_id = at.id
    LEFT JOIN regions r ON fm.region_id = r.id
    LEFT JOIN languages l ON fm.language_id = l.id
    WHERE f.system = 'Atari2600'
    LIMIT 1
""")
row = cursor.fetchone()
if row:
    print(f"  File ID: {row[0]}")
    print(f"  Filename: {row[1]}")
    print(f"  Extension: {row[2]}")
    print(f"  Media Type: {row[3]}")
    print(f"  App Type: {row[4]}")
    print(f"  Region: {row[5]}")
    print(f"  Language: {row[6]}")

# Check tags for Atari 2600
print("\n=== Tags for Atari 2600 Files ===")
cursor.execute("""
    SELECT ft.file_id, f.filename, ft.tag_type, ft.tag_value
    FROM file_tags ft
    JOIN files f ON ft.file_id = f.file_id
    WHERE f.system = 'Atari2600'
    LIMIT 10
""")
rows = cursor.fetchall()
print(f"Found {len(rows)} tags (showing first 10)")
for row in rows[:10]:
    print(f"  File {row[0]} ({row[1]}): {row[2]} = {row[3]}")

conn.close()
print("\n=== Query Complete ===")
