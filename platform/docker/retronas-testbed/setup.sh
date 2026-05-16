#!/bin/bash
set -euo pipefail

# RetroNAS testbed setup script
# Prepares a TransFS testbed environment for integration with retronas-docker
# Usage:
#   ./setup.sh [retronas_docker_path]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RETRONAS_DOCKER_PATH="${1:-${RETRONAS_DOCKER_PATH:-}}"

if [ -z "${RETRONAS_DOCKER_PATH}" ]; then
  echo "Error: retronas-docker path not provided"
  echo "Usage: ./setup.sh [/path/to/retronas-docker]"
  echo ""
  echo "To use a git submodule:"
  echo "  cd ${REPO_ROOT}"
  echo "  git submodule add https://github.com/YOUR_FORK/retronas-docker.git retronas-docker"
  echo "  platform/docker/retronas-testbed/setup.sh ./retronas-docker"
  exit 1
fi

if [ ! -d "${RETRONAS_DOCKER_PATH}" ]; then
  echo "Error: retronas-docker path not found: ${RETRONAS_DOCKER_PATH}"
  exit 1
fi

echo "Setting up RetroNAS testbed..."
echo "TransFS repo: ${REPO_ROOT}"
echo "RetroNAS Docker: ${RETRONAS_DOCKER_PATH}"

# Step 1: Build PR export artifacts
echo ""
echo "Step 1: Exporting RetroNAS PR artifacts..."
cd "${REPO_ROOT}"
bash platform/linux/retronas-pr/build_retronas_pr_export.sh artifacts/retronas-testbed/pr-artifacts

# Step 2: Copy PR artifacts into retronas-docker
echo ""
echo "Step 2: Injecting TransFS artifacts into retronas-docker..."
if [ -d "${RETRONAS_DOCKER_PATH}/ansible" ]; then
  cp artifacts/retronas-testbed/pr-artifacts/transfs-retronas-installer/platform/linux/retronas/ansible/install_transfs.yml \
    "${RETRONAS_DOCKER_PATH}/ansible/"
  cp -r artifacts/retronas-testbed/pr-artifacts/transfs-retronas-installer/platform/linux/retronas/ansible/templates/* \
    "${RETRONAS_DOCKER_PATH}/ansible/templates/" 2>/dev/null || true
  echo "  ✓ Copied Ansible playbook and templates"
fi

if [ -d "${RETRONAS_DOCKER_PATH}/scripts" ]; then
  cp artifacts/retronas-testbed/pr-artifacts/transfs-retronas-installer/platform/linux/retronas/register_transfs_menu.sh \
    "${RETRONAS_DOCKER_PATH}/scripts/" || true
  chmod +x "${RETRONAS_DOCKER_PATH}/scripts/register_transfs_menu.sh" 2>/dev/null || true
  echo "  ✓ Copied menu registration script"
fi

cp "${REPO_ROOT}/platform/docker/retronas-testbed/docker-compose.override.yml" \
  "${RETRONAS_DOCKER_PATH}/docker-compose.transfs-testbed.yml"
echo "  ✓ Copied docker-compose.transfs-testbed.yml (postgres + FUSE runtime settings)"

# Step 3: Provide next steps
echo ""
echo "Setup complete! Next steps:"
echo ""
echo "1. Build retronas-docker with injected TransFS files:"
echo "   cd ${RETRONAS_DOCKER_PATH}"
echo "   docker build -t retronas:testbed ."
echo ""
echo "2. Start testbed services with postgres + FUSE runtime settings:"
echo "   docker compose -f docker-compose.yml -f docker-compose.transfs-testbed.yml --profile retronas-testbed up -d"
echo ""
echo "3. Attach to RetroNAS container shell/menu:"
echo "   docker exec -it retronas-testbed /bin/bash"
echo ""
echo "4. Inside RetroNAS menu, select option 3 (Install) and TransFS should appear"
echo ""
