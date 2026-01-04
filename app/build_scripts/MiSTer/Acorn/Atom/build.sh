#!/bin/bash
set -e

echo "Build Script for Acorn Atom"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/Atom/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"


#Unzip the software archive
DOWNLOADED_ZIP=$(find "$SOFTWARE_DIR" -type f -name "*.zip" | head -n 1)
if [[ -z "$DOWNLOADED_ZIP" ]]; then
    echo "No downloaded zip found in $SOFTWARE_DIR"
    exit 1
fi

echo "Found downloaded zip: $DOWNLOADED_ZIP"

UNZIP_DIR="$SOFTWARE_DIR/tmp/unzipped_software"
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"
unzip -o "$DOWNLOADED_ZIP" -d "$UNZIP_DIR"


#Unzip the blank
DOWNLOADED_ZIP=$(find "$SOFTWARE_DIR/Software/Utils/" -type f -name "blank.zip" | head -n 1)
if [[ -z "$DOWNLOADED_ZIP" ]]; then
    echo "No downloaded zip found in $SOFTWARE_DIR"
    exit 1
fi

UNZIP_DIR="$SOFTWARE_DIR/tmp/unzipped_vhd"
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"
unzip -o "$DOWNLOADED_ZIP" -d "$UNZIP_DIR"



# Find the blank.vhd (assumes it was downloaded via the API)
BLANK_VHD=$(find "$UNZIP_DIR" -maxdepth 1 -type f -name "*.vhd" | head -n 1)
if [[ -z "$BLANK_VHD" ]]; then
    echo "No .vhd file found in $UNZIP_DIR"
    exit 1
fi

echo "Found blank VHD: $BLANK_VHD"

# Use guestfish to copy files into the VHD (no kernel modules required)
echo "Copying files into VHD"

# Find the first partition (assume /dev/sda1)
PARTITION="/dev/sda1"

# Copy all files from unzipped_software into the root of the VHD partition
guestfish --rw -a "$BLANK_VHD" -m "$PARTITION" <<EOF
copy-in "$SOFTWARE_DIR/tmp/unzipped_software/." /
EOF

# Move the updated VHD to Software/HDs directory
mkdir -p "$SOFTWARE_DIR/Software/VHD"
mv "$BLANK_VHD" "$SOFTWARE_DIR/Software/VHD/hoglet67.vhd"


rm -rf "$SOFTWARE_DIR/tmp/"

echo "Build complete."