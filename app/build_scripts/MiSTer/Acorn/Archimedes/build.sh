#!/bin/bash
set -e

echo "Build Script for Acorn Archimedes"

# Use BASE_PATH from environment, fallback to default if not set
BASE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/Archimedes/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

SOFTWARE_DIR="${BASE_DIR}/Collections"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"
mkdir -p "$SOFTWARE_DIR/tmp/unzipped_software"

unzip -o "$SOFTWARE_DIR/4corn/riscos3_71.zip" -d "$SOFTWARE_DIR/tmp/unzipped_software"
7zr x -y "$SOFTWARE_DIR/SIDKiddCROS4.2/CROS42_082620.7z" -o"$SOFTWARE_DIR/tmp/unzipped_software"
7zr x -y "$SOFTWARE_DIR/Icebird/ICEBIRD.7z" -o"$SOFTWARE_DIR/tmp/unzipped_software"


mkdir -p "$SOFTWARE_DIR/../HDF"
mkdir -p "$SOFTWARE_DIR/../BIOS"

mv $SOFTWARE_DIR/tmp/unzipped_software/*.hdf $SOFTWARE_DIR/../HDF
mv $SOFTWARE_DIR/tmp/unzipped_software/*.rom $SOFTWARE_DIR/../BIOS

rm -rf "$SOFTWARE_DIR/tmp/unzipped_software"

echo "Build complete."