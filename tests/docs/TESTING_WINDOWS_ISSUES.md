# TransFS Testing - Windows-Specific Issues & Solutions

## Issue: "TransFS volume not mounted - ensure Docker container is running"

### Root Cause

On **Windows hosts**, FUSE filesystems running inside Docker containers **cannot be directly accessed** from the Windows filesystem via bind mounts. This is because:

1. **FUSE is a Linux kernel feature** - it doesn't exist on Windows
2. **Docker on Windows** uses a Linux VM (WSL2 or Hyper-V)
3. **Bind-mounted directories** (like `./transfs:/mnt/transfs`) work for regular files but **not for FUSE mounts**
4. The FUSE mount exists only inside the container's kernel namespace

### Visual Explanation

```
┌─────────────────────────────────────────────────────────┐
│                    Windows Host                          │
│                                                          │
│  D:\Projects\TransFS\                                    │
│  ├─ content/  ✅ (accessible)                           │
│  └─ transfs/  ❌ (empty - FUSE not accessible)          │
│                                                          │
│        │                                                 │
│        │ Docker Volume Bind Mount                        │
│        ▼                                                 │
│  ┌────────────────────────────────────────────────┐     │
│  │         Linux VM (WSL2/Hyper-V)                │     │
│  │                                                 │     │
│  │  ┌──────────────────────────────────────────┐  │     │
│  │  │     Docker Container: transfs            │  │     │
│  │  │                                          │  │     │
│  │  │  /mnt/filestorefs  ✅ (regular files)   │  │     │
│  │  │  /mnt/transfs      ✅ (FUSE mounted)    │  │     │
│  │  │                     ↑                    │  │     │
│  │  │              TransFS FUSE Filesystem     │  │     │
│  │  │              (only accessible inside)    │  │     │
│  │  └──────────────────────────────────────────┘  │     │
│  └────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

## Solutions

### ✅ Solution 1: Run Tests Inside Docker Container (Recommended)

Run tests where the FUSE mount is actually accessible - inside the container.

#### PowerShell Script

```powershell
# Use the provided script
.\run_tests_in_docker.ps1
```

#### Manual Command

```powershell
# Run tests inside the container
docker exec -it transfs pytest /tests/test_filesystem_snapshots.py -v

# Update snapshots inside container
docker exec -it transfs pytest /tests/test_filesystem_snapshots.py --snapshot-update

# Run specific test
docker exec -it transfs pytest /tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v
```

#### Pros & Cons

✅ **Pros:**
- Works reliably on Windows
- Tests run in the actual environment TransFS runs in
- FUSE mount is fully accessible
- True integration testing

❌ **Cons:**
- Slightly longer command
- Need container running
- Snapshots stored in container (but mounted via volume, so accessible)

---

### ⚠️ Solution 2: Use Linux Host or WSL2 Native (Advanced)

Run everything natively in Linux where FUSE works properly.

#### Option A: WSL2 Native

```bash
# Inside WSL2 (not Docker Desktop)
cd /mnt/d/Projects/TransFS

# Install FUSE and Python
sudo apt-get update
sudo apt-get install fuse3 python3-pip

# Run TransFS natively
python3 app/transfs.py

# In another terminal, run tests
pytest tests/test_filesystem_snapshots.py -v
```

#### Option B: Linux VM or Bare Metal

Move the entire project to a Linux environment.

---

### ❌ Solution 3: Mock the FUSE Mount for Unit Tests (Not Recommended)

Create fake data for testing, losing integration test value.

---

## Recommended Workflow for Windows Development

### Daily Development

```powershell
# 1. Start Docker container
docker-compose up -d

# 2. Make code changes in VS Code (on Windows)
# Edit files in app/, tests/, etc.

# 3. Run tests inside container
.\run_tests_in_docker.ps1

# 4. If tests fail, review output and fix code

# 5. Update snapshots if changes are intentional
docker exec -it transfs pytest /tests/ --snapshot-update

# 6. Commit changes (code + snapshots)
git add .
git commit -m "Your changes"
```

### Accessing Snapshots

Snapshots are stored in `tests/__snapshots__/` which is:
- ✅ Mounted into the container via `./tests:/tests`
- ✅ Accessible on Windows at `D:\Projects\TransFS\tests\__snapshots__\`
- ✅ Can be committed to Git normally

### VS Code Integration

You can configure VS Code to run tests inside the container automatically.

#### `.vscode/tasks.json`

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Run Tests in Docker",
      "type": "shell",
      "command": "docker exec transfs pytest /tests/test_filesystem_snapshots.py -v",
      "group": {
        "kind": "test",
        "isDefault": true
      },
      "presentation": {
        "reveal": "always",
        "panel": "new"
      }
    },
    {
      "label": "Update Snapshots in Docker",
      "type": "shell",
      "command": "docker exec transfs pytest /tests/test_filesystem_snapshots.py --snapshot-update",
      "presentation": {
        "reveal": "always",
        "panel": "new"
      }
    }
  ]
}
```

Then use `Ctrl+Shift+P` → "Run Test Task" to run tests.

---

## Verification Steps

### 1. Check Container is Running

```powershell
docker ps --filter "name=transfs"
```

Expected output:
```
CONTAINER ID   IMAGE              COMMAND     ...   STATUS        PORTS       NAMES
abc123...      transfs_transfs    "bash..."   ...   Up 5 minutes  ...         transfs
```

### 2. Check FUSE Mount Inside Container

```powershell
# List files in the FUSE mount
docker exec transfs ls -la /mnt/transfs

# Should show TransFS virtual filesystem
# Example output:
# drwxr-xr-x  Native/
```

### 3. Check Volume Binding

```powershell
# On Windows - transfs directory likely empty
Get-ChildItem ./transfs

# Inside container - should show FUSE content
docker exec transfs ls -la /mnt/transfs
```

### 4. Run Simple Test

```powershell
# Test that pytest works
docker exec transfs pytest --version

# Run one simple test
docker exec transfs pytest /tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v
```

---

## Common Errors & Fixes

### Error: "No such file or directory: './transfs'"

**Cause:** Running tests on Windows host where FUSE mount isn't accessible

**Fix:** Run tests inside container:
```powershell
.\run_tests_in_docker.ps1
```

---

### Error: "Container not found"

**Cause:** Docker container not running

**Fix:**
```powershell
docker-compose up -d
```

---

### Error: "pytest: command not found" (inside container)

**Cause:** Python dependencies not installed in container

**Fix:** Rebuild container:
```powershell
docker-compose down
docker-compose up --build -d
```

Make sure `requirements-dev.txt` is installed in Dockerfile:
```dockerfile
RUN pip install -r requirements-dev.txt
```

---

### Error: "Permission denied" accessing /mnt/transfs

**Cause:** FUSE mount not properly initialized

**Fix:** Check TransFS logs:
```powershell
docker logs transfs

# Look for errors related to FUSE mounting
```

---

## Alternative: Hybrid Testing Approach

### Unit Tests (Windows Host)
Test individual functions without FUSE:
```powershell
# These work fine on Windows
pytest tests/test_pathutils.py -v
pytest tests/test_ziputils.py -v
```

### Integration Tests (Docker Container)
Test full filesystem behavior with FUSE:
```powershell
# Run in Docker where FUSE works
.\run_tests_in_docker.ps1
```

### Mark Tests Appropriately

```python
import pytest

@pytest.mark.integration
def test_transfs_structure(transfs_volume, filesystem_walker, snapshot):
    """Requires FUSE mount - run in Docker"""
    ...

@pytest.mark.unit
def test_path_transformation():
    """Pure function test - can run anywhere"""
    ...
```

Run selectively:
```powershell
# On Windows - only unit tests
pytest -m unit -v

# In Docker - all tests
docker exec transfs pytest -v
```

---

## Summary

| Environment | FUSE Access | Recommended Approach |
|-------------|-------------|---------------------|
| **Windows Host** | ❌ No | Run tests in Docker |
| **WSL2 Native** | ✅ Yes | Run tests natively |
| **Linux Host** | ✅ Yes | Run tests natively |
| **Inside Container** | ✅ Yes | **Always works** ✅ |

**Bottom Line:** For Windows development, **always run snapshot tests inside the Docker container** using:

```powershell
.\run_tests_in_docker.ps1
```

or

```powershell
docker exec -it transfs pytest /tests/test_filesystem_snapshots.py -v
```
