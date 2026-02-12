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

### Performance Tests Only
Run only performance tests with timing and target comparison:

```powershell
.\run_tests_in_docker.ps1 tests/test_systems.py::TestSystemPerformance -v
```

**What it shows:**
- Actual execution time for each test
- Target execution time (performance goal)
- Percentage improvement/degradation vs. target
- Tests marked with `@pytest.mark.performance` get special summary reporting

Example output:
```
======================== PERFORMANCE TEST SUMMARY =========================
✓ Performance Tests (Passed)
  test_directory_readdir_performance[Acorn Archimedes]: 1.456s / 15.0s target ✓ (90% faster)
  test_directory_stat_performance[Acorn Archimedes]: 1.150s / 30.0s target ✓ (96% faster)
```

## Why Docker is Required

Tests must access the FUSE mount at `/mnt/transfs`, which is only available inside the Docker container. Running tests on the Windows host will fail because FUSE mounts are not exposed to the host OS.

## Performance Test Markers

Performance tests are automatically tracked and reported with timing information. Mark a test with `@pytest.mark.performance` to include it in the performance summary:

```python
@pytest.mark.performance(target_seconds=15.0)
def test_directory_readdir_performance(self):
    """Test directory listing performance."""
    # Test code here
```

The performance reporter will:
1. Track execution time for the test
2. Compare against the target time
3. Display in a dedicated summary section
4. Show percentage faster/slower than target

**Target time guidelines:**
- Small directories (< 100 files): 0.5-1.0 seconds
- Medium directories (100-500 files): 2-5 seconds  
- Large directories (500+ files): 10-30 seconds
- Stat operations: 2-3x the readdir time

To skip snapshot tests (which are incomplete):
```powershell
.\run_tests_in_docker.ps1 --ignore=tests/test_snapshots.py
# or
.\run_tests_in_docker.ps1 -k "not snapshot"
```

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
