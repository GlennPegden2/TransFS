#!/bin/bash
set -e

echo "Build Script for Amstrad PCW build"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Amstrad/PCW/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Unzip the software archive
DOWNLOADED_ZIP=$(find "$SOFTWARE_DIR/Collections" -type f -name "*.zip" | head -n 1)
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

unzip "$DOWNLOADED_ZIP" -d "$UNZIP_DIR"
#find "$UNZIP_DIR" -type f -exec mv -t "$DSK_DIR" {} +
#find "$UNZIP_DIR" -type d -empty -delete

mkdir -p "$SOFTWARE_DIR/DSK"
mkdir -p "$SOFTWARE_DIR/DSK/Demos"
mkdir -p "$SOFTWARE_DIR/DSK/PD"
mkdir -p "$SOFTWARE_DIR/DSK/Compilations"
mkdir -p "$SOFTWARE_DIR/ROM"
mkdir -p "$SOFTWARE_DIR/CPR"

mv $UNZIP_DIR/*/*\[DSK\]*/* $SOFTWARE_DIR/DSK
mv $UNZIP_DIR/*/*\[ROM\]*/* $SOFTWARE_DIR/ROM
mv $UNZIP_DIR/*/*\[CPR\]*/* $SOFTWARE_DIR/CPR
mv $UNZIP_DIR/*/*Demos*/* $SOFTWARE_DIR/DSK/Demos
mv $UNZIP_DIR/*/*Public Domain*/* $SOFTWARE_DIR/DSK/PD
mv $UNZIP_DIR/*/*Compilations*/* $SOFTWARE_DIR/DSK/Compilations
#mv $UNZIP_DIR/*/*\[TAP\]*/* $SOFTWARE_DIR/TAP
#mv $UNZIP_DIR/*/*\[HEX\]*/* $SOFTWARE_DIR/HEX
#mv $UNZIP_DIR/*/*Boot\ Loader*/* $SOFTWARE_DIR/HEX
#mv $UNZIP_DIR/*/*Firmware*/* $SOFTWARE_DIR/HEX

echo "Build complete. Flattened files are in $DSK_DIR"