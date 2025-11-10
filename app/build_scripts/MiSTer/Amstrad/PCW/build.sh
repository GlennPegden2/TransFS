#!/bin/bash
set -e

echo "Build Script for Amstrad PCW build"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Amstrad/PCW/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Unzip the software archive
DOWNLOADED_ZIP=$(find "$SOFTWARE_DIR/Collections" -type f -name "*.tar.gz" | head -n 1)
if [[ -z "$DOWNLOADED_ZIP" ]]; then
    echo "No downloaded zip found in $SOFTWARE_DIR/Collections/"
    exit 1
fi

echo "Found downloaded zip: $DOWNLOADED_ZIP"

UNZIP_DIR="$SOFTWARE_DIR/tmp/unzipped_software"
DSK_DIR="$SOFTWARE_DIR/DSK"
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"
mkdir -p "$DSK_DIR"

tar -zxvf "$DOWNLOADED_ZIP" -C "$UNZIP_DIR"
find "$UNZIP_DIR" -type f -exec mv -t "$DSK_DIR" {} +
find "$UNZIP_DIR" -type d -empty -delete

rm -rf "$SOFTWARE_DIR/tmp/unzipped_software"

echo "Build complete. Flattened files are in $DSK_DIR"