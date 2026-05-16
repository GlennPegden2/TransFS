#!/bin/bash
set -euo pipefail


# Bare-metal and container startup runner for RetroNAS/systemd deployments.
# Ensures FUSE mountpoint and device are present, and provides clear diagnostics if not.

TRANSFS_ROOT="${TRANSFS_ROOT:-/opt/transfs}"
APP_DIR="${TRANSFS_APP_DIR:-${TRANSFS_ROOT}/app}"

LOG_DIR="${TRANSFS_LOG_DIR:-/var/log/transfs}"
PYTHON_BIN="${TRANSFS_PYTHON_BIN:-python3}"

mkdir -p "${LOG_DIR}"

# --- FUSE and mountpoint checks ---
MOUNTPOINT="$(${PYTHON_BIN} -c "from config import read_app_config; cfg=read_app_config() or {}; print(cfg.get('mountpoint', '/mnt/transfs'))" 2>/dev/null || echo "/mnt/transfs")"
if [ ! -d "${MOUNTPOINT}" ]; then
    echo "Creating FUSE mountpoint: ${MOUNTPOINT}"
    mkdir -p "${MOUNTPOINT}"
fi

if [ ! -c /dev/fuse ]; then
    echo "ERROR: /dev/fuse is missing. This container/host cannot run FUSE filesystems."
    echo "       Please run with --device /dev/fuse --cap-add SYS_ADMIN and ensure FUSE is enabled."
    exit 1
fi

# Runtime capability checks are enforced by the container launcher/compose profile.

cd "${APP_DIR}"

SMB_MANAGED=1
TRANSFS_PID=""
UVICORN_PID=""

have_systemctl() {
    command -v systemctl >/dev/null 2>&1
}

stop_samba_services() {
    if have_systemctl; then
        systemctl stop smbd 2>/dev/null || true
        systemctl stop nmbd 2>/dev/null || true
        return 0
    fi

    if command -v pkill >/dev/null 2>&1; then
        pkill -TERM smbd 2>/dev/null || true
        pkill -TERM nmbd 2>/dev/null || true
    fi
}

start_samba_services() {
    if have_systemctl; then
        systemctl start smbd
        systemctl start nmbd
        return 0
    fi

    if command -v smbd >/dev/null 2>&1; then
        smbd -D
    fi

    if command -v nmbd >/dev/null 2>&1; then
        nmbd -D
    fi
}

cleanup() {
    echo "Shutting down TransFS runtime..."
    [ -n "${UVICORN_PID}" ] && kill "${UVICORN_PID}" 2>/dev/null || true
    [ -n "${TRANSFS_PID}" ] && kill "${TRANSFS_PID}" 2>/dev/null || true
    if [ "${SMB_MANAGED}" = "1" ]; then
        stop_samba_services
    fi
    exit 0
}

trap cleanup TERM INT

SMB_MODE="$(${PYTHON_BIN} -c "import yaml; cfg=yaml.safe_load(open('config/app.yaml')) or {}; print((cfg.get('smb', {}) or {}).get('mode', 'transfs_managed'))" 2>/dev/null || echo "transfs_managed")"
if [ "${SMB_MODE}" != "transfs_managed" ]; then
    SMB_MANAGED=0
    echo "SMB management disabled for mode '${SMB_MODE}'"
fi

${PYTHON_BIN} -c "from config import read_app_config; from native_mounts import reconcile_mounts; cfg=read_app_config() or {}; entries=cfg.get('native_external_mounts', []) or []; reconcile_mounts(cfg, entries)"

if [ "${SMB_MANAGED}" = "1" ]; then
    ${PYTHON_BIN} -c "from config import read_app_config; from smb_config import setup_samba_from_config; cfg=read_app_config() or {}; setup_samba_from_config(cfg)"
fi


echo "Starting FUSE process..."
${PYTHON_BIN} -m transfs >> "${LOG_DIR}/transfs.log" 2>&1 &
TRANSFS_PID=$!

if [ "${SMB_MANAGED}" = "1" ]; then
    echo "Starting Samba services..."
    start_samba_services
else
    echo "Skipping Samba service startup (managed externally)"
fi

echo "Waiting for FUSE mount at ${MOUNTPOINT}..."
for i in $(seq 1 120); do
    if mountpoint -q "${MOUNTPOINT}"; then
        echo "FUSE mount ready"
        break
    fi
    sleep 1
done

if ! mountpoint -q "${MOUNTPOINT}"; then
    echo "WARNING: FUSE not mounted after timeout; continuing with Web API startup"
fi

WEB_PORT="$(${PYTHON_BIN} -c "from config import get_web_api_config; print(get_web_api_config().get('port', 8000))" 2>/dev/null || echo "8000")"
WEB_HOST="$(${PYTHON_BIN} -c "from config import get_web_api_config; print(get_web_api_config().get('host', '0.0.0.0'))" 2>/dev/null || echo "0.0.0.0")"

echo "Starting Web API on ${WEB_HOST}:${WEB_PORT}..."
${PYTHON_BIN} -m uvicorn main:app --host "${WEB_HOST}" --port "${WEB_PORT}" >> "${LOG_DIR}/web.log" 2>&1 &
UVICORN_PID=$!

wait "${UVICORN_PID}"
