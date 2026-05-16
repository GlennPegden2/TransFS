# RetroNAS PR Export

This document describes the Docker Compose profile for exporting TransFS installation artifacts ready for submission to the RetroNAS project.

## Purpose

TransFS has standalone and Docker runtime paths, but RetroNAS integration requires a reusable artifact bundle containing only the files intended for the RetroNAS project.

The `retronas-pr-export` profile produces that clean bundle without starting the normal TransFS runtime stack.

## Structure

All PR-ready source files are located in:

- `platform/linux/retronas-pr/` - Files destined for RetroNAS project submission

This is distinct from `platform/docker/retronas-testbed/` which contains local Docker integration code.

## Compose profile

Profile name:

- `retronas-pr-export`

Service:

- `retronas-pr-export`

## Run it

From the repository root:

```bash
docker compose --profile retronas-pr-export up --build retronas-pr-export
```

If you want to force one-shot execution with automatic cleanup:

```bash
docker compose --profile retronas-pr-export run --rm retronas-pr-export
```

Do not use detached runtime startup for this workflow (for example `up -d --build` without specifying the service), because that command pattern is intended for long-running runtime stacks.

Artifacts are written to:

- `artifacts/retronas-pr/transfs-retronas-installer/`
- `artifacts/retronas-pr/transfs-retronas-installer.tar.gz`

## What gets exported

- `platform/linux/configure_retronas.sh`
- `platform/linux/start_transfs_retronas.sh`
- `platform/linux/transfs-retronas.service`
- `platform/linux/retronas-pr/register_transfs_menu.sh`
- `platform/linux/retronas-pr/ansible/install_transfs.yml`
- `platform/linux/retronas-pr/ansible/inventory.example.ini`
- `platform/linux/retronas-pr/ansible/templates/transfs-retronas.service.j2`
- `platform/linux/retronas-pr/ansible/templates/transfs-retronas.env.j2`

The exported playbook defaults to:

- `https://github.com/GlennPegden2/TransFS.git`

This can still be overridden at playbook runtime with Ansible vars.

## Menu registration

To make TransFS appear in RetroNAS `Install` menu after artifacts are copied into a RetroNAS instance, run:

```bash
./platform/linux/retronas/register_transfs_menu.sh
```

The script patches RetroNAS `config/menu/install.json` only when `transfs` is missing, so it is safe to re-run after upgrades or container rebuilds.

## Notes

- This profile is intentionally separate from operational and development TransFS runtime containers.
- Files are suitable for submission to the RetroNAS project as a PR.
- See [RETRONAS_TESTBED_SETUP.md](RETRONAS_TESTBED_SETUP.md) for local Docker testing workflows.
