#!/bin/bash
set -e

echo "Build Script for Acorn Electron"

# Use BASE_PATH from environment, fallback to default if not set
BASE_DIR="${BASE_PATH:-/mnt/filestorefs/Native/Acorn/Electron/}"
TMP_DIR="${TMP_DIR:-/tmp/}"

SOFTWARE_DIR="${BASE_DIR}/Collections"

echo "Using SOFTWARE_DIR: $SOFTWARE_DIR"

# Unzip ALL .zip files in $SOFTWARE_DIR
UNZIP_DIR="$SOFTWARE_DIR/tmp/unzipped_software"
rm -rf "$UNZIP_DIR"
mkdir -p "$UNZIP_DIR"

found_zip=0
for zipfile in "$SOFTWARE_DIR"/*.zip; do
    if [[ -f "$zipfile" ]]; then
        echo "Unzipping $zipfile"
        unzip -o "$zipfile" -d "$UNZIP_DIR"
        found_zip=1
    fi
done

if [[ $found_zip -eq 0 ]]; then
    echo "No downloaded zip files found in $SOFTWARE_DIR"
    exit 1
fi

mkdir -p "$SOFTWARE_DIR/../SSD"
mkdir -p "$SOFTWARE_DIR/../MMB"
mkdir -p "$SOFTWARE_DIR/../UEF/"
mkdir -p "$SOFTWARE_DIR/../UEF/Apps"
mkdir -p "$SOFTWARE_DIR/../UEF/CoverTapes"
mkdir -p "$SOFTWARE_DIR/../UEF/Demos"
mkdir -p "$SOFTWARE_DIR/../UEF/Educational"
mkdir -p "$SOFTWARE_DIR/../UEF/Games"
mkdir -p "$SOFTWARE_DIR/../ROMS/"
mkdir -p "$SOFTWARE_DIR/../ADF"
mkdir -p "$SOFTWARE_DIR/../DFS"
mkdir -p "$SOFTWARE_DIR/../HFE"

mv "$UNZIP_DIR/BEEB.MMB" "/$SOFTWARE_DIR/../MMB/rayharper.mmb"
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Applications\ -\ \[BIN\]\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../ROMS
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Applications\ -\ \[UEF\]\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../UEF/Apps
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ CoverTapes\ \(TOSEC-v2011-02-22_CM\)/* $SOFTWARE_DIR/../UEF/CoverTapes
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Demos\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../UEF/Demos
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Educational\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../UEF/Educational
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Games\ -\ \[UEF\]\ \(TOSEC-v2011-02-22_CM\)/* $SOFTWARE_DIR/../UEF/Games
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Games\ -\ \[SSD\]\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../SSD
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Multimedia\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../UEF/Apps
mv $UNZIP_DIR/Acorn\ Electron\ \[TOSEC\]/Acorn\ Electron\ -\ Operating\ Systems\ \(TOSEC-v2008-10-11_CM\)/* $SOFTWARE_DIR/../ROMS
mv $UNZIP_DIR/Elk-PubGameADF/*/* "$SOFTWARE_DIR/../ADF"
mv $UNZIP_DIR/Elk-PubGameDFS/*/* "$SOFTWARE_DIR/../DFS"
mv $UNZIP_DIR/Elk-PubGameHFE/*/* "$SOFTWARE_DIR/../HFE"

echo "Build complete."