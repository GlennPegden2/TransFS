#!/bin/bash
set -euo pipefail

# Ensure TransFS installer artifacts are registered in RetroNAS menu when possible.
if [ -x /opt/retronas/scripts/register_transfs_menu.sh ] && [ -f /opt/retronas/ansible/install_transfs.yml ] && [ -f /opt/retronas/config/menu/install.json ]; then
  /opt/retronas/scripts/register_transfs_menu.sh || true
fi

exec /opt/retronas/docker-entrypoint.sh "$@"
