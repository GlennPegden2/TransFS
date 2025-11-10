#!/bin/bash
set -e

echo "Build Script for Altair 8800"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/MITS/Altair8800/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"


#Unzip the software archive
DOWNLOADED_ZIP=$(find "$SOFTWARE_DIR/Collections" -type f -name "*.zip" | head -n 1)
if [[ -z "$DOWNLOADED_ZIP" ]]; then
    echo "No downloaded zip found in $SOFTWARE_DIR/Collections/"
    exit 1
fi

echo "Found downloaded zip: $DOWNLOADED_ZIP"

UNZIP_DIR="$SOFTWARE_DIR/tmp/unzipped_software"
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"
unzip -o "$DOWNLOADED_ZIP" -d "$UNZIP_DIR"

mkdir -p "$SOFTWARE_DIR/BAS"
mkdir -p "$SOFTWARE_DIR/BIN"
mkdir -p "$SOFTWARE_DIR/CAS"
mkdir -p "$SOFTWARE_DIR/DSK"
mkdir -p "$SOFTWARE_DIR/TAP"
mkdir -p "$SOFTWARE_DIR/HEX"

mv $UNZIP_DIR/*/*\[BAS\]*/* $SOFTWARE_DIR/BAS
mv $UNZIP_DIR/*/*\[BIN\]*/* $SOFTWARE_DIR/BIN
mv $UNZIP_DIR/*/*\[CAS\]*/* $SOFTWARE_DIR/CAS
mv $UNZIP_DIR/*/*\[DSK\]*/* $SOFTWARE_DIR/DSK
mv $UNZIP_DIR/*/*\[TAP\]*/* $SOFTWARE_DIR/TAP
mv $UNZIP_DIR/*/*\[HEX\]*/* $SOFTWARE_DIR/HEX
mv $UNZIP_DIR/*/*Boot\ Loader*/* $SOFTWARE_DIR/HEX
mv $UNZIP_DIR/*/*Firmware*/* $SOFTWARE_DIR/HEX

rm -rf "$SOFTWARE_DIR/tmp/unzipped_software"

echo "Build complete."