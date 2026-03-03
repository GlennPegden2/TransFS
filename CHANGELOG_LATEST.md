# Latest Changes

## 2026-03-03: Database Connection Pool & Performance Fixes

### Summary
Fixed critical "connection pool exhausted" errors that were blocking multi-folder deletion operations by increasing the database connection pool from 15 to 150 total connections.

### Changes Made

#### 1. **Database Connection Pool Size (15 → 150)**
- **Files Modified:**
  - `app/transfs.py` (line 109): Updated `db_init_database()` call
  - `app/api.py` (lines 743, 808, 1900): Updated three `init_database()` calls  
  - `app/sync_database.py` (line 215): Updated database initialization
  - `app/dirlisting.py` (lines 39-41): Updated fallback initialization
  - `app/data_provider_db.py` (line 39): Updated provider initialization

- **Changes:** All calls now specify `pool_size=50, max_overflow=100` (previously used default of 5+10)

- **Impact:** Prevents "connection pool exhausted" errors during recursive directory operations where multiple READDIR requests query the database simultaneously

#### 2. **PostgreSQL Server Connection Limit (100 → 200)**
- **File Modified:** `docker-compose.yml` (lines 11-18)
- **Change:** Updated postgres service to use `command: ["postgres", "-c", "max_connections=200"]`
- **Impact:** Prevents "FATAL: sorry, too many clients already" errors when the app tries to establish more than the default 100 connections

#### 3. **Samba FUSE Compatibility Settings**
- **File Modified:** `smb.conf` (added lines for TransFS share)
- **Added Settings:**
  ```conf
  delete veto files = yes
  veto files = /.snapshot/
  ```
- **Purpose:** Improve Samba's handling of FUSE-backed file deletion operations

### Testing Results

#### ✅ Working (FUSE-level)
- FUSE-based deletion commands work correctly
- `docker exec transfs rm -rf /mnt/transfs/RetroBat/bios/[folder]` succeeds
- RMDIR/UNLINK operations properly called in logs
- Connection pool no longer exhausted during operations

#### ❌ Still Failing (SMB-level)
- Windows PowerShell `Remove-Item` returns "The request is not supported" error
- Samba is not properly translating Windows delete requests to FUSE operations
- Issue appears to be in Samba→FUSE translation layer, not in TransFS or database

### Next Steps

The SMB delete issue requires one of:
1. **Samba configuration adjustment** - May need additional FUSE-specific parameters
2. **FUSE permission/capability fix** - Ensure FUSE advertises delete capability to Samba
3. **SMB protocol handler debugging** - May require Samba source investigation or upgrade

However, the database connection pool fix is complete and working well. Multi-folder operations that were failing with "connection pool exhausted" now work successfully at the FUSE level.
