# TransFS Testing Guide

## Quick Start

### Fast Validation (Recommended)
Verifies core functionality in ~1 second:

```powershell
.\validate_docker.ps1
```

**What it checks:**
- FUSE mount accessibility
- Configuration standards compliance
- ZIP navigation and file reading
- Virtual filesystem structure

### Full Regression Tests
Comprehensive snapshot-based testing (slower, walks entire filesystem):

```powershell
.\run_tests_in_docker.ps1
```

**Run specific tests:**
```powershell
.\run_tests_in_docker.ps1 tests/test_filesystem_snapshots.py::TestRegressionDetection -v
```

**Update snapshots after intentional changes:**
```powershell
.\run_tests_in_docker.ps1 --snapshot-update
```

## Why Docker is Required

Tests must access the FUSE mount at `/mnt/transfs`, which is only available inside the Docker container. Running tests on the Windows host will fail because FUSE mounts are not exposed to the host OS.

## Test Scripts

- **`validate_docker.ps1`** - Quick validation (1 second)
- **`run_tests_in_docker.ps1`** - Full pytest runner (PowerShell)
- **`run_tests_in_docker.sh`** - Full pytest runner (Linux/Mac)
- **`run_tests.ps1`** - Legacy script (redirects to Docker versions)

## Performance Notes

Full filesystem walk tests can be very slow with FUSE. Use the quick validation script (`validate_docker.ps1`) for routine checks during development.

## More Information

For detailed testing documentation, architecture, and implementation details:
- [tests/docs/TESTING.md](tests/docs/TESTING.md) - Comprehensive guide
- [tests/docs/TESTING_QUICK_REFERENCE.md](tests/docs/TESTING_QUICK_REFERENCE.md) - Command reference
- [tests/docs/TESTING_WHY_SNAPSHOTS.md](tests/docs/TESTING_WHY_SNAPSHOTS.md) - Methodology
