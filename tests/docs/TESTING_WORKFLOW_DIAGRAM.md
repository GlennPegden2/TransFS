# TransFS Testing Framework - Visual Workflow

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Docker Container                         │
│                                                                  │
│  ┌──────────────┐           ┌──────────────┐                   │
│  │              │           │              │                   │
│  │  /mnt/       │  TransFS  │  /mnt/       │                   │
│  │  filestorefs │──────────▶│  transfs     │                   │
│  │  (source)    │  FUSE FS  │  (virtual)   │                   │
│  │              │           │              │                   │
│  └──────┬───────┘           └──────┬───────┘                   │
│         │                          │                           │
└─────────┼──────────────────────────┼───────────────────────────┘
          │                          │
          │ Docker Volume            │ Docker Volume
          │ Mapping                  │ Mapping
          │                          │
┌─────────▼──────────────────────────▼───────────────────────────┐
│                         Host Machine                            │
│                                                                  │
│  ┌──────────────┐           ┌──────────────┐                   │
│  │              │           │              │                   │
│  │  ./content/  │           │  ./transfs/  │                   │
│  │              │           │              │                   │
│  │  Native/     │           │  Native/     │                   │
│  │  ├─ Acorn/   │           │  ├─ Acorn/   │                   │
│  │  ├─ Amstrad/ │           │  ├─ Amstrad/ │                   │
│  │  └─ ...      │           │  └─ ...      │                   │
│  │              │           │              │                   │
│  └──────────────┘           └──────┬───────┘                   │
│                                    │                           │
│                                    │ Tests Read From           │
│                                    │                           │
│                          ┌─────────▼──────────┐                │
│                          │  tests/            │                │
│                          │  ├─ conftest.py    │                │
│                          │  ├─ test_*.py      │                │
│                          │  └─ __snapshots__/ │                │
│                          └────────────────────┘                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Testing Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    STEP 1: Initial Snapshot Creation            │
└─────────────────────────────────────────────────────────────────┘

    pytest tests/test_filesystem_snapshots.py -v
              │
              ▼
    ┌─────────────────┐
    │ filesystem_     │
    │ walker()        │──▶ Walks ./transfs/
    └─────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────┐
    │ Captures:                                │
    │ - Directory list                         │
    │ - File list                              │
    │ - Metadata (optional)                    │
    └─────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────┐
    │ Saves to:                                │
    │ tests/__snapshots__/                     │
    │   test_filesystem_snapshots/             │
    │     test_transfs_root_structure.json     │
    └─────────────────────────────────────────┘
              │
              ▼
         [PASS] ✅
    "1 snapshot created"


┌─────────────────────────────────────────────────────────────────┐
│              STEP 2: Development - No Changes                    │
└─────────────────────────────────────────────────────────────────┘

    [Developer makes changes to app/transfs.py]
              │
              ▼
    pytest tests/test_filesystem_snapshots.py -v
              │
              ▼
    ┌─────────────────┐
    │ Walk filesystem │──▶ Current state
    └─────────────────┘
              │
              ▼
    ┌─────────────────────────────┐
    │ Compare with snapshot       │
    └─────────────────────────────┘
              │
              ▼
    Current == Snapshot?
         │           │
         │           └──▶ [PASS] ✅
         │                "Structure unchanged"
         │
         └──▶ [Go to Step 3 or 4]


┌─────────────────────────────────────────────────────────────────┐
│         STEP 3: Development - Breaking Change (Accidental)       │
└─────────────────────────────────────────────────────────────────┘

    [Developer accidentally breaks something]
              │
              ▼
    pytest tests/test_filesystem_snapshots.py -v
              │
              ▼
    Current != Snapshot
              │
              ▼
         [FAIL] ❌
              │
              ▼
    ┌─────────────────────────────────────────┐
    │ Diff shown:                              │
    │                                          │
    │ - 'Native/Acorn/Atom/',                  │
    │ + 'Native/Acorn/Archimedes/',            │
    │                                          │
    │ Missing directory detected!              │
    └─────────────────────────────────────────┘
              │
              ▼
    Developer investigates and fixes bug
              │
              ▼
    Re-run tests → [PASS] ✅


┌─────────────────────────────────────────────────────────────────┐
│         STEP 4: Development - Intentional Feature Add            │
└─────────────────────────────────────────────────────────────────┘

    [Developer adds new system support]
              │
              ▼
    pytest tests/test_filesystem_snapshots.py -v
              │
              ▼
    Current != Snapshot
              │
              ▼
         [FAIL] ❌
              │
              ▼
    ┌─────────────────────────────────────────┐
    │ Diff shown:                              │
    │                                          │
    │   'total_directories': 25,               │
    │ + 'total_directories': 27,               │
    │                                          │
    │ + 'Native/NewManufacturer/',             │
    │ + 'Native/NewManufacturer/NewSystem/',   │
    └─────────────────────────────────────────┘
              │
              ▼
    Developer reviews: "This is correct!"
              │
              ▼
    pytest --snapshot-update
              │
              ▼
    ┌─────────────────────────────────────────┐
    │ Snapshots updated:                       │
    │ - test_transfs_directory_counts.json     │
    │ - test_transfs_root_structure.json       │
    └─────────────────────────────────────────┘
              │
              ▼
         [PASS] ✅
    "2 snapshots updated"
              │
              ▼
    git add tests/__snapshots__
    git commit -m "Add NewSystem + update snapshots"
```

## Comparison Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Snapshot Comparison Logic                     │
└─────────────────────────────────────────────────────────────────┘

                     ┌──────────────┐
                     │ Run Test     │
                     └──────┬───────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │ Does snapshot exist?    │
              └─────────┬───────────────┘
                        │
            ┌───────────┴───────────┐
            │                       │
           NO                      YES
            │                       │
            ▼                       ▼
    ┌───────────────┐    ┌──────────────────┐
    │ Create new    │    │ Load existing    │
    │ snapshot      │    │ snapshot         │
    └───────┬───────┘    └────────┬─────────┘
            │                     │
            └──────────┬──────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │ Walk filesystem and  │
            │ capture current state│
            └──────────┬───────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │ Compare:              │
            │ - Directories         │
            │ - Files               │
            │ - Metadata (if used)  │
            └──────────┬───────────┘
                       │
            ┌──────────┴──────────┐
            │                     │
           Same               Different
            │                     │
            ▼                     ▼
      ┌─────────┐          ┌──────────┐
      │ PASS ✅ │          │ FAIL ❌  │
      └─────────┘          └────┬─────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │ Show diff to user:   │
                    │ + Added items        │
                    │ - Removed items      │
                    │ ! Changed items      │
                    └──────────────────────┘
```

## Test Categorization

```
┌──────────────────────────────────────────────────────────────┐
│                    Test Suite Structure                       │
└──────────────────────────────────────────────────────────────┘

test_filesystem_snapshots.py
│
├─ TestTransFSSnapshots (Basic)
│  │
│  ├─ test_transfs_root_structure
│  │  └─ Captures: Top-level dirs & files (depth=2)
│  │
│  ├─ test_transfs_directory_counts
│  │  └─ Captures: Total counts + full lists
│  │
│  ├─ test_system_specific_structure [parameterized]
│  │  ├─ Native/Acorn/Archimedes
│  │  ├─ Native/Acorn/Atom
│  │  ├─ Native/Acorn/Electron
│  │  ├─ Native/Amstrad/CPC
│  │  ├─ Native/Amstrad/PCW
│  │  ├─ Native/MITS/Altair8800
│  │  └─ Native/Tandy/MC-10
│  │
│  └─ test_filestore_unchanged (Control)
│     └─ Verifies: Source content didn't change
│
├─ TestTransFSWithMetadata (Detailed)
│  │
│  ├─ test_virtual_file_extensions
│  │  └─ Tracks: File types by extension
│  │
│  └─ test_symlink_detection
│     └─ Tracks: Symlinks created/removed
│
├─ TestComparativeAnalysis (Advanced)
│  │
│  └─ test_file_count_ratio
│     └─ Compares: Source vs. transformed ratios
│
└─ TestRegressionDetection (Safety)
   │
   ├─ test_no_empty_directories_created
   │  └─ Prevents: Unexpected empty dirs
   │
   └─ test_critical_files_present
      └─ Ensures: Essential files exist
```

## CI/CD Integration Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    GitHub Actions Workflow                    │
└──────────────────────────────────────────────────────────────┘

    Developer pushes code
              │
              ▼
    ┌─────────────────┐
    │ GitHub Actions  │
    │ triggered       │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Checkout code           │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Set up Python 3.11      │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Install dependencies    │
    │ - requirements.txt      │
    │ - requirements-dev.txt  │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ docker-compose up -d    │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Wait for services       │
    │ (sleep 15s)             │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Run snapshot tests      │
    │ pytest -v               │
    └────────┬────────────────┘
             │
      ┌──────┴──────┐
      │             │
    PASS          FAIL
      │             │
      ▼             ▼
  ┌────────┐   ┌──────────────────────────┐
  │ Run    │   │ Check for snapshot       │
  │ other  │   │ updates in commit        │
  │ tests  │   │                          │
  └───┬────┘   └────────┬─────────────────┘
      │                 │
      │          ┌──────┴──────┐
      │          │             │
      │         YES           NO
      │          │             │
      │          ▼             ▼
      │    ┌──────────┐  ┌──────────────┐
      │    │ Warning: │  │ FAIL BUILD   │
      │    │ Review   │  │ Breaking     │
      │    │ changes  │  │ change!      │
      │    └────┬─────┘  └──────────────┘
      │         │
      └─────────┴────────▶ Continue
                │
                ▼
         ┌──────────────┐
         │ Build passes │
         │ or fails     │
         └──────────────┘
```

## Legend

```
Symbol   Meaning
───────────────────────────────
  ▶      Process flow
  │      Connection
  ┌─┐    Container/Box
  ✅     Success/Pass
  ❌     Failure
  [...]  Action/State
```
