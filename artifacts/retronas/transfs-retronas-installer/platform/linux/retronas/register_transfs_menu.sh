#!/bin/bash
set -euo pipefail

# Registers TransFS as an experimental RetroNAS menu item.
# Usage:
#   ./register_transfs_menu.sh [experimental_menu_json] [ansible_dir]

MENU_JSON="${1:-/opt/retronas/config/menu/experimental.json}"
ANSIBLE_DIR="${2:-/opt/retronas/ansible}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed."
  exit 1
fi

if [ ! -f "${MENU_JSON}" ]; then
  echo "Error: experimental menu JSON not found: ${MENU_JSON}"
  exit 1
fi

if [ ! -f "${ANSIBLE_DIR}/install_transfs.yml" ]; then
  echo "Error: expected playbook not found: ${ANSIBLE_DIR}/install_transfs.yml"
  echo "Copy install_transfs.yml into RetroNAS ansible directory before registering the menu item."
  exit 1
fi

if jq -e '.menu.items[] | select(.id == "transfs" or .command == "transfs")' "${MENU_JSON}" >/dev/null; then
  echo "TransFS menu entry already present. No changes made."
  exit 0
fi

MAX_INDEX="$(jq -r '.menu.items[]?.index // "00"' "${MENU_JSON}" | sed 's/^0*//' | awk 'NF==0{print 0; next}{print $1}' | sort -n | tail -1)"
NEXT_INDEX_NUM=$((MAX_INDEX + 1))
NEXT_INDEX="$(printf '%02d' "${NEXT_INDEX_NUM}")"

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

jq --arg index "${NEXT_INDEX}" '
  .menu.items += [
    {
      "index": $index,
      "title": "transfs",
      "description": "TransFS virtual filesystem and multi-client content server",
      "id": "transfs",
      "prompt": "Install",
      "type": "install",
      "group": "",
      "command": "transfs",
      "args": ""
    }
  ]
' "${MENU_JSON}" > "${TMP_FILE}"

mv "${TMP_FILE}" "${MENU_JSON}"
echo "Registered TransFS in RetroNAS experimental menu with index ${NEXT_INDEX}."