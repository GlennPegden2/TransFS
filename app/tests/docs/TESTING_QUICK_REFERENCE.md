# TransFS Testing - Quick Reference Card

## 🚀 Quick Start (First Time)

### Windows Users (IMPORTANT!)

```powershell
# 1. Install dependencies (on host, for IDE support)
pip install -r requirements-dev.txt

# 2. Start Docker
docker-compose up --build -d

# 3. Run tests INSIDE Docker container
.\run_tests_in_docker.ps1

# OR manually:
docker exec -it transfs pytest /tests/test_filesystem_snapshots.py -v
```

**Why inside Docker?** FUSE mounts aren't accessible from Windows hosts. See [TESTING_WINDOWS_ISSUES.md](../../TESTING_WINDOWS_ISSUES.md)

### Linux Users

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt

# 2. Start Docker
docker-compose up --build -d

# 3. Run tests (can run on host OR in Docker)
pytest tests/test_filesystem_snapshots.py -v

# 4. Commit snapshots
git add tests/__snapshots__
git commit -m "Add initial filesystem snapshots"
```

## 📋 Common Commands

### Running Tests

```powershell
# Run all snapshot tests
pytest tests/test_filesystem_snapshots.py -v

# Run specific test
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v

# Run tests for specific system
pytest -k "Archimedes" -v

# Run all tests (including old ones)
pytest tests/ -v

# Run with coverage
pytest --cov=app --cov-report=html

# Run in parallel (faster)
pytest -n auto
```

### Working with Snapshots

```powershell
# Update all snapshots
pytest --snapshot-update

# Update specific test snapshot
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure --snapshot-update

# Check for unused snapshots
pytest --snapshot-warn-unused
```

### Docker Management

```powershell
# Start container
docker-compose up --build -d

# Stop container
docker-compose down

# Restart container
docker-compose restart

# View logs
docker-compose logs -f transfs
```

## 🔍 Interpreting Test Results

### ✅ Tests Pass
```
tests/test_filesystem_snapshots.py::test_transfs_root_structure PASSED [100%]
```
**Meaning**: No breaking changes detected. Safe to proceed!

### ❌ Tests Fail - Snapshot Mismatch
```
AssertionError: Snapshot does not match
- Expected: 'total_files': 150
+ Actual:   'total_files': 148
```
**Meaning**: 2 files were removed. Investigate!

**Actions**:
1. Review the diff carefully
2. Check if change was intentional
3. If intentional: `pytest --snapshot-update`
4. If not intentional: Fix the bug

### ⏭️ Tests Skipped
```
SKIPPED [1] TransFS volume not mounted
```
**Meaning**: Docker container not running

**Fix**: `docker-compose up --build -d`

## 📁 File Locations

| File/Directory | Purpose |
|----------------|---------|
| `requirements-dev.txt` | Testing dependencies |
| `pytest.ini` | pytest configuration |
| `tests/conftest.py` | Test fixtures |
| `tests/test_filesystem_snapshots.py` | Main test suite |
| `tests/__snapshots__/` | Snapshot files |
| `./content/` | Source filestore (Docker volume) |
| `./transfs/` | TransFS mount (Docker volume) |
| `TESTING.md` | Full documentation |

## 🔄 Common Workflows

### Daily Development
```powershell
# Before committing
pytest tests/test_filesystem_snapshots.py -v
```

### Adding New Feature
```powershell
# 1. Implement feature
# 2. Run tests (they will fail)
pytest -v

# 3. Review diff
# 4. Update snapshots if correct
pytest --snapshot-update

# 5. Commit code + snapshots together
git add .
git commit -m "Add feature + update snapshots"
```

### Code Review
```powershell
# 1. Checkout PR branch
git checkout pr-branch

# 2. Rebuild Docker
docker-compose down
docker-compose up --build -d

# 3. Run tests
pytest tests/test_filesystem_snapshots.py -v

# 4. Review results
# - Pass: Good!
# - Fail with snapshot updates: Review changes
# - Fail without snapshot updates: Breaking change!
```

### Bug Fix
```powershell
# 1. Fix the bug
# 2. Run tests (should still pass)
pytest tests/test_filesystem_snapshots.py -v

# 3. If tests fail: your fix might have side effects
# 4. Investigate and adjust
```

## ⚠️ Important Rules

### ❌ DON'T
- Blindly run `--snapshot-update` without reviewing changes
- Skip tests before committing
- Update snapshots without understanding what changed
- Ignore test failures in CI/CD

### ✅ DO
- Review diffs before updating snapshots
- Commit snapshot updates with code changes
- Run tests after pulling changes
- Document why snapshots changed in commit message

## 🎯 Test Categories

| Test Class | What It Tests | When It Fails |
|------------|---------------|---------------|
| `TestTransFSSnapshots` | Basic structure | Files/dirs added/removed |
| `TestTransFSWithMetadata` | File metadata | File types changed |
| `TestComparativeAnalysis` | Transformation ratios | Virtual files not generated |
| `TestRegressionDetection` | Common issues | Empty dirs, missing critical files |

## 🐛 Troubleshooting

### "Volume not mounted"
```powershell
docker-compose up --build -d
```

### "deepdiff not found"
```powershell
pip install -r requirements-dev.txt
```

### "Too many tests failing"
```powershell
# Check if source content changed
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_filestore_unchanged -v

# Verify Docker is running
docker ps | findstr transfs

# Rebuild from scratch
docker-compose down
docker-compose up --build -d
pytest -v
```

### "Snapshot file not found"
```powershell
# Create initial snapshots
pytest tests/test_filesystem_snapshots.py -v
```

## 📊 Understanding Snapshots

### What Gets Captured?
- ✅ Directory names and structure
- ✅ File names and locations
- ✅ File counts
- ✅ File extensions (in metadata tests)
- ✅ Symlink information (in metadata tests)
- ❌ File contents (by default)
- ❌ File timestamps
- ❌ File permissions

### Snapshot File Format
```json
{
  "root": "./transfs",
  "directories": [
    "Native/",
    "Native/Acorn/",
    "Native/Acorn/Archimedes/"
  ],
  "files": [
    "Native/Acorn/Archimedes/README.md"
  ]
}
```

## 🔧 Advanced Usage

### Run Specific Test Types
```powershell
# Only basic structure tests
pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots -v

# Only metadata tests
pytest tests/test_filesystem_snapshots.py::TestTransFSWithMetadata -v

# Only regression tests
pytest tests/test_filesystem_snapshots.py::TestRegressionDetection -v
```

### Generate Reports
```powershell
# HTML coverage report
pytest --cov=app --cov-report=html
# Open htmlcov/index.html

# JSON test report
pytest --json-report --json-report-file=report.json
```

### Debug Mode
```powershell
# Verbose output
pytest -v -s

# Show print statements
pytest -s

# Stop on first failure
pytest -x
```

## 📝 Commit Message Template

When updating snapshots:
```
Add [feature name]

- Implemented [what you did]
- Updated snapshots to reflect [what changed]
- Added [X] new directories for [system/feature]
- Added [Y] new virtual files

Snapshots updated:
- test_transfs_directory_counts
- test_system_specific_structure[Archimedes]
```

## 🆘 Getting Help

1. **Full documentation**: See `TESTING.md`
2. **Examples**: See `tests/QUICKSTART.py`
3. **Workflows**: See `TESTING_WORKFLOW_DIAGRAM.md`
4. **Implementation details**: See `TESTING_IMPLEMENTATION_SUMMARY.md`

## 💡 Pro Tips

1. **Use specific tests during development** for faster feedback
2. **Run full suite before committing** to catch all issues
3. **Always review snapshot diffs** - they tell you what changed
4. **Keep Docker running** during development to avoid startup delays
5. **Use pytest markers** to categorize custom tests
6. **Parallelize tests** with `-n auto` for faster execution
7. **Check coverage** periodically to ensure good test coverage

---

**Quick Help**: `pytest --help` | **Version**: `pytest --version`
