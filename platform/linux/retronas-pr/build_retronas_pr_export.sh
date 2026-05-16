#!/bin/bash
set -euo pipefail

# Export RetroNAS-ready installation artifacts from TransFS for PR submission to RetroNAS project.
# This script generates a clean bundle containing only the files intended for the RetroNAS project,
# separate from any testbed/integration-specific code.
# Usage:
#   ./build_retronas_pr_export.sh [output_dir]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OUT_DIR="${1:-${RETRONAS_PR_EXPORT_OUT:-${REPO_ROOT}/artifacts/retronas-pr}}"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

BUNDLE_DIR="${WORK_DIR}/transfs-retronas-installer"

mkdir -p "${BUNDLE_DIR}/platform/linux/retronas/ansible/templates"
mkdir -p "${OUT_DIR}"

cp "${REPO_ROOT}/platform/linux/configure_retronas.sh" "${BUNDLE_DIR}/platform/linux/"
cp "${REPO_ROOT}/platform/linux/start_transfs_retronas.sh" "${BUNDLE_DIR}/platform/linux/"
cp "${REPO_ROOT}/platform/linux/transfs_retronas_ctl.sh" "${BUNDLE_DIR}/platform/linux/"
cp "${REPO_ROOT}/platform/linux/transfs-retronas.service" "${BUNDLE_DIR}/platform/linux/"
cp "${REPO_ROOT}/platform/linux/retronas-pr/register_transfs_menu.sh" "${BUNDLE_DIR}/platform/linux/retronas/"

cp "${REPO_ROOT}/platform/linux/retronas-pr/ansible/install_transfs.yml" "${BUNDLE_DIR}/platform/linux/retronas/ansible/"
cp "${REPO_ROOT}/platform/linux/retronas-pr/ansible/inventory.example.ini" "${BUNDLE_DIR}/platform/linux/retronas/ansible/"
cp "${REPO_ROOT}/platform/linux/retronas-pr/ansible/README.md" "${BUNDLE_DIR}/platform/linux/retronas/ansible/"
cp "${REPO_ROOT}/platform/linux/retronas-pr/ansible/templates/transfs-retronas.service.j2" "${BUNDLE_DIR}/platform/linux/retronas/ansible/templates/"
cp "${REPO_ROOT}/platform/linux/retronas-pr/ansible/templates/transfs-retronas.env.j2" "${BUNDLE_DIR}/platform/linux/retronas/ansible/templates/"

# Ensure bundle defaults point at the canonical TransFS repo.
sed -i 's#^\([[:space:]]*transfs_repo_url:[[:space:]]*\).*$#\1https://github.com/GlennPegden2/TransFS.git#' \
  "${BUNDLE_DIR}/platform/linux/retronas/ansible/install_transfs.yml"

cat > "${BUNDLE_DIR}/README.md" <<'EOF'
# TransFS RetroNAS Installer Bundle

This bundle contains RetroNAS-focused installation assets from the TransFS repository,
ready for submission to the RetroNAS project.

## Included assets

- platform/linux/configure_retronas.sh
- platform/linux/start_transfs_retronas.sh
- platform/linux/transfs_retronas_ctl.sh
- platform/linux/transfs-retronas.service
- platform/linux/retronas/register_transfs_menu.sh
- platform/linux/retronas/ansible/install_transfs.yml
- platform/linux/retronas/ansible/inventory.example.ini
- platform/linux/retronas/ansible/templates/transfs-retronas.service.j2
- platform/linux/retronas/ansible/templates/transfs-retronas.env.j2

## Default source repository

The generated playbook defaults to:

https://github.com/GlennPegden2/TransFS.git

Override via Ansible vars if needed:

-e transfs_repo_url=<your repo>
-e transfs_repo_version=<branch or tag>

## Register TransFS in RetroNAS Install menu

After copying the playbook/templates into a RetroNAS host, register the menu item:

./platform/linux/retronas/register_transfs_menu.sh

This is idempotent and only adds `transfs` if it is not already present.

## Runtime activation

On bare-metal RetroNAS hosts with systemd, the playbook deploys `transfs-retronas.service`.
In non-systemd environments such as the RetroNAS Docker testbed, it starts TransFS with
`platform/linux/transfs_retronas_ctl.sh` instead.
EOF

cp -R "${BUNDLE_DIR}" "${OUT_DIR}/"

ARCHIVE_PATH="${OUT_DIR}/transfs-retronas-installer.tar.gz"
tar -C "${WORK_DIR}" -czf "${ARCHIVE_PATH}" transfs-retronas-installer

echo "RetroNAS PR export artifacts: ${OUT_DIR}/transfs-retronas-installer"
echo "RetroNAS PR export archive: ${ARCHIVE_PATH}"
