#!/bin/bash
set -e

echo "Build Script for Acorn Atom"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/Atom/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Find the already-extracted software directory
SOFTWARE_SOURCE="$SOFTWARE_DIR/Software/Sources/hoglet67"
if [[ ! -d "$SOFTWARE_SOURCE" ]]; then
    echo "Software source directory not found: $SOFTWARE_SOURCE"
    exit 1
fi

echo "Found software source: $SOFTWARE_SOURCE"

# Find the blank.vhd (already extracted)
BLANK_VHD=$(find "$SOFTWARE_DIR/Software/Sources/blankvhd" -type f -name "*.vhd" | head -n 1)
if [[ -z "$BLANK_VHD" ]]; then
    echo "No .vhd file found in $SOFTWARE_DIR/Software/Sources/blankvhd"
    exit 1
fi

echo "Found blank VHD: $BLANK_VHD"

# Create a working copy of the blank VHD
WORK_DIR="$SOFTWARE_DIR/tmp"
mkdir -p "$WORK_DIR"
WORK_VHD="$WORK_DIR/hoglet67.vhd"
cp "$BLANK_VHD" "$WORK_VHD"

# Use guestfish to copy files into the VHD (no kernel modules required)
echo "Copying files into VHD"

# Find the first partition (assume /dev/sda1)
PARTITION="/dev/sda1"

# Copy all files from the software source into the root of the VHD partition
guestfish --rw -a "$WORK_VHD" -m "$PARTITION" <<EOF
copy-in "$SOFTWARE_SOURCE/." /
EOF

# Move the updated VHD to Software/VHD directory
mkdir -p "$SOFTWARE_DIR/Software/VHD"
mv "$WORK_VHD" "$SOFTWARE_DIR/Software/VHD/hoglet67.vhd"

rm -rf "$WORK_DIR"

echo "Build complete."