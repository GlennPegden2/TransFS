# RetroNAS Ansible Skeleton

This folder contains a first-pass playbook skeleton for installing TransFS in a RetroNAS bare-metal flow.

## Files

- `install_transfs.yml`: Main playbook.
- `templates/transfs-retronas.service.j2`: systemd unit template.
- `templates/transfs-retronas.env.j2`: runtime environment file for service.

The installer now supports two runtime activation paths:

- Bare-metal RetroNAS hosts with `systemctl`: deploy and enable `transfs-retronas.service`.
- Non-systemd environments such as the RetroNAS Docker testbed: start TransFS directly via `platform/linux/transfs_retronas_ctl.sh`.

## Usage example

RetroNAS menu-driven installs run this playbook locally on the RetroNAS host, so the
default target is `localhost` with a local Ansible connection.

For a manual remote Ansible run, override the target host group and connection type:

```bash
cp inventory.example.ini inventory.ini
ansible-playbook -i inventory.ini install_transfs.yml \
	-e transfs_target_hosts=retronas_hosts \
	-e transfs_connection=ssh
```

## Post-deploy smoke check

After deployment, verify the runtime and resolved ports:

```bash
ssh root@<host> "if command -v systemctl >/dev/null 2>&1; then systemctl is-active transfs-retronas; else /opt/transfs/platform/linux/transfs_retronas_ctl.sh status; fi && curl -fsS http://127.0.0.1:8000/api/runtime/ports"
```

## Key variables

- `transfs_repo_url`
- `transfs_repo_version`
- `transfs_install_root`
- `transfs_smb_mode`
- `transfs_smb_preferred_port`
- `transfs_smb_fallback_ports`
- `transfs_web_host`
- `transfs_web_preferred_port`
- `transfs_web_fallback_ports`
- `transfs_enable_port_auto_claim`

## Notes

- Default `transfs_smb_mode` is `retronas_managed`.
- If `transfs_smb_mode` is `transfs_managed`, the playbook installs Samba and the runtime may control `smbd`/`nmbd`.
- The playbook executes `platform/linux/configure_retronas.sh` to apply runtime port and mode settings into `app/config/app.yaml`.
- The portable control path is intended for containers and other environments without PID 1 systemd; it is also what the RetroNAS testbed exercises.
