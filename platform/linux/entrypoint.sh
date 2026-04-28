#!/bin/bash
set -e

cleanup() {
    echo 'Shutting down TransFS...'
    [ -n "$UVICORN_PID" ] && kill "$UVICORN_PID" 2>/dev/null || true
    service smbd stop 2>/dev/null || true
    service nmbd stop 2>/dev/null || true
    pkill -f 'python3 -m transfs' 2>/dev/null || true
    pkill -f 'debugpy.*transfs' 2>/dev/null || true
    sleep 2
    fusermount3 -uz /mnt/transfs 2>/dev/null || umount -l /mnt/transfs 2>/dev/null || true
    exit 0
}

trap cleanup TERM INT

mkdir -p /mnt/filestorefs
mkdir -p /mnt/filestorefs/.transfs_logs

python3 -c "import sys; sys.path.insert(0, '/app'); from smb_config import setup_samba_from_config; import yaml; config = yaml.safe_load(open('/app/config/app.yaml')); setup_samba_from_config(config)"

echo 'Starting FUSE filesystem...'
if [ "$DEBUG_MODE" = "1" ]; then
    echo 'Starting in debug mode...'
    python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /app/transfs.py 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/transfs.log &
else
    echo 'Starting in normal mode...'
    python3 -m transfs 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/transfs.log &
fi

echo 'Starting SMB services...'
service smbd start
service nmbd start

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

WEB_PORT=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/transfs.yaml'))['web_api']['port'])" 2>/dev/null || echo "8000")
WEB_HOST=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/transfs.yaml'))['web_api']['host'])" 2>/dev/null || echo "0.0.0.0")
echo "Starting FastAPI web service on ${WEB_HOST}:${WEB_PORT}..."
uvicorn main:app --host "${WEB_HOST}" --port "${WEB_PORT}" 2>&1 | tee -a /mnt/filestorefs/.transfs_logs/web.log &
UVICORN_PID=$!

wait $UVICORN_PID
