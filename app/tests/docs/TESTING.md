# TransFS Testing Guide

## Overview

This testing framework helps detect breaking changes in TransFS by capturing snapshots of the filesystem structure and comparing them across code changes.

## Testing Framework

We use **pytest with syrupy** for snapshot testing:
- **pytest**: Industry-standard Python testing framework
- **syrupy**: Modern snapshot testing for capturing and comparing complex data structures
- **deepdiff**: For detailed comparison of filesystem states

## Installation

### Install Development Dependencies

```powershell
# Install all development dependencies including testing tools
pip install -r requirements-dev.txt
```

Or install just the core testing dependencies:

```powershell
pip install pytest syrupy deepdiff pytest-cov
```

## Running Tests

### Prerequisites

1. **Start Docker Container**: The tests need TransFS running in Docker to access the volumes:

```powershell
docker-compose up --build -d
```

2. **Verify Volumes**: Ensure the volumes are accessible:
   - `./content` - Source filestore (maps to `/mnt/filestorefs` in container)
   - `./transfs` - TransFS mount (maps to `/mnt/transfs` in container)

### Run All Tests

```powershell
# Run all tests with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run in parallel for faster execution
pytest -n auto
```

### Run Specific Test Categories

```powershell
# Run only snapshot tests
pytest tests/test_filesystem_snapshots.py -v

# Run only a specific test class
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots -v

# Run a specific test
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v
```

### Run Tests for Specific Systems

```powershell
# Run tests for Acorn Archimedes only
pytest tests/test_filesystem_snapshots.py -k "Archimedes" -v
```

## Working with Snapshots

### Initial Snapshot Creation

The first time you run the tests, snapshots will be automatically created:

```powershell
pytest tests/test_filesystem_snapshots.py -v
```

This creates snapshot files in `tests/__snapshots__/` directory.

### Detecting Breaking Changes

When you modify code and run tests:

```powershell
pytest tests/test_filesystem_snapshots.py -v
```

If the filesystem structure changed:
- ✅ **Test passes**: No changes detected (safe)
- ❌ **Test fails**: Structure changed (review carefully!)

### Updating Snapshots (Intentional Changes)

When you **intentionally** add new features that change the filesystem:

```powershell
# Update all snapshots
pytest --snapshot-update

# Update snapshots for specific test
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure --snapshot-update
```

**⚠️ WARNING**: Only update snapshots when you've verified the changes are intentional!

### Reviewing Snapshot Differences

When a test fails, pytest shows the difference:

```
AssertionError: Snapshot does not match
- Expected
+ Actual

  {
    'total_files': 150,
-   'total_directories': 45,
+   'total_directories': 46,  # <- New directory added
  }
```

Review the diff carefully to ensure it's an expected change.

## Test Structure

### Test Categories

1. **`TestTransFSSnapshots`**: Basic structure verification
   - Root structure
   - Directory/file counts
   - Per-system structure

2. **`TestTransFSWithMetadata`**: Detailed metadata verification
   - File extensions
   - Symlink detection

3. **`TestComparativeAnalysis`**: Compare source vs transformed
   - File count ratios
   - Transformation validation

4. **`TestRegressionDetection`**: Common regression patterns
   - Empty directory detection
   - Critical file presence

### Adding New Tests

To test a new system or feature:

```python
@pytest.mark.parametrize("system_path", [
    "Native/YourManufacturer/YourSystem",
])
def test_your_system_structure(self, transfs_volume, system_path, 
                               filesystem_walker, snapshot):
    """Test your new system directory structure."""
    full_path = transfs_volume / system_path
    
    if not full_path.exists():
        pytest.skip(f"System path {system_path} not found")
    
    state = filesystem_walker(full_path, include_metadata=False)
    assert state == snapshot
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Test TransFS

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Start Docker services
        run: docker-compose up --build -d
      
      - name: Wait for TransFS to be ready
        run: sleep 10
      
      - name: Run tests
        run: pytest -v --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Best Practices

### 1. Run Tests Before Committing

```powershell
# Quick validation before committing
pytest tests/test_filesystem_snapshots.py -v
```

### 2. Never Blindly Update Snapshots

Always review what changed before running `--snapshot-update`:

```powershell
# First, see what failed
pytest -v

# Review the diff carefully
# Only then update if changes are intentional
pytest --snapshot-update
```

### 3. Test After Merging

After merging changes from others:

```powershell
# Pull latest changes
git pull

# Rebuild and restart Docker
docker-compose down
docker-compose up --build -d

# Run full test suite
pytest -v
```

### 4. Add Critical Files to Test

If certain files must always exist, add them to `test_critical_files_present`:

```python
critical_paths = [
    "Native/Acorn/Archimedes/Software/BIOS/riscos.rom",
    "Native/Acorn/Electron/Software/Collections/README.md",
]
```

## Troubleshooting

### Volume Not Mounted

```
SKIPPED [1] test_filesystem_snapshots.py:24: TransFS volume not mounted
```

**Solution**: Start Docker container:
```powershell
docker-compose up --build -d
```

### Snapshot Mismatch Unclear

Use `--snapshot-warn-unused` to see which snapshots aren't being used:

```powershell
pytest --snapshot-warn-unused
```

### Too Many Snapshots Failing

If you pulled changes and many tests fail:

1. Check if content directory changed
2. Verify Docker is running correctly
3. Review git history for intentional changes
4. Contact the person who made the changes

### Performance Issues

For large filesystems, limit depth:

```python
state = filesystem_walker(path, max_depth=3)  # Only go 3 levels deep
```

## Understanding Test Output

### Successful Test

```
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure PASSED
```

### Failed Test (Breaking Change Detected)

```
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts FAILED

AssertionError: Snapshot does not match
Expected: 'total_files': 150
Actual:   'total_files': 148

This indicates 2 files were removed - investigate!
```

### Skipped Test

```
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_system_specific_structure SKIPPED
Reason: System path Native/NewSystem/NewPlatform not found
```

This is normal if you haven't added content for that system yet.

## Advanced Usage

### Generate Test Report

```powershell
# Generate JSON report
pytest --json-report --json-report-file=test-report.json

# Generate HTML report (requires pytest-html)
pip install pytest-html
pytest --html=report.html --self-contained-html
```

### Benchmark Performance

```powershell
# Run with benchmarking
pytest --benchmark-only
```

### Debug Mode

```powershell
# Run with detailed debug output
pytest -v -s --log-cli-level=DEBUG
```

## Maintenance

### Periodic Review

Every month or after major changes:

1. Run full test suite: `pytest -v`
2. Review snapshot sizes: `du -sh tests/__snapshots__`
3. Clean up obsolete snapshots for removed tests
4. Update documentation for new systems

### Snapshot Cleanup

Remove snapshots for deleted tests:

```powershell
pytest --snapshot-warn-unused
# Manually delete unused snapshot files
```

## Quick Reference

| Task | Command |
|------|---------|
| Run all tests | `pytest -v` |
| Update snapshots | `pytest --snapshot-update` |
| Run with coverage | `pytest --cov=app` |
| Run specific test | `pytest tests/test_filesystem_snapshots.py::TestName::test_name` |
| Run in parallel | `pytest -n auto` |
| Generate HTML report | `pytest --html=report.html` |
| Debug output | `pytest -v -s` |

## Questions?

- Check snapshot files in `tests/__snapshots__/`
- Review syrupy documentation: https://github.com/tophat/syrupy
- Check pytest documentation: https://docs.pytest.org/
