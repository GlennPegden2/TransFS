#!/bin/bash
set -e

echo "Build Script for BBC Micro - Rename SSD files"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/BBC_B/}Software/"
SSD_DIR="${SOFTWARE_DIR}SSD"

echo "Using SSD_DIR: $SSD_DIR"

# Change to SSD directory
cd "$SSD_DIR" || exit 1

# Rename all Disc???-*.ssd files to remove the Disc???- prefix
for f in Disc???-*.ssd; do 
    [ -f "$f" ] || continue
    newname="${f#Disc???-}"
    echo "Renaming: $f -> $newname"
    mv "$f" "$newname"
done

echo "Rename complete!"