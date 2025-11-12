"""
Quick Start Example: Running Your First Snapshot Test

This example demonstrates how to use the snapshot testing framework
to detect breaking changes in TransFS.
"""

# Step 1: Ensure Docker is running
# Run in PowerShell:
# docker-compose up --build -d

# Step 2: Install dependencies
# pip install -r requirements-dev.txt

# Step 3: Run your first test to create initial snapshots
# pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v

# Step 4: Make a change to your code
# (Edit any file in app/ directory)

# Step 5: Run the test again to check for breaking changes
# pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v

# Step 6: If changes are intentional, update the snapshot
# pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure --snapshot-update

# Example Test Run Output:
"""
Example 1: No Changes (Test Passes)
====================================

$ pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v

tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure PASSED [100%]

========================= 1 passed in 0.45s =========================

✅ This means no breaking changes were detected!


Example 2: Breaking Change Detected (Test Fails)
================================================

$ pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts -v

tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts FAILED [100%]

========================= FAILURES =========================
________________ TestTransFSSnapshots.test_transfs_directory_counts ________________

Snapshot does not match:

  {
    'directory_list': [
      'Native/',
      'Native/Acorn/',
      'Native/Acorn/Archimedes/',
-     'Native/Acorn/Atom/',           <- Directory missing!
      'Native/Acorn/Electron/',
    ],
-   'total_directories': 25,
+   'total_directories': 24,          <- Count decreased!
    'total_files': 150,
  }

❌ This indicates a breaking change - the Atom directory is missing!
   You need to investigate why this directory disappeared.


Example 3: Intentional Feature Addition (Update Snapshot)
=========================================================

You added support for a new system, so the structure legitimately changed.

$ pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts -v

FAILED (snapshot mismatch)

After reviewing the diff and confirming it's correct:

$ pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts --snapshot-update

tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts PASSED [100%]
1 snapshot updated.

✅ Snapshot updated successfully!


Example 4: Running Full Test Suite
===================================

$ pytest tests/test_filesystem_snapshots.py -v

tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure PASSED
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_directory_counts PASSED
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_system_specific_structure[Native/Acorn/Archimedes] PASSED
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_system_specific_structure[Native/Acorn/Atom] PASSED
tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_system_specific_structure[Native/Acorn/Electron] PASSED
tests/test_filesystem_snapshots.py::TestTransFSWithMetadata::test_virtual_file_extensions PASSED
tests/test_filesystem_snapshots.py::TestComparativeAnalysis::test_file_count_ratio PASSED
tests/test_filesystem_snapshots.py::TestRegressionDetection::test_no_empty_directories_created PASSED

========================= 8 passed in 2.34s =========================

✅ All tests passed - no breaking changes!


Example 5: Testing After Code Review
====================================

Scenario: Someone else made changes, you're reviewing their PR.

$ git checkout feature-branch
$ docker-compose down
$ docker-compose up --build -d
$ pytest tests/test_filesystem_snapshots.py -v

If tests fail:
1. Review the diff to understand what changed
2. Ask the developer if changes are intentional
3. If legitimate feature: approve PR + update snapshots after merge
4. If breaking change: request fixes before merge

"""


# Common Workflows
# ================

def workflow_adding_new_feature():
    """Workflow when adding a new feature that changes the filesystem structure."""
    
    # 1. Create a new branch
    # git checkout -b feature/new-system-support
    
    # 2. Run tests to establish baseline
    # pytest tests/test_filesystem_snapshots.py -v
    
    # 3. Implement your feature
    # (make code changes)
    
    # 4. Run tests again
    # pytest tests/test_filesystem_snapshots.py -v
    
    # 5. Review the differences carefully
    # (check the output to see what changed)
    
    # 6. If changes look correct, update snapshots
    # pytest --snapshot-update
    
    # 7. Commit both code changes AND snapshot updates
    # git add .
    # git commit -m "Add support for new system + updated snapshots"
    
    pass


def workflow_fixing_bug():
    """Workflow when fixing a bug that shouldn't change filesystem structure."""
    
    # 1. Create a new branch
    # git checkout -b fix/some-bug
    
    # 2. Implement your fix
    # (make code changes)
    
    # 3. Run tests - they should still pass!
    # pytest tests/test_filesystem_snapshots.py -v
    
    # 4. If tests pass: great! Commit and create PR
    # git commit -am "Fix bug XYZ"
    
    # 5. If tests fail: your fix might have introduced a breaking change
    # Review carefully - you may need to adjust your fix
    
    pass


def workflow_code_review():
    """Workflow when reviewing someone else's pull request."""
    
    # 1. Checkout their branch
    # git fetch origin
    # git checkout pr-branch
    
    # 2. Rebuild Docker
    # docker-compose down
    # docker-compose up --build -d
    
    # 3. Run tests
    # pytest tests/test_filesystem_snapshots.py -v
    
    # 4a. If tests pass: good sign!
    # 4b. If tests fail: check if snapshot updates are included in PR
    #     - If snapshot updates present: review changes carefully
    #     - If no snapshot updates: likely a breaking change - request fixes
    
    pass


# Continuous Integration Example
# ===============================

ci_github_actions = """
# .github/workflows/test.yml

name: Test TransFS

on: 
  push:
    branches: [ main, dev ]
  pull_request:
    branches: [ main, dev ]

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
      
      - name: Start Docker Compose
        run: |
          docker-compose up --build -d
      
      - name: Wait for services to be ready
        run: |
          sleep 15
      
      - name: Run snapshot tests
        run: |
          pytest tests/test_filesystem_snapshots.py -v --tb=short
      
      - name: Check for snapshot differences
        if: failure()
        run: |
          echo "⚠️ Snapshot tests failed!"
          echo "If this is intentional, run 'pytest --snapshot-update' locally"
          echo "and commit the updated snapshots."
          exit 1
      
      - name: Run all tests with coverage
        run: |
          pytest --cov=app --cov-report=xml --cov-report=term
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
"""

print(__doc__)
print(ci_github_actions)
