#!/bin/bash
set -e

echo "Build Script for Acorn Atom on Retrobat"

# Use BASE_PATH from environment, fallback to default if not set
SOFTWARE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/Atom/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Find the already-extracted software directory
SOFTWARE_SOURCE="$SOFTWARE_DIR/Software/SourcesBIOS"
if [[ ! -d "$SOFTWARE_SOURCE" ]]; then
    echo "Software source directory not found: $SOFTWARE_SOURCE"
    exit 1
fi


rm -rf "$WORK_DIR"

echo "Build complete."