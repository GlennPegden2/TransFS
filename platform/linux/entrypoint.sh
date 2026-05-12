#!/bin/bash
set -e

SMB_MANAGED=1

cleanup() {
    echo 'Shutting down TransFS...'
    [ -n "$UVICORN_PID" ] && kill "$UVICORN_PID" 2>/dev/null || true
    if [ "$SMB_MANAGED" = "1" ]; then
        service smbd stop 2>/dev/null || true
        service nmbd stop 2>/dev/null || true
    fi
    pkill -f 'python3 -m transfs' 2>/dev/null || true
    pkill -f 'debugpy.*transfs' 2>/dev/null || true
    sleep 2
    fusermount3 -uz /mnt/transfs 2>/dev/null || umount -l /mnt/transfs 2>/dev/null || true
    exit 0
}

trap cleanup TERM INT

mkdir -p /mnt/filestorefs
mkdir -p /mnt/filestorefs/.transfs_logs

SMB_MODE=$(python3 -c "import yaml; cfg=yaml.safe_load(open('/app/config/app.yaml')) or {}; print((cfg.get('smb', {}) or {}).get('mode', 'transfs_managed'))" 2>/dev/null || echo "transfs_managed")
if [ "$SMB_MODE" != "transfs_managed" ]; then
    SMB_MANAGED=0
    echo "SMB management disabled for mode '$SMB_MODE'"
fi

python3 -c "import sys; sys.path.insert(0, '/app'); from native_mounts import reconcile_mounts; import yaml; cfg = yaml.safe_load(open('/app/config/app.yaml')) or {}; entries = cfg.get('native_external_mounts', []) or []; reconcile_mounts(cfg, entries)"

if [ "$SMB_MANAGED" = "1" ]; then
    python3 -c "import sys; sys.path.insert(0, '/app'); from smb_config import setup_samba_from_config; import yaml; config = yaml.safe_load(open('/app/config/app.yaml')); setup_samba_from_config(config)"
fi

echo 'Starting FUSE filesystem...'
if [ "$DEBUG_MODE" = "1" ]; then
    echo 'Starting in debug mode...'
    python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /app/transfs.py 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/transfs.log &
else
    echo 'Starting in normal mode...'
    python3 -m transfs 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/transfs.log &
fi

if [ "$SMB_MANAGED" = "1" ]; then
    echo 'Starting SMB services...'
    service smbd start
    service nmbd start
else
    echo 'Skipping SMB service startup (managed externally)'
fi

echo 'Waiting for FUSE mount...'
for i in $(seq 1 120); do
    if mountpoint -q /mnt/transfs; then
        echo 'FUSE mount ready'
        break
    fi
    sleep 1
done

if ! mountpoint -q /mnt/transfs; then
    echo 'WARNING: FUSE not mounted after 120 seconds; continuing with SMB/Web startup'
fi

WEB_PORT=$(python3 -c "import sys; sys.path.insert(0, '/app'); from config import get_web_api_config; print(get_web_api_config().get('port', 8000))" 2>/dev/null || echo "8000")
WEB_HOST=$(python3 -c "import sys; sys.path.insert(0, '/app'); from config import get_web_api_config; print(get_web_api_config().get('host', '0.0.0.0'))" 2>/dev/null || echo "0.0.0.0")
echo "Starting FastAPI web service on ${WEB_HOST}:${WEB_PORT}..."
uvicorn main:app --host "${WEB_HOST}" --port "${WEB_PORT}" 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/web.log &
UVICORN_PID=$!

wait $UVICORN_PID
