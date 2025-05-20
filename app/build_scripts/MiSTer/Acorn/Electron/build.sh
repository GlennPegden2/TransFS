#!/bin/bash
set -e

echo "Build Script for Acorn Electron"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Acorn/Electron/}"
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



# Move the updated VHD up one folder level
mkdir -p "$SOFTWARE_DIR/HDs"
mv "$UNZIP_DIR/BEEB.MMB" "$SOFTWARE_DIR/HDs/rayhaper.mmb"

echo "Build complete."