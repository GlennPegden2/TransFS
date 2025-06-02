#!/bin/bash
# filepath: bootstrap.sh
#
# Bootstrap script for TransFS native run prerequisites
#
# Requirements:
#   - Linux (FUSE support)
#   - Python 3.9+
#   - fuse3 (or libfuse)
#   - Samba (smbd)
#   - uvicorn
#   - tar
#   - unzip
#   - guestfish

# An array of required commands
REQUIRED_CMDS=(python3 fusermount smbd uvicorn tar unzip guestfish p7zip)

MISSING=()

echo "Checking system dependencies..."
for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
        MISSING+=("$cmd")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "ERROR: The following required tools are missing: ${MISSING[@]}"
    if command -v apt-get &>/dev/null; then
        echo "Suggestion for Debian/Ubuntu:"
        echo "  sudo apt-get update && sudo apt-get install -y fuse3 samba tar unzip guestfs"
    else
        echo "Please install the missing tools using your system's package manager."
    fi
    exit 1
fi

# Check for Python version (3.9 or higher)
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Detected Python version: $PYTHON_VERSION"
# Using the sort version trick to compare versions:
if [[ $(printf '%s\n' "3.9" "$PYTHON_VERSION" | sort -V | head -n1) != "3.9" ]]; then
    echo "ERROR: Python 3.9 or higher is required."
    exit 1
fi

echo "✅ All system dependencies are present."

# Optional: Check that mount points exist with proper permissions
for dir in /mnt/transfs /mnt/filestorefs; do
    if [ ! -d "$dir" ]; then
        echo "Creating mount point: $dir"
        sudo mkdir -p "$dir"
        sudo chmod 777 "$dir"
    fi
done

echo "Environment is ready to run TransFS."
# To run TransFS, you might execute:
# sudo python3 transfs.py /mnt/transfs /mnt/filestorefs