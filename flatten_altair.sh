#!/bin/bash

echo "=== PHASE 2.6: FLATTENING ALTAIR8800 FOLDER STRUCTURE ==="
echo ""
echo "Step 1: Verify backup exists"
cd /mnt/filestorefs/Native/MITS/Altair8800
ls -lh Software.tar.gz
echo ""

echo "Step 2: Create flat structure in temporary directory"
mkdir -p Software_flat
cd Software_flat

echo "  Copying files from extension folders..."
for dir in BAS BIN CAS DSK HEX TAP Collections; do
  if [ -d "../Software/$dir" ]; then
    echo "  - Copying from $dir/"
    cp "../Software/$dir"/* . 2>/dev/null || true
  fi
done

echo ""
echo "Step 3: Verify file count"
flat_count=$(find . -maxdepth 1 -type f 2>/dev/null | wc -l)
echo "  Files in flat: $flat_count"

orig_count=$(find ../Software -maxdepth 1 -type f 2>/dev/null | wc -l)
echo "  Files in original Software: $orig_count"

# Count files in Software folders
folder_count=$(find ../Software -maxdepth 2 -type f 2>/dev/null | wc -l)
echo "  Total files in Software (all folders): $folder_count"

if [ "$flat_count" -gt 0 ] && [ "$flat_count" -eq "$folder_count" ]; then
  echo "  ✓ File counts match!"
else
  echo "  ✗ File count check: flat=$flat_count, total=$folder_count"
fi

echo ""
echo "Step 4: Atomic replace (rename)"
cd /mnt/filestorefs/Native/MITS/Altair8800
mv Software Software_old
mv Software_flat Software

echo ""
echo "Step 5: Verify new structure"
echo "  Directories in /Software/: $(find Software -maxdepth 1 -type d 2>/dev/null | wc -l)"
echo "  Files in /Software/: $(find Software -maxdepth 1 -type f 2>/dev/null | wc -l)"
echo ""
echo "  First 10 files:"
ls -1 Software | head -10

echo ""
echo "✅ Flattening complete!"
