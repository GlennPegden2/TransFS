#!/bin/bash
# Flatten BBC_B folder structure for flat layout testing

set -e

echo "=== FLATTENING BBC_B FOLDER STRUCTURE ==="
echo ""

BBCB_DIR="/mnt/filestorefs/Native/Acorn/BBC_B/Software"

echo "Current structure:"
ls -la "$BBCB_DIR"

echo ""
echo "Flattening process:"

# Create a temporary directory to hold all files
TEMP_DIR="${BBCB_DIR}_flat"
echo "  1. Creating temporary directory: $TEMP_DIR"
mkdir -p "$TEMP_DIR"

# Copy all files from subfolders to temp directory
echo "  2. Copying files from subfolders..."
if [ -d "$BBCB_DIR/SSD" ]; then
    echo "     - Copying from SSD/ ..."
    cp -v "$BBCB_DIR/SSD"/* "$TEMP_DIR/" 2>/dev/null || true
fi

if [ -d "$BBCB_DIR/MMB" ]; then
    echo "     - Copying from MMB/ ..."
    cp -v "$BBCB_DIR/MMB"/* "$TEMP_DIR/" 2>/dev/null || true
fi

# Count files
FILE_COUNT=$(find "$TEMP_DIR" -type f | wc -l)
echo ""
echo "  3. Flattened $FILE_COUNT files to temporary location"

# Backup old structure
echo "  4. Backing up original structure..."
mv "$BBCB_DIR" "${BBCB_DIR}_old"

# Move flattened structure to real location
echo "  5. Moving flattened structure to $BBCB_DIR..."
mv "$TEMP_DIR" "$BBCB_DIR"

# Remove old structure
echo "  6. Cleaning up old structure..."
rm -rf "${BBCB_DIR}_old"

echo ""
echo "Flattened structure:"
ls -la "$BBCB_DIR"
echo ""
echo "Files in flattened directory:"
find "$BBCB_DIR" -type f -exec basename {} \; | sort | head -10
echo "  ... and more"

echo ""
echo "✓ BBC_B flattening complete!"
echo "  - All files now in single Software/ directory"
echo "  - Ready for config update to download_layout: flat"
