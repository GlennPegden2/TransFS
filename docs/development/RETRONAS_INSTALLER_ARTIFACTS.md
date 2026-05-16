# RetroNAS Installer Artifacts (Phase 3)

This document describes the first-pass artifacts added to support a RetroNAS contributed installer.

## Added files

- `platform/linux/configure_retronas.sh`
- `platform/linux/start_transfs_retronas.sh`
- `platform/linux/transfs-retronas.service`
- `platform/linux/retronas/ansible/install_transfs.yml`
- `platform/linux/retronas/ansible/inventory.example.ini`
- `platform/linux/retronas/ansible/templates/transfs-retronas.service.j2`
- `platform/linux/retronas/ansible/templates/transfs-retronas.env.j2`

## Intended installer flow

1. Deploy repository to target path (recommended: `/opt/transfs`).
2. Ensure Linux dependencies are present (`fuse3`, Python runtime, and optional Samba packages if using `transfs_managed` mode).
3. Run config helper:

```bash
/opt/transfs/platform/linux/configure_retronas.sh
```

4. Install and enable service:

```bash
cp /opt/transfs/platform/linux/transfs-retronas.service /etc/systemd/system/transfs-retronas.service
chmod +x /opt/transfs/platform/linux/start_transfs_retronas.sh
chmod +x /opt/transfs/platform/linux/configure_retronas.sh
systemctl daemon-reload
systemctl enable --now transfs-retronas.service
```

## Included Ansible skeleton

An initial playbook skeleton is included in `platform/linux/retronas/ansible/` to accelerate integration into the RetroNAS repo.

Example:

```bash
cd /opt/transfs/platform/linux/retronas/ansible
cp inventory.example.ini inventory.ini
ansible-playbook -i inventory.ini install_transfs.yml
```

The playbook:

- Installs base dependencies (`git`, `python3`, `fuse3`, optional `samba` for `transfs_managed`).
- Clones/updates repository content.
- Deploys `/etc/default/transfs-retronas` and `/etc/systemd/system/transfs-retronas.service`.
- Executes `configure_retronas.sh` with playbook variables.
- Enables and starts `transfs-retronas.service`.

Smoke verification after playbook run:

```bash
ssh root@<host> "systemctl is-active transfs-retronas && curl -fsS http://127.0.0.1:8000/api/runtime/ports"
```

## Key environment variables for playbook customization

### configure_retronas.sh

- `TRANSFS_APP_DIR`
- `TRANSFS_CONFIG_PATH`
- `TRANSFS_SMB_MODE` (`retronas_managed`, `transfs_managed`, `disabled`)
- `TRANSFS_SMB_PREFERRED_PORT`
- `TRANSFS_SMB_FALLBACK_PORTS` (comma-separated)
- `TRANSFS_SMB_STRICT_STANDARD_PORT` (`true`/`false`)
- `TRANSFS_WEB_HOST`
- `TRANSFS_WEB_PREFERRED_PORT`
- `TRANSFS_WEB_FALLBACK_PORTS` (comma-separated)
- `TRANSFS_WEB_STRICT_STANDARD_PORT` (`true`/`false`)
- `TRANSFS_ENABLE_PORT_AUTO_CLAIM` (`true`/`false`)
- `TRANSFS_RUNTIME_PROFILE`

### start_transfs_retronas.sh

- `TRANSFS_ROOT`
- `TRANSFS_APP_DIR`
- `TRANSFS_LOG_DIR`
- `TRANSFS_PYTHON_BIN`

## Notes

- Default mode in this flow should be `retronas_managed` for Samba ownership on RetroNAS hosts.
- If `transfs_managed` mode is selected, startup script will attempt Samba setup and `smbd`/`nmbd` service control.
- Resolved runtime status can be queried via API endpoint: `/api/runtime/ports`.
