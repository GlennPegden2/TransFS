# RetroNAS Testbed Setup

This document describes how to set up a local Docker-based RetroNAS testbed for testing TransFS installation.

## Purpose

A testbed combines:
1. Your forked `retronas-docker` repository
2. TransFS PR-ready artifacts exported from this repository
3. Glue code to wire them together for integrated testing

This allows you to test the complete TransFS installation flow inside RetroNAS before submitting a PR to the main project.

## Prerequisites

- A fork of `retronas-docker` (you can use your own fork or clone the upstream)
- Docker and Docker Compose
- This TransFS repository

## Setup steps

### Step 1: Clone retronas-docker

If you haven't already, clone your fork or the upstream retronas-docker:

```bash
git clone https://github.com/YOUR_FORK/retronas-docker.git
# or
git clone https://github.com/retronas/retronas-docker.git
```

Or use a git submodule:

```bash
cd TransFS
git submodule add https://github.com/YOUR_FORK/retronas-docker.git retronas-docker
```

### Step 2: Prepare the testbed

From the TransFS repository root, run the testbed setup script:

```bash
bash platform/docker/retronas-testbed/setup.sh /path/to/retronas-docker
```

This will:
1. Export PR-ready artifacts via `retronas-pr-export` profile
2. Copy the artifacts into your retronas-docker clone
3. Provide next steps for building and testing

### Step 3: Build retronas-docker with TransFS

```bash
cd /path/to/retronas-docker
docker build -t retronas:testbed .
```

### Step 4: Run the testbed with postgres + FUSE support

```bash
cd /path/to/retronas-docker
docker compose -f docker-compose.yml -f docker-compose.transfs-testbed.yml --profile retronas-testbed up -d
docker exec -it retronas-testbed /bin/bash
```

This starts the RetroNAS menu system container plus a local postgres container on the same network.
The compose fragment also provides required FUSE runtime settings (`/dev/fuse`, `SYS_ADMIN`).

### Step 5: Test TransFS installation

Inside the RetroNAS menu:

1. Select option **3 - Install**
2. Look for **transfs** in the list
3. Select it and follow the installation prompts
4. The playbook will clone TransFS, install dependencies, and start the service

### Step 6: Verify installation

After installation completes, test TransFS:

```bash
# From inside the container:
curl -fsS http://127.0.0.1:8000/api/runtime/ports
systemctl status transfs-retronas
```

From your host (if you exposed ports):

```bash
curl -fsS http://localhost:8000/api/runtime/ports
```

## Directory structure

After setup, you'll have:

```
TransFS/
├── retronas-docker/                     ← Your retronas-docker clone/fork
├── platform/
│   ├── linux/
│   │   └── retronas-pr/                 ← PR-ready files
│   └── docker/
│       └── retronas-testbed/            ← Testbed glue code
├── artifacts/
│   ├── retronas-pr/                     ← PR export (for submission)
│   └── retronas-testbed/                ← Testbed artifacts (local testing)
└── ...
```

## Cleanup

To remove the testbed container and rebuild:

```bash
docker compose -f docker-compose.yml -f docker-compose.transfs-testbed.yml --profile retronas-testbed down
```

To start fresh with new artifacts:

```bash
rm -rf artifacts/retronas-testbed/
bash platform/docker/retronas-testbed/setup.sh /path/to/retronas-docker
cd /path/to/retronas-docker && docker build -t retronas:testbed .
docker compose -f docker-compose.yml -f docker-compose.transfs-testbed.yml --profile retronas-testbed up -d
```

## Troubleshooting

### Menu item not appearing

If TransFS doesn't appear in the Install menu, check that:
1. `install_transfs.yml` was copied to retronas-docker's `ansible/` directory
2. The retronas-docker image was rebuilt after copying files
3. The container can find `install_transfs.yml` at `/opt/retronas/ansible/install_transfs.yml`

### Installation failing

Check the ansible-playbook output for:
- Git clone errors (verify `transfs_repo_url` is accessible)
- Python dependencies missing (verify `requirements.txt` location)
- Service start failures (check logs with `journalctl -u transfs-retronas`)

### FUSE or database startup errors

If install succeeds but TransFS does not run:
1. Confirm you launched with the compose fragment (`docker-compose.transfs-testbed.yml`).
2. Check `/dev/fuse` is present in the container (`ls -l /dev/fuse`).
3. Check postgres is healthy (`docker ps` and `docker logs retronas-testbed-postgres`).
4. Check TransFS launcher logs (`/var/log/transfs/launcher.log`, `transfs.log`, `web.log`).

### Persistent testing

To preserve your testbed across rebuilds:

```bash
docker volume create retronas-testbed-data
docker run -it -v retronas-testbed-data:/opt/transfs --name retronas-testbed retronas:testbed ./retronas.sh
```

## Next steps

Once testing is successful:
1. Commit your changes to your retronas-docker fork
2. Submit a PR to the main retronas project with the TransFS integration

See [RETRONAS_PR_EXPORT.md](RETRONAS_PR_EXPORT.md) for details on PR artifact generation.
