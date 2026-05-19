"""Managed SMB/CIFS mounts inside Native storage.

This module mounts NAS shares into /mnt/filestorefs/Native subdirectories so they
are persisted via app config and can be managed from the web UI.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_EXTRA_OPT = re.compile(r"^[A-Za-z0-9._:-]+(=[^,\s]+)?$")


def _extract_option_value(entry: dict[str, Any], key: str) -> str:
    prefix = f"{key}="
    for raw_opt in (entry.get("extra_options") or []):
        opt = str(raw_opt or "").strip()
        if opt.lower().startswith(prefix.lower()):
            return opt.split("=", 1)[1].strip()
    return ""


def _smbclient_protocol(vers: str) -> str:
    value = (vers or "3.0").strip().lower()
    if value.startswith("3"):
        return "SMB3"
    if value.startswith("2"):
        return "SMB2"
    return "NT1"


def _classify_probe_error(text: str) -> tuple[str, str]:
    message = (text or "").strip()
    upper = message.upper()
    if "NT_STATUS_LOGON_FAILURE" in upper or "STATUS_LOGON_FAILURE" in upper:
        return "auth_failed", "Authentication failed"
    if "NT_STATUS_ACCESS_DENIED" in upper:
        return "access_denied", "Access denied"
    if "NT_STATUS_BAD_NETWORK_NAME" in upper:
        return "share_not_found", "Share not found"
    if "NT_STATUS_OBJECT_PATH_NOT_FOUND" in upper or "NT_STATUS_OBJECT_NAME_NOT_FOUND" in upper:
        return "path_not_found", "Remote path not found"
    if "NT_STATUS_IO_TIMEOUT" in upper or "NT_STATUS_HOST_UNREACHABLE" in upper or "NO ROUTE TO HOST" in upper:
        return "network_error", "Host reachable but SMB session failed at the network layer"
    if "CONNECTION TO" in upper and "FAILED" in upper:
        return "network_error", "Unable to connect to SMB service"
    return "unknown", "SMB probe failed"


def probe_entry(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Probe SMB access with smbclient for clearer diagnostics than mount.cifs provides."""
    smbclient_path = shutil.which("smbclient")
    if not smbclient_path:
        return {
            "success": False,
            "kind": "tool_unavailable",
            "summary": "SMB probe tool unavailable",
            "detail": "Install smbclient in the container image to enable auth/share/path probing.",
        }

    host = (entry.get("smb_host") or "").strip()
    share = (entry.get("smb_share") or "").strip().strip("/")
    subpath = (entry.get("smb_subpath") or "").strip().replace("\\", "/").strip("/")
    if not host or not share:
        raise ValueError("smb_host and smb_share are required for probe")

    cmd = [
        smbclient_path,
        f"//{host}/{share}",
        "-m",
        _smbclient_protocol(entry.get("vers", "3.0")),
    ]

    smb_port = entry.get("smb_port")
    if smb_port is not None and str(smb_port).strip() != "":
        cmd.extend(["-p", str(int(smb_port))])

    workgroup = _extract_option_value(entry, "domain") or _extract_option_value(entry, "workgroup")
    if workgroup:
        cmd.extend(["-W", workgroup])

    auth_temp_path = None
    try:
        if bool(entry.get("guest", False)):
            cmd.append("-N")
        else:
            username = (entry.get("username") or "").strip()
            password = entry.get("password")
            credentials_file = (entry.get("credentials_file") or "").strip()
            if password is None and credentials_file and os.path.exists(credentials_file):
                auth_file = credentials_file
            else:
                fd, auth_temp_path = tempfile.mkstemp(prefix="transfs-smbprobe-", suffix=".cred")
                os.close(fd)
                with open(auth_temp_path, "w", encoding="utf-8") as fh:
                    fh.write(f"username={username}\npassword={password or ''}\n")
                    if workgroup:
                        fh.write(f"domain={workgroup}\n")
                os.chmod(auth_temp_path, 0o600)
                auth_file = auth_temp_path
            cmd.extend(["-A", auth_file])

        if subpath:
            cmd.extend(["-D", subpath, "-c", "dir"])
        else:
            cmd.extend(["-c", "quit"])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        detail = (result.stderr or result.stdout or "").strip()
        if result.returncode == 0:
            summary = "Share accessible" if not subpath else "Share and remote path accessible"
            return {
                "success": True,
                "kind": "ok",
                "summary": summary,
                "detail": detail,
                "command": f"//{host}/{share}" + (f"/{subpath}" if subpath else ""),
            }

        kind, summary = _classify_probe_error(detail)
        return {
            "success": False,
            "kind": kind,
            "summary": summary,
            "detail": detail,
            "command": f"//{host}/{share}" + (f"/{subpath}" if subpath else ""),
        }
    finally:
        if auth_temp_path and os.path.exists(auth_temp_path):
            try:
                os.remove(auth_temp_path)
            except OSError:
                pass


def _safe_join(base: str, rel_path: str) -> str:
    base_abs = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base_abs, rel_path))
    if os.path.commonpath([base_abs, candidate]) != base_abs:
        raise ValueError(f"Path traversal detected: {rel_path}")
    return candidate


def normalize_target_subpath(target_subpath: str) -> str:
    """Normalize and validate a path under Native.

    Accepts either:
    - Systems/Panasonic/3DO/Software/Sources/Nas-Collection
    - Native/Systems/Panasonic/3DO/Software/Sources/Nas-Collection
    """
    value = (target_subpath or "").strip().replace("\\", "/").strip("/")
    if not value:
        raise ValueError("target_subpath is required")
    if value.lower().startswith("native/"):
        value = value[7:]
    path_obj = Path(value)
    if path_obj.is_absolute() or ".." in path_obj.parts:
        raise ValueError(f"Unsafe target_subpath: {target_subpath}")
    return str(path_obj.as_posix())


def resolve_target_path(config: dict[str, Any], target_subpath: str) -> str:
    filestore = config.get("filestore", "/data/retronas")
    native_base = os.path.join(filestore, "Native")
    normalized = normalize_target_subpath(target_subpath)
    return _safe_join(native_base, normalized)


def _mount_runtime_dir(config: dict[str, Any]) -> str:
    filestore = config.get("filestore", "/data/retronas")
    runtime_dir = os.path.join(filestore, ".transfs", "native-mounts")
    os.makedirs(runtime_dir, exist_ok=True)
    return runtime_dir


def _share_mount_path(config: dict[str, Any], entry: dict[str, Any]) -> str:
    mount_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(entry.get("id") or "mount"))
    return os.path.join(_mount_runtime_dir(config), mount_id, "share-root")


def build_share_unc_path(entry: dict[str, Any]) -> str:
    host = (entry.get("smb_host") or "").strip()
    share = (entry.get("smb_share") or "").strip().strip("/")
    if not host:
        raise ValueError("smb_host is required")
    if not share:
        raise ValueError("smb_share is required")
    return f"//{host}/{share}"


def build_unc_path(entry: dict[str, Any]) -> str:
    unc = build_share_unc_path(entry)
    subpath = (entry.get("smb_subpath") or "").strip().replace("\\", "/").strip("/")
    if subpath:
        unc = f"{unc}/{subpath}"
    return unc


def _parse_proc_mounts() -> list[tuple[str, str, str]]:
    mounts: list[tuple[str, str, str]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                src = parts[0].replace("\\040", " ")
                target = parts[1].replace("\\040", " ")
                fstype = parts[2]
                mounts.append((src, target, fstype))
    except FileNotFoundError:
        return []
    return mounts


def get_mount_status(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    target_path = resolve_target_path(config, entry.get("target_subpath", ""))
    mounted = False
    source = ""
    fstype = ""
    for src, target, fs_type in _parse_proc_mounts():
        if target == target_path:
            mounted = True
            source = src
            fstype = fs_type
            break

    return {
        "id": entry.get("id"),
        "enabled": bool(entry.get("enabled", True)),
        "target_subpath": normalize_target_subpath(entry.get("target_subpath", "")),
        "target_path": target_path,
        "smb_host": entry.get("smb_host", ""),
        "smb_share": entry.get("smb_share", ""),
        "smb_subpath": entry.get("smb_subpath", ""),
        "smb_port": entry.get("smb_port"),
        "username": entry.get("username", ""),
        "guest": bool(entry.get("guest", False)),
        "read_only": bool(entry.get("read_only", False)),
        "vers": entry.get("vers", "3.0"),
        "auto_reconnect": bool(entry.get("auto_reconnect", True)),
        "has_credentials": bool(entry.get("credentials_file")),
        "mounted": mounted,
        "mounted_source": source,
        "mounted_fstype": fstype,
        "last_error": entry.get("last_error", ""),
        "last_ok": entry.get("last_ok", 0),
        "last_checked": entry.get("last_checked", 0),
    }


def _build_mount_options(entry: dict[str, Any]) -> str:
    read_only = bool(entry.get("read_only", False))
    guest = bool(entry.get("guest", False))
    vers = (entry.get("vers") or "3.0").strip()

    opts = [
        "ro" if read_only else "rw",
        "iocharset=utf8",
        "uid=0",
        "gid=0",
        "file_mode=0664",
        "dir_mode=0775",
        "noserverino",
        "nounix",
        f"vers={vers}",
    ]

    smb_port = entry.get("smb_port")
    if smb_port is not None and str(smb_port).strip() != "":
        opts.append(f"port={int(smb_port)}")

    if guest:
        opts.append("guest")
    else:
        username = (entry.get("username") or "").strip()
        password = entry.get("password")
        credentials_file = (entry.get("credentials_file") or "").strip()
        if credentials_file and os.path.exists(credentials_file):
            with open(credentials_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("username="):
                        username = line.split("=", 1)[1].rstrip("\n")
                    elif line.startswith("password="):
                        password = line.split("=", 1)[1].rstrip("\n")
        if not username:
            raise ValueError("username is required when guest=false")
        if password is None:
            raise ValueError("password is required when guest=false")
        opts.append(f"username={username}")
        opts.append(f"password={password}")

    for raw_opt in (entry.get("extra_options") or []):
        opt = str(raw_opt or "").strip()
        if not opt:
            continue
        if not _ALLOWED_EXTRA_OPT.fullmatch(opt):
            raise ValueError(f"Invalid mount option: {opt}")
        opts.append(opt)

    return ",".join(opts)


def mount_entry(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    target_path = resolve_target_path(config, entry.get("target_subpath", ""))
    unc_path = build_unc_path(entry)
    share_unc_path = build_share_unc_path(entry)
    share_mount_path = _share_mount_path(config, entry)
    smb_subpath = (entry.get("smb_subpath") or "").strip().replace("\\", "/").strip("/")

    os.makedirs(target_path, exist_ok=True)
    os.makedirs(share_mount_path, exist_ok=True)

    current = get_mount_status(config, entry)
    if current.get("mounted"):
        return {
            "success": True,
            "changed": False,
            "message": "Already mounted",
            "target_path": target_path,
            "unc_path": unc_path,
        }

    mount_opts = _build_mount_options(entry)
    if smb_subpath:
        share_result = subprocess.run(
            ["mount", "-i", "-t", "cifs", share_unc_path, share_mount_path, "-o", mount_opts],
            capture_output=True,
            text=True,
            check=False,
        )
        if share_result.returncode != 0:
            error_text = (share_result.stderr or share_result.stdout or "mount failed").strip()
            logger.warning("Native share mount failed for %s: %s", entry.get("id"), error_text)
            probe = probe_entry(config, entry)
            return {
                "success": False,
                "changed": False,
                "error": error_text,
                "probe": probe,
                "target_path": target_path,
                "unc_path": unc_path,
            }

        bind_source = os.path.join(share_mount_path, *[part for part in smb_subpath.split("/") if part])
        if not os.path.exists(bind_source):
            subprocess.run(["umount", share_mount_path], capture_output=True, text=True, check=False)
            return {
                "success": False,
                "changed": False,
                "error": f"Remote subpath not found after share mount: {smb_subpath}",
                "probe": probe_entry(config, entry),
                "target_path": target_path,
                "unc_path": unc_path,
            }

        result = subprocess.run(
            ["mount", "--bind", bind_source, target_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            subprocess.run(["umount", share_mount_path], capture_output=True, text=True, check=False)
    else:
        result = subprocess.run(
            ["mount", "-i", "-t", "cifs", share_unc_path, target_path, "-o", mount_opts],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "mount failed").strip()
        logger.warning("Native mount failed for %s: %s", entry.get("id"), error_text)
        probe = probe_entry(config, entry)
        return {
            "success": False,
            "changed": False,
            "error": error_text,
            "probe": probe,
            "target_path": target_path,
            "unc_path": unc_path,
        }

    return {
        "success": True,
        "changed": True,
        "message": "Mounted",
        "target_path": target_path,
        "unc_path": unc_path,
    }


def unmount_entry(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    target_path = resolve_target_path(config, entry.get("target_subpath", ""))
    share_mount_path = _share_mount_path(config, entry)

    current = get_mount_status(config, entry)
    share_status = any(target == share_mount_path for _, target, _ in _parse_proc_mounts())
    changed = False

    if not current.get("mounted") and not share_status:
        return {
            "success": True,
            "changed": False,
            "message": "Already unmounted",
            "target_path": target_path,
        }

    if current.get("mounted"):
        result = subprocess.run(
            ["umount", target_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            lazy = subprocess.run(
                ["umount", "-l", target_path],
                capture_output=True,
                text=True,
                check=False,
            )
            if lazy.returncode != 0:
                error_text = (lazy.stderr or lazy.stdout or result.stderr or result.stdout or "umount failed").strip()
                logger.warning("Native unmount failed for %s: %s", entry.get("id"), error_text)
                return {
                    "success": False,
                    "changed": False,
                    "error": error_text,
                    "target_path": target_path,
                }
        changed = True

    if share_status:
        share_result = subprocess.run(["umount", share_mount_path], capture_output=True, text=True, check=False)
        if share_result.returncode != 0:
            subprocess.run(["umount", "-l", share_mount_path], capture_output=True, text=True, check=False)
        changed = True

    return {
        "success": True,
        "changed": changed,
        "message": "Unmounted",
        "target_path": target_path,
    }


def reconcile_mounts(config: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    mounted = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []

    for entry in entries:
        if not bool(entry.get("enabled", True)):
            skipped += 1
            details.append({"id": entry.get("id"), "success": True, "changed": False, "message": "Disabled"})
            continue
        if not bool(entry.get("auto_reconnect", True)):
            skipped += 1
            details.append({"id": entry.get("id"), "success": True, "changed": False, "message": "Auto reconnect disabled"})
            continue

        result = mount_entry(config, entry)
        result["id"] = entry.get("id")
        details.append(result)
        if result.get("success"):
            if result.get("changed"):
                mounted += 1
            else:
                skipped += 1
        else:
            failed += 1

    return {
        "success": failed == 0,
        "mounted": mounted,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


def write_credentials_file(filestore: str, mount_id: str, username: str, password: str) -> str:
    """Write SMB credentials to a persisted file under filestore.

    The resulting file path is safe to store in app config.
    """
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", (mount_id or "mount").strip())
    safe_user = (username or "").strip()
    if not safe_user:
        raise ValueError("username is required when guest=false")

    secret_dir = os.path.join(filestore, ".secrets", "transfs", "native-mounts")
    os.makedirs(secret_dir, exist_ok=True)
    credentials_path = os.path.join(secret_dir, f"{clean_id}.cred")

    payload = f"username={safe_user}\npassword={password or ''}\n"
    fd = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
    finally:
        try:
            os.chmod(credentials_path, 0o600)
        except OSError:
            pass

    return credentials_path
