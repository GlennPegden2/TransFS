#!/bin/bash
set -e

echo "Build Script for Acorn Atom"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Systems/Acorn/Atom}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Resolve software source directory (supports both legacy and folder-based layouts)
SOFTWARE_SOURCE=""
for candidate in \
    "$SOFTWARE_DIR/Software/Sources/hoglet67" \
    "$SOFTWARE_DIR/Software/hoglet67"; do
    if [[ -d "$candidate" ]]; then
        SOFTWARE_SOURCE="$candidate"
        break
    fi
done

if [[ -z "$SOFTWARE_SOURCE" ]]; then
    echo "Software source directory not found. Checked:"
    echo "  - $SOFTWARE_DIR/Software/Sources/hoglet67"
    echo "  - $SOFTWARE_DIR/Software/hoglet67"
    exit 1
fi

echo "Found software source: $SOFTWARE_SOURCE"

# Resolve blank VHD source (supports both legacy and folder-based layouts)
BLANK_VHD=""
for candidate in \
    "$SOFTWARE_DIR/Software/Sources/blankvhd/blank.vhd" \
    "$SOFTWARE_DIR/Software/blankvhd/blank.vhd"; do
    if [[ -f "$candidate" ]]; then
        BLANK_VHD="$candidate"
        break
    fi
done

if [[ -z "$BLANK_VHD" ]]; then
    BLANK_VHD=$(find "$SOFTWARE_DIR/Software" -type f -name "blank*.vhd" | sort | head -n 1)
fi

if [[ -z "$BLANK_VHD" || ! -f "$BLANK_VHD" ]]; then
    echo "No blank VHD found under $SOFTWARE_DIR/Software"
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

# Sanity-check key boot files exist in the generated image
if ! guestfish --ro -a "$WORK_VHD" -m "$PARTITION" is-file /MENU >/dev/null 2>&1; then
    echo "Generated VHD is missing /MENU - aborting"
    exit 1
fi
if ! guestfish --ro -a "$WORK_VHD" -m "$PARTITION" is-file /SPLASH1 >/dev/null 2>&1; then
    echo "Generated VHD is missing /SPLASH1 - aborting"
    exit 1
fi
if ! guestfish --ro -a "$WORK_VHD" -m "$PARTITION" is-file /SPLASH2 >/dev/null 2>&1; then
    echo "Generated VHD is missing /SPLASH2 - aborting"
    exit 1
fi

# Move the updated VHD to Software/VHD directory
mkdir -p "$SOFTWARE_DIR/Software/VHD"
mv "$WORK_VHD" "$SOFTWARE_DIR/Software/VHD/hoglet67.vhd"

rm -rf "$WORK_DIR"

echo "Build complete."