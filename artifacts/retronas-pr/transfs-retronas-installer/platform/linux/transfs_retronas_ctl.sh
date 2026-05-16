#!/bin/bash
set -euo pipefail

ACTION="${1:-start}"
ENV_FILE="${TRANSFS_ENV_FILE:-/etc/default/transfs-retronas}"

if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
fi

TRANSFS_ROOT="${TRANSFS_ROOT:-/opt/transfs}"
START_SCRIPT="${TRANSFS_START_SCRIPT:-${TRANSFS_ROOT}/platform/linux/start_transfs_retronas.sh}"
PID_FILE="${TRANSFS_PID_FILE:-/var/run/transfs-retronas.pid}"
LOG_DIR="${TRANSFS_LOG_DIR:-/var/log/transfs}"
LAUNCH_LOG="${TRANSFS_CTL_LOG:-${LOG_DIR}/launcher.log}"

mkdir -p "$(dirname "${PID_FILE}")" "${LOG_DIR}"

read_pid() {
    if [ -f "${PID_FILE}" ]; then
        cat "${PID_FILE}"
    fi
}

is_running() {
    local pid
    pid="$(read_pid)"
    [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null
}

clear_stale_pid() {
    if [ -f "${PID_FILE}" ] && ! is_running; then
        rm -f "${PID_FILE}"
    fi
}

start_service() {
    clear_stale_pid
    if is_running; then
        echo "TransFS already running with PID $(read_pid)"
        return 0
    fi

    if [ ! -x "${START_SCRIPT}" ]; then
        echo "TransFS start script is missing or not executable: ${START_SCRIPT}" >&2
        return 1
    fi

    nohup "${START_SCRIPT}" >> "${LAUNCH_LOG}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${PID_FILE}"

    sleep 1
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "TransFS failed to start; see ${LAUNCH_LOG}" >&2
        rm -f "${PID_FILE}"
        return 1
    fi

    echo "Started TransFS with PID ${pid}"
}

stop_service() {
    clear_stale_pid
    if ! is_running; then
        echo "TransFS is not running"
        return 0
    fi

    local pid
    pid="$(read_pid)"
    kill "${pid}" 2>/dev/null || true

    for _ in $(seq 1 30); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${PID_FILE}"
            echo "Stopped TransFS"
            return 0
        fi
        sleep 1
    done

    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${PID_FILE}"
    echo "Force-stopped TransFS"
}

status_service() {
    clear_stale_pid
    if is_running; then
        echo "TransFS is running with PID $(read_pid)"
        return 0
    fi

    echo "TransFS is not running"
    return 1
}

case "${ACTION}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        stop_service
        start_service
        ;;
    status)
        status_service
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}" >&2
        exit 2
        ;;
esac