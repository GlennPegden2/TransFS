# RetroNAS Artifact Build Profile

This document describes the optional Docker Compose profile for generating RetroNAS installation artifacts from this repository.

## Why this exists

TransFS has standalone and Docker runtime paths, but RetroNAS integration needs a reusable artifact bundle that can be consumed by RetroNAS Ansible workflows.

The `retronas-artifacts` profile produces that bundle without starting the normal TransFS runtime stack.

## Compose profile

Profile name:

- `retronas-artifacts`

Service:

- `retronas-artifacts`

## Run it

From the repository root:

```bash
docker compose --profile retronas-artifacts up --build retronas-artifacts
```

If you want to force one-shot execution with automatic cleanup:

```bash
docker compose --profile retronas-artifacts run --rm retronas-artifacts
```

Do not use detached runtime startup for this workflow (for example `up -d --build` without specifying the service), because that command pattern is intended for long-running runtime stacks.

Artifacts are written to:

- `artifacts/retronas/transfs-retronas-installer/`
- `artifacts/retronas/transfs-retronas-installer.tar.gz`

## What gets exported

- `platform/linux/configure_retronas.sh`
- `platform/linux/start_transfs_retronas.sh`
- `platform/linux/transfs-retronas.service`
- `platform/linux/retronas/register_transfs_menu.sh`
- `platform/linux/retronas/ansible/install_transfs.yml`
- `platform/linux/retronas/ansible/inventory.example.ini`
- `platform/linux/retronas/ansible/templates/transfs-retronas.service.j2`
- `platform/linux/retronas/ansible/templates/transfs-retronas.env.j2`

The exported playbook defaults to:

- `https://github.com/GlennPegden2/TransFS.git`

This can still be overridden at playbook runtime with Ansible vars.

## Persistent RetroNAS menu integration

To make TransFS appear in RetroNAS `Install` menu after artifacts are copied into a RetroNAS instance, run:

```bash
./platform/linux/retronas/register_transfs_menu.sh
```

The script patches RetroNAS `config/menu/install.json` only when `transfs` is missing, so it is safe to re-run after upgrades or container rebuilds.

## Notes

- This profile is intentionally separate from operational and development TransFS runtime containers.
- It is intended for integration/testing workflows where RetroNAS install artifacts are needed on demand.