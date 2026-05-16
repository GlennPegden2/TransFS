#!/bin/bash
set -euo pipefail

# Registers TransFS as an installable RetroNAS menu item.
# Usage:
#   ./register_transfs_menu.sh [install_menu_json] [ansible_dir]

MENU_JSON="${1:-/opt/retronas/config/menu/install.json}"
ANSIBLE_DIR="${2:-/opt/retronas/ansible}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed."
  exit 1
fi

if [ ! -f "${MENU_JSON}" ]; then
  echo "Error: install menu JSON not found: ${MENU_JSON}"
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

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

jq '
  .menu.items = (
    (
      .menu.items + [
        {
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
    )
    | sort_by((.title // .id // "") | ascii_downcase)
    | to_entries
    | map(
        .value + {
          "index": (
            (.key + 1)
            | tostring
            | if length < 2 then "0" + . else . end
          )
        }
      )
  )
' "${MENU_JSON}" > "${TMP_FILE}"

mv "${TMP_FILE}" "${MENU_JSON}"
TRANSFS_INDEX="$(jq -r '.menu.items[] | select(.id == "transfs") | .index' "${MENU_JSON}")"
echo "Registered TransFS in RetroNAS install menu with index ${TRANSFS_INDEX} (alphabetical order)."
