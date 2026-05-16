# TransFS Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **Python base image upgraded from 3.10 to 3.12**: Updated `Dockerfile` (both `chdman-builder` and runtime stages) from `python:3.10-slim` to `python:3.12-slim`. All dependencies confirmed compatible: `libtorrent 2.0.11` has pre-built cp312 wheels, `pyfuse3 3.4.2` compiles cleanly on 3.12 (requires `>=3.10`), `mega.py 1.0.8` is fully synchronous with no `asyncio.coroutine` usage and works on 3.12/3.13. The retronas-testbed container already runs Python 3.12 in production.

- **Refactored RetroNAS integration structure**: Reorganized RetroNAS-related code to clarify three distinct objectives:
  1. **PR-ready files** (`platform/linux/retronas-pr/`) - Clean artifacts for RetroNAS project submission
  2. **Testbed integration** (`platform/docker/retronas-testbed/`) - Local Docker testing infrastructure (separate from PR submission code)
  3. **Build workflows** - Split into `retronas-pr-export` (PR artifacts) and `retronas-testbed-prep` (testbed preparation) Docker Compose profiles
  - Renamed `platform/linux/retronas/` → `platform/linux/retronas-pr/`
  - Created `platform/docker/retronas-testbed/` with setup script and docker-compose override
  - Updated docker-compose.yml: `retronas-artifacts` profile → `retronas-pr-export` and `retronas-testbed-prep`
  - Updated build scripts: `build_retronas_artifacts.sh` → `build_retronas_pr_export.sh` in `platform/linux/retronas-pr/`
  - Renamed `docs/development/RETRONAS_DOCKER_PROFILE.md` → `docs/development/RETRONAS_PR_EXPORT.md`
  - Added `docs/development/RETRONAS_TESTBED_SETUP.md` with complete testbed workflow

### Added
- **RetroNAS testbed integration script** (`platform/docker/retronas-testbed/setup.sh`): One-command testbed preparation that exports PR artifacts, injects them into a cloned retronas-docker, and provides next-step instructions.
- **RetroNAS testbed Docker Compose override** (`platform/docker/retronas-testbed/docker-compose.override.yml`): Compose configuration for testbed service orchestration.
- **Persistent RetroNAS install-menu registration helper**: Added `platform/linux/retronas-pr/register_transfs_menu.sh` and included it in generated RetroNAS artifacts so TransFS can be registered in RetroNAS `Install` menu (`config/menu/install.json`) after deploy/rebuild with an idempotent command.

### Fixed
- **RetroNAS testbed now has a compose-driven runtime path for FUSE + postgres dependencies**: Updated `platform/docker/retronas-testbed/docker-compose.override.yml` into a usable `retronas-testbed` compose profile fragment that starts `retronas:testbed` with `/dev/fuse`, `SYS_ADMIN`, and `apparmor:unconfined`, plus a colocated `postgres` service and healthcheck. Updated `platform/docker/retronas-testbed/setup.sh` to copy this fragment into retronas-docker as `docker-compose.transfs-testbed.yml` and print compose-based startup commands.
- **RetroNAS testbed setup script artifact copy paths corrected**: `platform/docker/retronas-testbed/setup.sh` now copies `install_transfs.yml` and templates from the exported bundle path `platform/linux/retronas/ansible/...` (not `retronas-pr`), matching the generated installer layout.
- **RetroNAS startup script now creates missing mountpoint before FUSE mount checks**: `platform/linux/start_transfs_retronas.sh` now ensures the configured mountpoint directory exists and emits a clear `/dev/fuse` runtime error when FUSE device passthrough is missing.
- **RetroNAS installer now starts TransFS in non-systemd environments instead of only skipping activation**: Added `platform/linux/transfs_retronas_ctl.sh` as a portable runtime controller, updated the RetroNAS Ansible installer to use it whenever `systemctl` is unavailable, and included the new launcher in the RetroNAS PR export bundle so the Docker testbed exercises the same submitted files.
- **RetroNAS installer now tolerates non-systemd testbed environments**: The Ansible install flow now checks for `systemctl` before enabling or restarting `transfs-retronas.service`, and skips service activation with a clear message when running inside the Docker-based RetroNAS testbed container.
- **RetroNAS installer now falls back to bundled helper scripts when the cloned TransFS repo lacks them**: The Ansible install flow now copies `configure_retronas.sh` and `start_transfs_retronas.sh` from bundled RetroNAS PR assets into `/opt/transfs/platform/linux` when the checked-out repo revision does not yet contain those files, preventing testbed installs from failing on missing helper scripts.
- **RetroNAS installer now installs native build dependencies for pyfuse3**: Added `build-essential`, `pkg-config`, `libfuse3-dev`, and `python3-dev` to the RetroNAS Ansible dependency list so the TransFS virtualenv install can build `pyfuse3` successfully on bare-metal RetroNAS hosts.
- **RetroNAS installer now uses a dedicated Python virtualenv**: Updated the RetroNAS Ansible install flow to create/use `/opt/transfs/.venv` instead of system `pip3`, avoiding PEP 668 `externally-managed-environment` failures on modern Debian-based RetroNAS hosts while also pointing the runtime service at the venv Python.
- **Compose profile isolation for RetroNAS artifact builds**: `postgres` and `transfs` services are now explicitly assigned to runtime profiles (`operational`, `development`) so running `--profile retronas-artifacts` no longer attempts to create/start the runtime stack. Updated `.vscode/tasks.json` to select `operational` explicitly for normal runtime startup and added a dedicated **Build RetroNAS Artifacts** task.
- **Intermittent Docker network attach failure during artifact-only runs**: Set `retronas-artifacts` service to `network_mode: none` in `docker-compose.yml` since the artifact export workflow does not require networking. This avoids daemon errors like `failed to set up container networking: network ... not found` while preserving successful artifact generation.
- **Optional RetroNAS namespace compatibility layer**: Added `app/retronas_support.py` and FUSE integration hooks in `app/dirlisting.py` and `app/sourcepath.py` for client-specific SMB/CIFS namespace projection over canonical storage. Includes MiSTer top-level projection model (`games`, `saves`, `savestates`, `BIOS`), canonical mapping, and alias/override support. Default config is opt-in (`retronas_support.enabled: false`) to preserve existing behavior.
- **RetroNAS verification scaffolding**: Added unit tests for runtime port allocation and SMB ownership-mode gates (`tests/test_runtime_port_resolution.py`, `tests/test_smb_mode_behavior.py`) plus Ansible inventory example (`platform/linux/retronas/ansible/inventory.example.ini`) and README smoke-check guidance.
- **RetroNAS Ansible playbook skeleton**: Added `platform/linux/retronas/ansible/install_transfs.yml` with templates for `/etc/systemd/system/transfs-retronas.service` and `/etc/default/transfs-retronas`, wired to `configure_retronas.sh` for runtime mode and port configuration.
- **Phase 3 RetroNAS installer artifacts (first pass)**: Added reusable Linux artifacts to support contributed RetroNAS installation flow: `platform/linux/configure_retronas.sh` (writes RetroNAS runtime/port/mode config into `app/config/app.yaml`), `platform/linux/start_transfs_retronas.sh` (bare-metal startup runner honoring `smb.mode`), and `platform/linux/transfs-retronas.service` (systemd unit template). Added implementation notes in `docs/development/RETRONAS_INSTALLER_ARTIFACTS.md`.
- **Phase 2 SMB ownership mode wiring + runtime port status API**: Added explicit SMB ownership-mode handling for runtime startup (`smb.mode`: `transfs_managed` | `retronas_managed` | `disabled`) in `app/smb_config.py` and `platform/linux/entrypoint.sh`, including conditional Samba setup/service start/stop. Added `/api/runtime/ports` endpoint in `app/api.py` to expose resolved runtime port allocation and SMB management state for installer diagnostics.
- **Phase 1 runtime port allocation resolver (opt-in, Docker-safe)**: Added config-layer port allocation utilities in `app/config.py` to resolve preferred/fallback listener ports for `web_api` and `smb` with optional conflict probing (`auto_allocate_port` or global `runtime.enable_port_auto_claim`). Resolver outputs include `allocated_port`, attempted/conflicted ports, non-standard warning flags, and allocation errors. Existing Docker behavior remains unchanged unless explicitly enabled.
- **RetroNAS installer port-claim strategy design**: Added [docs/development/RETRONAS_PORT_CLAIM_STRATEGY.md](docs/development/RETRONAS_PORT_CLAIM_STRATEGY.md) defining TransFS integration behavior for port ownership modes (`retronas_managed` vs `transfs_managed`), deterministic preferred/fallback port allocation, non-standard port warning semantics, and proposed config schema for installer/runtime resolved ports.
- **YAML Configuration Linter**: New integrated linter for TransFS config files with both CLI (`tools/lint_config.py`) and web UI (Debug tab → Config Lint) entry points. Detects:
  - Syntax errors and duplicate keys (YAML parsing)
  - Missing required fields per config type (`app.yaml`, `clients/*.yaml`, `sources/*/*.yaml`)
  - Invalid source type references in packs
  - Missing recommended fields (warnings)
  - Detailed suggestions for each issue
  - JSON API endpoint `/api/lint-config` for programmatic access
  - Real-time validation found 18 errors and 51 warnings across 84 config files
- **Per-client disc cache for archived game images**: Implemented a "last inserted disc" cache keyed by `(client, system)` that preserves extracted temporary files indefinitely until a different game is accessed by that client on that system. When the 3DO core (or any core) re-reads a disc mid-game for audio streaming, seek operations, or other runtime access, the file is served instantly from the cache instead of requiring 18-20 second re-extraction from the archive. Different clients/systems maintain independent cache slots, so loading a different game automatically evicts and replaces the previous cache. This dramatically improves performance for games that stream or re-read audio tracks during gameplay.
- **Managed Native external SMB/CIFS mounts**: Added persistent, web-UI-manageable mounts for mapping NAS folders into Native subpaths (including deep targets like `Native/Systems/.../Software/Sources/Nas-Collection`). New API endpoints support list/create/update/delete/validate/mount/unmount/reconcile flows under `/api/native-mounts*`, mount credentials are stored in persisted filestore secrets, and startup now reconciles enabled auto-reconnect mounts.

### Fixed
- **Config Lint results list now renders in Debug UI**: Debug -> Config Lint now consistently shows per-file warning/error entries (not just summary counts). The frontend renderer now supports both nested `summary` payloads and legacy top-level count fields, and always iterates returned `files[].issues` to display detailed lint findings.
- **7z/zip flatten listings restored for DB-backed query maps (3DO CDs, MiSTer/RetroBat)**: `app/transfs.py` now expands archive container rows into inner-file virtual entries during DB-only readdir when `zip_mode: flatten` is configured, and reuses that expanded cache in DB-only `getattr`/`open` so flattened files resolve to `archive#ZIP#inner` source paths instead of failing direct source-path reconstruction.
- **MiSTer 3DO `CDs` now includes files from mounted Native collection folders even before DB sync**: DB-backed query-map directory listings were prioritizing map-index rows and could miss unsynced files present under mounted nested folders (for example `Native/Systems/3DO/3DO/Software/Collections/RetroRom-Collection`). Updated query-map listing paths to merge filesystem files (including recursive nested folders) with extension filtering, so mounted content appears immediately in virtual listings.
- **3DO query-map lookups no longer crash when archive path resolution misses**: `list_query_map` could pass a `None` archive path into `os.path.isfile(...)` after recursive archive lookup returned no match, raising `TypeError` and aborting MiSTer 3DO lookups. Added null guards before file checks in both query-map archive branches so missing archive paths now fail gracefully instead of killing the listing/lookup flow.
- **MiSTer Amstrad CPC FDs listings no longer appear empty when the source content is archive-backed**: the FUSE DB-only query-map path now includes archive container extensions for maps with `transform_zip: true`, falls back cleanly when older map-index rows are incomplete, and serves recovered results from cache. After reindexing, the live MiSTer Amstrad FDs view is again returning thousands of entries instead of an empty folder.
- **Hidden share-name root alias lookups now resolve cleanly again**: clients probing paths like `/mnt/transfs/transfs` no longer fall through to repeated `LOOKUP: FAILED - not found: transfs` messages. The FUSE layer now normalizes that hidden compatibility segment back to the real mount root and serves it through a stable synthetic directory inode.
- **MiSTer 3DO archive-backed discs could list but fail to launch**: fixed FUSE LOOKUP for database-backed query-map files so archive members exposed under virtual maps resolve reliably after directory browsing, and added cue-sheet target rewriting for broken archive cues so referenced ISO names match the actual mounted disc image names.
- **3DO RetroRom collection entries under Native/Systems were missing for MiSTer and only partially surfacing for archive-backed maps**: corrected the MiSTer 3DO `local_base_path` to `Systems/3DO/3DO`, enabled `zip_mode: flatten` on the 3DO `CDs` query maps, and updated DB query filtering so `transform_zip` maps include archive-backed entries consistently.
- **`transform_zip` now handles `.7z` archives in query-map sync and browse flows**: The archive handling path was effectively ZIP-only even when `transform_zip: true` was set. Database sync now indexes `.7z` containers for hierarchical/file modes and expands `.7z` contents for `zip_mode: flatten`, while the archive helper, query-map listing, source-path resolution, and FUSE getattr/open paths now recognize `.7z` alongside `.zip`.
- **Testing 3DO source folders realigned after Native-share move damage**: The active `Testing/3DO/3DO.yaml` had drifted to singular `Software/Collection/...` paths while the repaired on-disk layout and live container view were using `Software/Collections/...`. Updated the active 3DO source config so future downloads and lookups target the repaired Native folders again.
- **`source_based` layout renamed to `legacy_source_based` and removed from current client configs**: The old layout mode name hid the fact that it rewrote configured source folders at download and query time. The rewrite behavior is now explicitly named `legacy_source_based`, current client configs now use `folder_based`, and nested-file fallback logic was decoupled from the legacy mode so existing maps can still resolve content in nested folders without silently changing the configured path.
- **3DO source folder config now matches `source_based` storage layout**: Updated the active Testing 3DO source config to use explicit `Software/Sources/...` folders for collection-style sources instead of `Software/Collections/...`, and aligned the managed 3DO NAS mount target to `Systems/3DO/3DO/Software/Sources/RetroRom-Collection`. This removes the mismatch between YAML source folders and the downloader's layout normalization for 3DO.
- **Editing a live Native external mount no longer leaves the old target mounted**: Updating a managed Native SMB mount previously only rewrote the saved config entry and did not reconcile the already-mounted live target. The update path now unmounts the existing live mount when mount-affecting fields change, then mounts the updated target if still enabled. Unmount cleanup also removes stale share-root helper mounts even if the target bind mount is already gone.
- **Native SMB mount action failed inside the container despite valid NAS credentials**: `app/native_mounts.py` was invoking `mount -t cifs`, which delegates to the `mount.cifs` userspace helper. In this Docker runtime the helper fails before any network mount attempt with `Unable to apply new capability set.`. After bypassing the helper, deep subpaths also needed helper-independent handling: the kernel mount path now uses inline auth options and mounts the share root first, then bind-mounts the requested SMB subpath into the Native target. This restores working managed Native SMB mounts for deep targets like `//host/share/path/to/subdir`.
- **Native SMB validation now reports auth/share/path failures explicitly**: Added an `smbclient`-based probe to managed Native mounts so validate and mount failures can distinguish authentication errors (`STATUS_LOGON_FAILURE`), missing shares, missing remote paths, and other SMB session failures instead of only returning the generic kernel CIFS mount error.
- **Snapshot workflow now supports explicit "lock baseline now" capture from Debug UI**: Added API endpoints to capture/list/compare locked directory snapshots (`/api/snapshots/capture`, `/api/snapshots`, `/api/snapshots/compare`) and new Debug tab controls to capture a verified TransFS path on demand. Snapshot tests (`tests/test_snapshots.py`, mirrored in `app/tests/test_snapshots.py`) now validate against these locked baselines in `tests/snapshots/locked/*.json`, so verified system/client combos remain stable unless intentionally re-captured.
- **Snapshot capture UI now uses client/system dropdowns with inferred path**: Replaced freeform snapshot name/path entry with client and system selectors, auto-generated snapshot name, and inferred path (`/mnt/transfs/{client}/{system}`) to reduce operator error when locking new baselines. Added `/api/snapshots/options` to provide exact configured client/system values for the UI.
- **Snapshot capture UI now uses client/system dropdowns with inferred path**: Replaced freeform snapshot name/path entry with client and system selectors, auto-generated snapshot name, and inferred path (`/mnt/transfs/{client}/{system}`) to reduce operator error when locking new baselines. Added `/api/snapshots/options` to provide exact configured client/system values for the UI.
- **Snapshot UI context dropdown now infers paths from `category_paths` in client YAML**: The `/api/snapshots/options` endpoint and Debug UI capture controls now read each client's `category_paths` config (e.g. `roms: "{name}/ROMS/{system_name}"` in `retrobat.yaml`) and the `category` field on each system map to derive the correct virtual path per context (ROMs, BIOS, Shared BIOS, etc.). A third "Context" dropdown appears when a system has multiple paths (e.g. RetroBat/3DO exposes ROMs → `/mnt/transfs/RetroBat/ROMS/3DO` and Shared BIOS → `/mnt/transfs/RetroBat/bios`); the context dropdown is hidden when there is only one path (e.g. MiSTer systems).
- **SYSTEMS tests aligned to Native/Systems filestore layout**: Updated `tests/test_systems.py` (and mirrored `app/tests/test_systems.py`) to use `source_base_path` values under `Native/Systems/...` and corrected the Archimedes byte-compare filestore reference to `/mnt/filestorefs/Native/Systems/Acorn/Archimedes/BIOS/riscos.rom`. This resolves stale path assertions after the storage layout migration.
- **SMB create-time timeout during foundation roundtrip writes**: `TransFS.setattr()` could delegate mode/ownership/size updates to `Passthrough.setattr()` with `fh=None`, which uses inode-mapped paths that may be virtual FUSE paths. Under SMB create flows this could recurse back through FUSE and stall the CREATE response (observed as `smbclient.open_file(..., mode="wb")` timing out). `app/transfs.py` now resolves a real backing path via `get_source_path_for_write()` / `get_source_path()` and applies non-time updates directly (`truncate/chmod/chown`) when no file handle is provided, avoiding recursive setattr deadlocks.
- **Skipped tests in Debug UI now show real pytest skip causes more reliably**: Updated `app/api.py` test-result parsing to normalize test file paths across `tests/...` and `app/tests/...` formats, capture inline `SKIPPED (reason)` text when present, and map `-rs` short-summary `SKIPPED [n] file:line: reason` lines back onto the correct skipped test entries in file order. This reduces fallback usage of the generic "Skipped (fixture or condition not met)" message.
- **CUE files missing from RetroBat FUSE listing when another client indexed the same file first**: `sync_database.py` was reusing the virtual filename from any existing DB record with matching `source_path`, even if that record belonged to a different client with different transforms. Changed the `existing_entry` check to be scoped to `source_path AND client`, so each client correctly computes its own virtual filename (e.g. `.chd` for RetroBat when a `CUE→CHD` transform is configured).
- **Database query short-circuits on first non-empty system-candidate**: `list_query_map` in `dirlisting.py` would `break` as soon as any system candidate (e.g. `3DO`) returned results, meaning files indexed under a differently-cased variant (`3do`) were silently ignored. Changed to accumulate results from all candidates and deduplicate by filename (preferring entries with a valid source path on disk).
- **`extension_map` not derived from `transforms` for directory listing**: Added explicit `extension_map: {CUE: CHD}` to the 3DO CDs map in `retrobat.yaml` so the `list_query_map` code path also renames the virtual extension, consistent with what the CHD transform produces.
- **Files inside zips (zip_mode: flatten) served with wrong size/content**: When `transform_zip: true` + `zip_mode: flatten` applied, `sync_database.py` stored the outer ZIP file's compressed size in the database instead of the inner file's uncompressed size. This caused FUSE to truncate the served data at the zip file size (e.g. 4493 bytes instead of 8192). Fixed in three places: `_add_file_to_database` now reads the uncompressed `file_size` from the zip's central directory, `_add_zip_entries_to_database` passes `info.file_size` directly to avoid re-opening the zip, and the single-file zip case in file-based maps was similarly corrected.

### Known Issues
- **SMB test hang after full suite run**: When running the full foundation test suite, SMB tests (`TestSmbFoundation`) hang after other tests complete. Individual SMB tests run successfully. **Workaround**: Run non-SMB foundation tests with `pytest tests/test_foundation.py -m "not slow"`, or run SMB tests separately. Root cause appears to be lingering state in Samba/FUSE after write-cleanup operations.

### Added
- **Windows setup script can relink RetroBat `roms` and `bios` to mapped TransFS drives**: Extended the generated `setup_windows.ps1` flow to detect a RetroBat install, and after drive mappings plus any optional BIOS copy/config updates, offer to replace local `roms` and `bios` directories with symbolic links to the mapped RetroBat drive. Existing real directories are preserved by renaming them to `<name>_bak` (or `<name>_bakN` if needed) before the symlink is created.
- **FUSE-layer config reload without container restart**: Added `/api/fuse/reload-config` endpoint to reload configuration directly in the running FUSE process. Uses SIGHUP signal handler to safely reapply client/source mappings, clear caches, and reinitialize data providers without unmounting the filesystem or losing in-flight operations.
- **Runtime config reload endpoint**: Added `/api/config/reload` endpoint to reload client and source mapping configurations from disk without container restart. Clears config cache in the web service immediately; FUSE process now reloads via the `/api/fuse/reload-config` endpoint (see above).
- **Debug tab UI restructuring**: Merged Test Results and Logs tabs into a new unified "Debug" tab (only visible when Advanced Options enabled). Debug tab includes three sub-sections: Test Results (pytest suite execution), Logs (FUSE activity), and Config & System (active config sets and reload controls).
- **Config reload UI controls**: Added Config & System sub-section in Debug tab with reload button and real-time display of active client/source config sets, plus clear messaging about scope (web service vs. FUSE-layer changes).
- **IA-COL pack installation support**: Pack sources with type `IA-COL` (Internet Archive collections) are now fully supported during pack installation, using the same `download_ia_collection` path as the per-system download endpoint. Filetypes filtering from the source definition is also honoured.
- **IA-COL handles single items as well as true collections**: `download_ia_collection` now first attempts a collection search (`collection:<id>`); if that returns no results it falls back to treating the identifier as a direct single IA item. This fixes sources like `https://archive.org/details/rr-3do` which are single items containing many files, not collections of sub-items.

### Fixed
- **Duplicate 3DO / 3do entries on downloader page**: `mame.yaml` had `manufacturer: 3do` and `system_mapping_name: 3do` (all lowercase), causing MAME's 3DO system to appear as a separate `3do` entry alongside the shared `3DO` entry from MiSTer and RetroBat. Changed to `manufacturer: 3DO` / `system_mapping_name: 3DO` to match the other clients.
- **"Bioses Only" pack incorrectly downloaded 3DO interactive sampler**: `just-bio` in `Testing/3DO/3DO.yaml` had `sources: [bios, 3do-interactive-samplers]` despite its description saying "Essential BIOS files no software". Removed `3do-interactive-samplers` from the sources list.
- **IA-COL download failed with read timeout on large collections**: `download_ia_collection` was passing all files in one batch call to `ia_item.download()`, which hit the library's 12-second default timeout. Now downloads one file at a time with a 300-second per-file timeout, giving per-file progress and isolated error handling. Also skips IA-generated metadata files (thumbnails, `_files.xml`, `.torrent`, etc.) unless an explicit `filetypes` filter is configured.

### Fixed
- **Database sync blocking event loop during large pack installs**: The post-install database sync (`update_db=true`) in the install endpoint ran `DatabaseSync.full_sync()` directly in the async generator, blocking FastAPI's event loop while processing potentially hundreds of files. Any concurrent request (e.g. pressing "Update DB" during install) would fail with "Database sync connection error" / "Failed to fetch". Fixed by offloading the sync to a thread executor via `asyncio.get_running_loop().run_in_executor()`.
- **Double database sync on "Install + Update DB"**: `submitInstallAndUpdateDb()` was calling `submitInstallPacks(true)` (triggering a server-side inline sync) AND then calling `runDbSync()` (triggering a second SSE sync). This caused the sync to run twice and meant the SSE sync was connecting while the inline sync was still blocking the event loop. Fixed by passing `update_db=false` to the install step so the server-side inline sync is skipped, and the single client-side SSE sync (with real-time progress) handles everything.

### Fixed
- **FUSE LOOKUP for system directories under category paths no longer fails after kernel cache expiry**: Fixed `GETATTR` virtual-directory fallback in `transfs.py` to return a synthetic directory stat for any entry that appears in its parent's `parse_trans_path` listing but has no physical path (e.g. `RetroBat/ROMS/3DO` where `ROMS` is a category prefix and `3DO` is a system name). Previously, after the 60-second kernel entry cache expired, a re-validation LOOKUP for `3DO` would return ENOENT, making the directory invisible to `stat`, tab completion, and SMB clients. The full path `ROMS/3DO/CDs` and its files are now persistently accessible.
- **Removed leftover `[CRITICAL]` debug warning logs from `list_query_map`**: Four `logger.warning("[CRITICAL] ...")` lines that were added during development are now removed from `dirlisting.py`, eliminating log noise on every virtual directory listing.
- **RetroBat shared BIOS 3DO file maps now resolve from the actual Native layout**: Updated `app/config/clients/default/retrobat.yaml` system `local_base_path` values to include the `Systems/` prefix (`Systems/3DO/3DO`, `Systems/Acorn/Atom`) so category-shared BIOS file maps resolve to existing paths under `/mnt/filestorefs/Native/Systems/...` and correctly surface files like `panafz1.bin`, `panafz10.bin`, and `goldstar.bin` at `/mnt/transfs/RetroBat/bios`.
- **RetroBat symlink setup no longer depends on accepting new drive mappings**: Updated generated Windows setup flow so declining all mapping prompts (`N:`/`R:`/`M:`) no longer silently skips RetroBat symlink configuration. When RetroBat is detected and mapping is skipped, setup now offers a symlink-only path that reuses an existing RetroBat mapped drive (for example `R:`) when available.
- **ROM backup merge option temporarily removed from setup symlink flow**: Disabled ROM backup content merge prompts and copy operations in both elevated and non-elevated link paths. BIOS merge prompt/copy remains available. This avoids writing ROM backup contents into virtual RetroBat targets while Native-share ROM write-back design is finalized.
- **Backup merge failures no longer abort successful link creation**: When post-link backup merge encounters write-protected or read-only targets (for example virtual RetroBat share paths), setup now logs a warning and continues instead of failing the entire symlink/junction operation.
- **Elevated symlink flow now uses UNC targets and correct success semantics**: Updated non-admin elevation path to pass UNC-based RetroBat targets (`RemotePath`) into the elevated helper so admin context does not rely on user-scoped mapped drives (for example missing `R:` in elevated session). Also corrected elevated return handling so `success=true` with `changed=false` is treated as a successful no-op instead of prompting junction fallback.
- **Elevated link helper no longer crashes before logging**: Fixed PowerShell string interpolation in generated elevated helper payload (`$Label:` to `${Label}:`) so the elevated script parses correctly and can emit log/result artifacts instead of exiting immediately with code 1.
- **UAC elevated helper now stores temp artifacts in a shared location**: Switched temporary elevated script/log/result files from user-specific `%TEMP%` to `Public\Documents\TransFS\SetupTemp` so elevation under alternate admin credentials can still read and write diagnostics/result files. This prevents immediate elevated exits with missing log/result artifacts.
- **Elevated log-read retry loop no longer hangs parent setup session**: Fixed a retry-loop bug in the Windows setup elevated-link flow where missing log files could leave the parent PowerShell session spinning indefinitely without returning control. Retry attempts now advance deterministically and exit with diagnostics when no log content is available.
- **RetroBat link setup now uses an elevation-first non-interactive symlink phase**: Non-admin runs now prompt for UAC elevation to create proper Windows symbolic links, collect merge choices in the parent process, and execute the elevated phase with fixed arguments only (no child prompts). Elevated completion now returns structured result data via a temp result file with clearer failure diagnostics, and offers explicit junction fallback only if elevation fails or is declined.
- **UAC symlink flow no longer blocks on hidden elevated prompts**: Updated the elevated RetroBat link helper to run non-interactive, skip automatic ROM backup merge in elevated mode by default, and enforce a bounded wait with timeout diagnostics. This prevents apparent hangs after accepting the UAC prompt and reports when an elevated window remains blocked.
- **Windows setup script now includes RetroBat detection diagnostics**: Added detailed install discovery logging for RetroBat (registry sources + fallback paths), prints all valid install candidates, and prompts the user to choose when multiple installs are found. This makes setup behavior explicit when installs are ambiguous.
- **RetroBat link setup now offers backup merge into symlink targets**: After `roms`/`bios` are swapped to links, the script now prompts to merge files from `<name>_bak` into the linked folder (additive copy, no wipe). Default is `Y` when a link was just created, and `N` when a link already existed.
- **Windows setup symlink step now uses UAC elevation when needed**: Updated generated `setup_windows.ps1` so RetroBat `roms`/`bios` link replacement can request Administrator privileges via UAC before any rename/link operations. This avoids partial states where folders were backed up but symlink creation failed due to insufficient rights.
- **Legacy RetroBat BIOS copy flow temporarily gated off by default**: Added `EnableLegacyRetroBatBiosCopy` script flag (default `false`) so the previous BIOS copy/config update step is skipped while symlink-based folder redirection is being validated. The legacy code path remains in place for re-enable if needed.
- **FUSE reload now clears DB readdir cache**: Updated `TransFS.reload_config_from_disk()` to clear `_db_readdir_cache` in addition to config/source caches. This prevents stale DB-backed directory listings from persisting after config changes (for example stale `CDs` emptiness or old map names).
- **RetroBat 3DO extension set restored**: Reverted temporary 3DO map extension edits in `retrobat.yaml` so `CDs` uses `CUE` and `BIOS` uses `ROM`, matching expected RetroBat behavior.
- **RetroBat shared BIOS source accidentally crossed into system tree**: Removed the client-level `shared_bios` query map in `retrobat.yaml` that pointed to `../Systems/Acorn/Atom/Software/BIOS/retrobat-bios-main`. RetroBat shared BIOS now resolves only from its client-scoped path (`Clients/RetroBat/bios`), preventing unintended cross-client/system content bleed into `/RetroBat/bios`.
- **Mixed map-type system root listings filtered out query maps**: Fixed `app/transfs.py` database-mode `readdir` behavior for system roots that contain a mix of file maps (for example BIOS files like `panafz1.bin`) and directory/query maps (for example `CDs`, `BIOS`). The previous classifier only emitted synthetic directories when entries were all dir-like, causing mixed systems such as RetroBat `3DO` to return zero visible entries at `/RetroBat/ROMS/3DO` even when DB rows existed. The handler now processes dir-like config entries per-entry and emits synthetic directory entries for query maps while still allowing file-like entries when present.
- **Query-map file entries misclassified as directories**: Fixed `readdir` config-entry type detection so maps containing a single extension set (for example only `.cue`) are treated as files, not folders. Also made category-path map detection in FUSE database-only mode aware of `/client/category/system/map` paths to keep file typing consistent in RetroBat category routes.
- **RetroBat 3DO category path visibility and map resolution**: Fixed category-path browsing so configured systems are merged with DB-discovered entries at `/RetroBat/ROMS`, made category matching case-insensitive, and corrected map/subpath parsing for category routes like `/RetroBat/ROMS/3DO/CDs`. Also added resilient query-map DB system key fallbacks (including lowercase legacy values) and recursive source-based filesystem fallback so nested source folders can surface entries when DB sync lags.
- **RetroBat 3DO ROMS visibility**: Added the missing `category: roms` assignment to the RetroBat `3DO -> CDs` query map so the system now appears under `/mnt/transfs/RetroBat/ROMS/3DO` alongside other ROM-category systems.
- **Download Systems list cross-client name/case consistency**: Updated merged systems metadata to prefer canonical `system_mapping_name` for fallback display labels (instead of client-local `name`), and hardened client-filter matching in the Download UI to compare `display_name`/`mapping_name`/`name` case-insensitively. This prevents mixed-client casing differences (for example `3do` vs `3DO`) from producing inconsistent system labels or filtering.
- **Config UI database mode options aligned with backend behavior**: Updated `Configuration -> Database -> Mode` dropdown to expose only supported runtime values (`enabled`, `hybrid`, `disabled`) and removed stale legacy options (`memory`, `sqlite`). Config loading now normalizes unknown/legacy mode values to `enabled` so saved settings remain valid.
- **DAT/XML metadata scan false-zero matching on large folders**: Fixed Metadata scan behavior so preview matching is no longer biased to the first scanned files. Scan now counts actual files processed, collects matched results (instead of early unmatched samples), and stops after reaching the requested match limit. This prevents `files_scanned` high / `matches_found=0` outcomes caused by early directory ordering.
- **DAT/XML Atom cassette provider path resilience + matcher crash fix**: Fixed DAT/XML matcher normalization call (`normalize_name`) and added fallback XML path resolution for missing configured DAT/XML files by checking common MAME hash locations (including RetroBat hash paths). This addresses Atom cassette scans failing when `atom_cass.xml` is present but not at the hardcoded configured path.
- **Metadata delete-all action now has inline danger-zone warning**: Added a persistent red warning message beside the **Delete All Metadata** control in the Metadata Browser so destructive impact is visible before opening the confirmation prompts.
- **Metadata browser deletion controls added with confirmations**: Added a **Delete This Record** action in the Metadata Editor to remove metadata/tags/pack links for the currently open file, and a **Delete All Metadata** action in the Metadata Browser with a typed confirmation (`DELETE ALL METADATA`) before clearing all metadata records.
- **Metadata Generate Client Config now clearly marked and advanced-gated**: Added an in-panel warning that DAT-based client config generation is a work-in-progress and does not yet produce a complete config. The entire **Generate client config** section on Metadata is now hidden unless `ui.advanced_options` is enabled, and the Config-tab toggle label is renamed to **Enable Advanced and Incomplete Options and features**.
- **DAT-generated maps now use full DAT directory paths**: Metadata DAT client config generation now groups entries by full imported DAT folder path (`top_level_dir/relative_dir`) instead of only top-level folder names. Generated map names and `query.source_dir` now align to deep DAT paths (for example `games/TI-99_4A/...`) so map definitions no longer collapse to just `games`.
- **DAT-generated client maps now preserve deeper source_based paths**: DAT config generation now emits map `query.source_dir` roots under `Software/Sources/<top_level>` (and `Software/Sources` for root entries) instead of `Software/<top_level>`, aligning with source_based layout resolution so nested DAT paths are preserved correctly under each generated map.
- **Metadata importer log continuity + generate auto-selection**: Import/upload/generate actions now append to the shared metadata log instead of clearing prior output, and completed DAT imports now auto-select the newly imported catalog for config generation to avoid immediate "Select an imported DAT first" skips.
- **Metadata direct-route initialization gap**: Visiting `/metadata` directly after refresh now loads DAT importer dependencies (File Format options from `xml_formats`, DAT file list, imported catalogs, and configured-client combobox suggestions) instead of only loading metadata stats/entries.
- **Metadata importer naming and field discoverability**: Renamed DAT `xml_format` UI label to **File Format**, updated related status text, and added field-name tooltips to all inputs in the **Generate client config** section so field purpose remains visible after values are populated.
- **Imported catalog client-name combobox coverage**: Updated the imported-catalog generate panel so the field formerly shown as `System name` is now presented as `Client name` and populated from configured client names (`config/clients/*`) via combobox suggestions while still allowing custom typed values.
- **Metadata DAT importer list/render UX tuning**: Reworked Metadata-tab importer layout so upload appears before DAT selection, moved `xml_format` adjacent to DAT import action, and removed selection-triggered DAT list re-fetches to prevent UI stalls/non-population during selection changes.
- **Metadata DAT importer defaults and config generation UX**: DAT folder is now implied from `app.yaml` `filestore` (`<filestore>/Native/DATs`) instead of user-editable input; DAT selection now auto-fills blank config-set name from the selected DAT filename (without extension); client name suggestions are now provided as a combobox from configured client names under `config/clients/*`.
- **Metadata API startup regression after DAT upload endpoint**: Added `python-multipart` dependency so FastAPI can register multipart `File`/`Form` routes (used by DAT browser upload) without crashing app startup.
- **Metadata DAT importer control clarity + local upload**: Simplified Metadata-tab DAT importer flow to remove ambiguous duplicate path entry, replaced DAT file entry with a dropdown populated from the selected DAT folder, and added browser-based DAT/XML upload to the current DAT folder before import.
- **CRITICAL: Memory-mapped I/O optimization for large file reads**: Implemented configurable memory-mapped file I/O (`mmap`) in `app/transfs.py` to address performance bottleneck when reading large files (VHDs, CD-ROM ISOs) over SMB/CIFS. The previous `os.read()` loop implementation, while ensuring data integrity, suffered from 3x iteration overhead due to FUSE kernel's ~65KB read limit - resulting in ~5MB/sec throughput (20 seconds for 101MB VHD). The new implementation creates read-only memory maps for files exceeding a configurable threshold (default 10MB), allowing direct memory-to-memory copies that bypass FUSE chunking entirely. Configuration added to `app/config/app.yaml`: `performance.use_mmap_for_reads` (default: true) and `performance.mmap_threshold_bytes` (default: 10485760). The `read()` method now uses dual-path logic: mmap slice `[off:read_end]` for mapped files (fast path) with automatic fallback to `os.read()` loop if mmap unavailable or disabled (compatible path). Memory maps are created in `open()` for files > threshold and cleaned up in `release()` to prevent leaks. Expected performance improvement: >10MB/sec effective throughput for large sequential reads, maintaining "download once, read in many ways" architecture without file duplication or FUSE bypass.
- **CRITICAL: Incomplete reads for large files over SMB/CIFS**: Fixed `app/transfs.py` `read()` method to handle POSIX short reads correctly. The previous implementation used a single `os.read(fh, size)` call which can legally return fewer bytes than requested without error. Testing confirmed that the FUSE kernel driver returns only ~65KB per `os.read()` call regardless of the requested size, requiring multiple iterations (e.g., 3 iterations for a 131KB request). Without this fix, only the first partial chunk was returned, causing incomplete data transfer for large files (e.g., 101MB VHD images) accessed over SMB/CIFS. This resulted in MD5 checksum mismatches and boot failures on MiSTer FPGA. The fix wraps `os.read()` in a loop that continues reading until the full requested size is obtained or EOF is reached. Testing shows MD5 checksums now match correctly (`1709a677f957e35cc8a7ffaac0e35f16`) vs wrong hash (`a0ff320b0190b55227b891404bb67d90`) before fix. The ~65KB FUSE read limit appears to be a kernel pipe buffer constraint, not a configuration issue - this is a known FUSE behavior. Performance impact: 101MB file takes ~20s over SMB/CIFS (~5MB/sec), which is slower than ideal but ensures data integrity. Increased SMB `max xmit` to 1MB to reduce protocol overhead.
- **CRITICAL: SMB durable handles re-enabled to fix orphaned FUSE handles**: Re-enabled `smb2 leases = yes` and `durable handles = yes` in `platform/linux/smb.conf` (both were disabled on Feb 14 for PCW compatibility). Disabling these settings prevented Samba from maintaining handle state across SMB session reconnects, causing FUSE to never receive `release()` or `forget()` callbacks when clients disconnected abnormally. This resulted in persistent orphaned file handles that made files appear missing or empty to subsequent CIFS clients. Durable handles allow SMB sessions to survive temporary disconnects and preserve file handle continuity, which is essential for FUSE lifecycle management. This fix resolves the stale-handle symptoms observed on MiSTer VHD access and intermittent pytest SMB test failures.
- **FUSE inode forget file-descriptor cleanup**: Fixed `app/passthroughfs.py` `forget()` to correctly handle inode→fd mappings stored as a single integer fd. Previous logic attempted `list(fd)` and could fail cleanup during inode forget/disconnect paths, leaving open handles behind. Cleanup now supports int/list/tuple/set mappings and removes closed fds from reverse maps.
- **SMB session stability hardening for MiSTer VHD access**: Added keepalive-focused Samba settings in `platform/linux/smb.conf` (`deadtime=0`, `keepalive=30`, `socket options=TCP_NODELAY IPTOS_LOWDELAY SO_KEEPALIVE`, `stat cache=no`) to reduce CIFS idle timeout reconnects and stale-handle behavior under repeated VHD reads. Also reverted unsupported pyfuse3 mount options in `app/transfs.py` that previously prevented FUSE from mounting.
- **AcornAtom build script path resilience**: Hardened `app/build_scripts/MiSTer/Acorn/Atom/build.sh` to work with both legacy (`Software/`) and source_based (`Software/Sources/`) layout patterns. Script now uses dual-candidate path resolution for software sources and blank VHD templates, with deterministic sorted fallback selection. Added sanity checks for critical boot files (`/MENU`, `/SPLASH1`, `/SPLASH2`) in generated VHD to catch incomplete builds early.
- **AcornAtom HDs listed-file open mismatch**: Fixed query-map source resolution in `app/sourcepath.py` where files could appear in `/MiSTer/AcornAtom/HDs` but fail to open (`ENOENT`) due to incorrect fallback to `.../Atom/HDs/<file>`. Query-map resolution now tries both `source_based`-adjusted and raw `source_dir` paths, and avoids generic physical fallback for unresolved query-map file paths.
- **FILE map entries missing from system directory listings**: Fixed `list_maps()` in `/api/browse` so that configured FILE maps (like `boot.vhd`) are now merged with database-discovered QUERY maps. Previously, when the database returned any results, FILE maps were silently dropped from the listing. Fixed by changing the logic to always include configured maps and then merge database entries, ensuring FILE maps are visible in the virtual browser.
- **Virtual browse fidelity to FUSE restored**: Reverted `/api/browse` bypass logic for virtual paths so the Web UI browse view is again sourced directly from the live FUSE mount (`/mnt/transfs`) rather than config-derived shortcuts.
- **Virtual browse entry type regression**: Corrected `/api/browse` fast-path typing at system root so file maps (for example `boot.vhd`) are returned as `file` rather than `directory`.
- **Virtual browser slow folder open on MiSTer system roots**: Optimized `/api/browse` for `/mnt/transfs/<client>/<system>` paths by bypassing expensive FUSE `exists/isdir/scandir` calls and using direct virtual map listing from config. This removes cross-contention delays from unrelated heavy FUSE scans and reduces AcornElectron browse latency from ~40-50s to sub-second warm responses.
- **Virtual browser metadata info error**: Fixed `/file-metadata` endpoint failures caused by dict-style DB rows being unpacked as tuples (`"invalid input syntax for type integer: 'file_id'"`). Endpoint now supports both dict and tuple row formats and includes case-insensitive path lookup fallback for virtual path casing differences.
- **File metadata API import error**: Fixed missing `get_cursor` import in `/file-metadata` endpoint that caused "Database query failed: name 'get_cursor' is not defined" error when clicking [i] button in virtual browser.
- **YAML null handling in virtual directory detection**: Fixed crash when YAML config has `maps:` set to null/empty. Code now uses `.get('maps') or []` pattern to handle None values returned from YAML parsing.
- **SMB test connection state management**: Added session cleanup before attempting new SMB connections to prevent state leakage between test runs.

### Validated
- **Real-world MiSTer core validation after SMB/FUSE fixes**: Verified in real-world use that MiSTer core flows are now stable and fast for `Acorn Atom`, `Acorn Archimedes`, and `Atari 5200` with the current durable-handle + short-read + mmap stack. Observed behavior: no stale-handle regressions, correct file integrity, and significantly improved large-file access latency.

### Added
- **Explicit DAT importer workflow on Metadata tab**: Added a manual DAT/XML importer panel to the Metadata web UI with `xml_format` selection, default DAT folder discovery under `/mnt/filestorefs/Native/DATs`, suggested new/changed DAT detection, tracked import history, and live polling-based import logs while catalogs are parsed and written to the database.
- **Imported DAT catalog database support**: Added tracked `dat_imports` and `dat_import_entries` storage so DAT/XML catalogs can be explicitly imported once and then re-used as metadata providers (`imported_dat_lookup`) for scan/apply workflows.
- **DAT-driven client config generation**: Added Metadata-tab tooling and API support to generate/update client config-set YAML files from imported DAT path structures (including MiSTer Organizer-style ROM paths), prompting for config set and system details before writing `config/clients/<set>/...`.

### Changed
- **Logiqx DAT parsing expanded for path-aware catalogs**: XML format support now includes ROM-level `name_attr` extraction so importer/catalog flows can preserve nested DAT path structures while still indexing by filename and checksum.

### Added
- **TransFS file-handle lifecycle diagnostics**: Added structured `open/read/release` instrumentation in `app/transfs.py` to trace per-handle lifetime, read counts/offsets, byte totals, read error counts, and slow-read warnings (`>250ms`). This improves root-cause visibility for intermittent stale-handle and empty-image symptoms on SMB clients.
- **Virtual browser copy-to-clipboard button**: Added 📋 button next to [i] info and Zaparoo launch buttons in the virtual browser to copy file paths to clipboard
  - Copies full virtual path (e.g., `/mnt/transfs/MiSTer/AcornAtom/boot.vhd`)
  - Shows success toast notification and briefly displays ✓ checkmark on button
  - Uses modern Clipboard API with fallback error handling
- **Browse Native "Sync contents" action**: Added a button in the Browse Native tab to trigger database sync for the current native folder path directly from the UI.
- **SMB-layer foundation tests**: Added `TestSmbFoundation` class in `tests/test_foundation.py` with two comprehensive SMB protocol tests
  - `test_smb_write_read_delete_roundtrip`: End-to-end write/read/delete validation over SMB share
  - `test_smb_can_read_large_file_over_1mb`: Large file (2MB) integrity test with size and SHA256 hash verification
  - Added `smbprotocol>=1.13.0` dependency for SMB2/SMB3 protocol testing
  - Tests dynamically fall back to share root when expected subdirectories are absent
  - Marked with `@pytest.mark.slow` to allow skipping in quick test runs
- **Startup hot-path pre-warming**: Added `app/startup_prewarm.py` to pre-load critical paths before FUSE mount completes
  - Reduces cold-start delays from 550-760ms to sub-millisecond (0.6-1.0ms) on frequently-accessed paths
  - Configuration in `app/config/app.yaml` via `startup_prewarm` section
  - Pre-builds recursive filename indexes for large source directories (eliminates 8+ second cold-start delays)
  - Configurable hot paths and subdirectory prewarm behavior
- **Enhanced recursive filename indexing**: Comprehensive logging and extended TTL in `app/sourcepath.py`
  - Cache hits/misses, scan time, and file count logging
  - Increased TTL from 30s to 900s (15 minutes) to avoid repeated expensive scans
  - Pre-warming eliminates silent delays on first file access (e.g., joeblade.dsk 8.8-second scan issue)
- **Setup Clients connection profile API**: Added `/api/setup/connection-profile` to publish externally reachable SMB setup details (host, port, share, auth mode, commands).
- **Setup Clients web tab**: Added a dedicated dashboard tab showing working SMB connection details for Windows and MiSTer clients.
- **Dynamic Windows setup script download**: `/api/download/setup-windows` now injects host/port/share/username from the resolved setup profile.
- **N:/R:/M: drive mapping architecture**: Redesigned `setup_windows.ps1.template` with purpose-specific drive letter mappings
  - **N:** → `/Native` - Direct filestore access (bypass mode) with optional mapping
  - **R:** → `/RetroBat` - Auto-detected RetroBat installation with virtual filesystem mapping
  - **M:** → `/Mame` - Auto-detected standalone MAME installation with virtual filesystem mapping
  - Added `Get-MameInstallDir` function for standalone MAME detection (registry + common install paths)
  - Simplified connection configuration with `Get-ConnectionConfig` replacing complex mode selection
  - Modular mapping functions (`Offer-NativeMapping`, `Offer-RetroBatMapping`, `Offer-MameMapping`)
  - Each mapping is optional and detection-based (Native always offered, RetroBat/Mame only if installed)
  - RetroBat BIOS copy now requires Native mapping for direct filestore write access
  - Improved UX with clear visual separators and explanatory text for each mapping option
- **Configurable hidden file visibility**: Added `show_hidden_files` option in `app.yaml` (default: `true`) to control visibility of dotfiles
  - Now shows hidden files by default to match standard filesystem behavior and maximize client compatibility
  - Can be set to `false` to hide metadata files like `.DS_Store`, `.git`, etc. from emulator views
  - Applies to directory listings in FUSE, database sync, and all virtual path resolution
  - Resolves issue where admin tools (e.g., writability probes) failed when using hidden temp files

### Added
- **Metadata provider subsystem (phase 1)**: Added dedicated metadata scanning/apply flow with pluggable providers in `app/metadata/providers.py`.
  - Provider registry now combines filename-ruleset providers (from `config/metadata/rulesets`) and DAT/XML providers (from `config/metadata/providers/<active_source_set>.yaml`, fallback `default.yaml`).
  - Initial DAT/XML adapter supports MAME software-list XML (`format: mame_softwarelist`) with filename-first matching and checksum fallback (`sha1`/`crc32`).
  - New API endpoints:
    - `GET /api/metadata/providers`
    - `POST /api/metadata/scan-preview`
    - `POST /api/metadata/apply`
  - Added default provider config: `app/config/metadata/providers/default.yaml`.
- **Metadata dashboard tab**: Added a new `Metadata` tab (to the right of Download) with `/mnt/transfs` folder browsing, provider selection, scan preview, apply action, and deep-link routing via `/metadata`.
- **Config-driven XML metadata format templates**: Added `config/metadata/xml_formats/<active_source_set>.yaml` (fallback `default.yaml`) to define DAT/XML field extraction declaratively (record path, metadata field mapping, filename source, checksum nodes/attributes, static tags). New XML formats can now be introduced by config only, without Python code changes.
 
### Performance
- **Startup prewarm optimization**: Added cached config-entry parsing and DB-entry reuse for database-mode `readdir` in `app/transfs.py`
  - Reduces repeated expensive adapter and parse calls
  - Pre-loads critical paths (RetroBat/bios, AcornAtom maps) before FUSE mount
- **Recursive filename scan optimization**: Replaced repeated recursive scans with indexed lookup caches
  - Applied in `app/sourcepath.py` and `app/dirlisting.py` for flattened query fallback and ZIP discovery
  - Increased subdirectory query cache TTL to reduce repeated startup/browse DB load
- **PostgreSQL prefix-like index**: Added `idx_files_virtual_path_like` with `text_pattern_ops` in `app/db/schema.py`
  - Accelerates `virtual_path LIKE 'prefix%'` lookups used by subdirectory discovery
- **Subdirectory SQL optimization**: Optimized to compute prefix substring once via CTE in `app/dirlisting.py`
- **Database connection pooling**: Increased from 15 to 150 total connections (50 pool size + 100 max overflow)
  - Prevents "connection pool exhausted" errors during recursive directory operations
  - PostgreSQL server connection limit increased from 100 to 200 connections
  - Fixes multi-folder deletion operations that were previously blocked

### Changed
- **Pack metadata ownership migrated to source-level (with compatibility fallback)**: Database sync metadata enrichment now prefers `sources[].metadata` as the authoritative default metadata location, enabling different metadata defaults per source within the same pack. Legacy `packs[].metadata` is still supported as a fallback for backward compatibility, preserving existing behavior until configs are migrated.
- **Metadata scanner root path corrected**: Updated the Metadata web UI and API validation to use `/mnt/filestorefs` as the default and allowed scan root instead of `/mnt/transfs`, so scans target the native/downloaded content store directly.
- **Metadata UX split by purpose**: Moved scanner actions from the Metadata tab into the Browse Native tab (folder-context workflow), and repurposed the Metadata tab into a metadata browser/editor foundation with stats, filtering, and paginated metadata entry listing.
- **Metadata tab editor flow expanded**: Added inline edit support in the Metadata tab for key fields (`title`, `release_year`, `publisher`, `region`, `language`, `is_prototype`, `is_homebrew`) with save/reload behavior integrated into the metadata list view.
- **Metadata schema coverage exposed in API/UI**: Expanded `GET /api/metadata/entries` to include schema-backed file context and metadata fields (native/virtual paths, original extension, system/client/map/content type, archive state, normalized metadata vocab fields, provenance, tags, and pack lineage).
- **Metadata editor expanded to schema-backed fields**: `POST /api/metadata/entry/update` and Metadata tab editor now support editing extended file/metadata fields plus `metadata_tags` and `pack_names` associations.
- **Metadata editor safety toggle**: Added a default-off **Allow advanced edits** control in the Metadata editor so risky core file fields (paths/system/client/map/archive) remain visible but read-only unless explicitly enabled; these fields are only sent in update payloads when advanced mode is on.
- **Metadata editor field hover help**: Added per-field hover tooltips in the Metadata editor (including current value context) so field meaning remains visible after placeholders disappear.
- **Metadata editor read-only padlock styling**: Updated risky disabled fields to show an inline orange padlock inside the field (right side) while advanced edits are disabled, replacing the separate read-only badge chips.
- **Metadata editor lock icon visual refinement**: Tuned the inline padlock to a lighter orange and smaller size for a less intrusive look while preserving the read-only cue.
- **Metadata schema forward-compat**: Extended `file_metadata` schema with optional provenance columns (`metadata_provider`, `metadata_source`, `metadata_applied_at`) for new installs and runtime `ALTER TABLE ... IF NOT EXISTS` backfill on existing databases.
- **SMB create/read lookup consistency**: Fixed `lookup()` path resolution to use the virtual mount context and added writable-path existence fallback so newly created SMB files are immediately discoverable for read/delete operations.
- **MAME hash cache relocated out of config**: Cache files now live under `/mnt/filestorefs/Native/Clients/Mame/mame_cache` (configurable via `mame.hash_cache_dir`) instead of `app/config/mame_cache`, with automatic migration of existing cached XML files.
- **MAME cache path visibility**: Startup now logs the effective MAME hash cache directory (or that caching is disabled) to make runtime behavior explicit.
- **Test Results run status UX**: Replaced coarse percentage progress bar with an explicit run-state indicator (`In progress` / `Complete`) and removed misleading percent text during test execution.
- **Downloader action semantics fixed**: "Install/Download Only" no longer triggers automatic database sync; only "Install & Update DB" runs download + sync in one action.
- **Setup Clients tab URL routing**: Clicking Setup Clients now updates the browser route to `/setup` (instead of `/`) for direct linking and consistent navigation.
- **Pack downloader log destination visibility**: Downloader install stream now prints native mount destination paths (base path and per-source destination folders) so the UI log shows exactly where files are written.
- **Metadata browser APIs**: Added `GET /api/metadata/stats` and `GET /api/metadata/entries` for metadata coverage and filtered/paginated metadata browsing from the web UI.
- **Metadata API startup resilience**: Metadata browser/editor endpoints now perform best-effort DB pool initialization and schema compatibility backfill at request time, fixing `Database not initialized` and missing-column failures on existing deployments.
- **Docker startup sequence optimization**: Updated `docker-compose.yml` to start Samba immediately after FUSE launch
  - Extended FUSE mount timeout from 30s to 120s to accommodate slow prewarm operations
  - Changed mount failure from hard error (`exit 1`) to warning, allowing service continuation
  - Prevents premature container exits that blocked SMB-level validation
  - Samba now starts before FUSE readiness checks complete
- **Removed hardcoded "Native" virtual client folder**: Removed from `/mnt/transfs` root since we now use separate SMB shares (TransFS virtual + TransFSNative native) for filesystem access
- **RetroBat/Acorn Atom directory listing performance**: Hardened `readdir` caching and query-map path resolution to reduce repeated expensive lookups during emulator probe bursts.
  - Added cached config-entry parsing for database-mode `readdir` calls in `app/transfs.py`.
  - Reused database `readdir` results in main database-mode path via `_db_readdir_cache` instead of re-querying adapter each call.
  - Replaced recursive filename scans with indexed recursive lookup caches in `app/sourcepath.py` and `app/dirlisting.py` for flattened query-map fallback and ZIP discovery.
  - Increased subdirectory query result cache TTL in `app/dirlisting.py` to reduce repeated DB pressure during startup and browse bursts.
- **Database prefix-query optimization**: Added `idx_files_virtual_path_like` (`text_pattern_ops`) in `app/db/schema.py` to improve `virtual_path LIKE 'prefix%'` lookups used by subdirectory discovery.
- **Advertised SMB endpoint (Approach B)**: Added optional compose environment overrides `SMB_ADVERTISE_HOST`, `SMB_ADVERTISE_PORT`, and `SMB_ADVERTISE_SHARE` for explicit client-facing setup values.
- **Dev compose LAN host default**: Updated `SMB_ADVERTISE_HOST` default in compose for this environment so Setup Clients and generated scripts point to a network-reachable host.
- **Project Housekeeping (Legacy Archival)**: Moved temporary development artifacts out of project root into `legacy/`
- **Linux platform file layout**: Moved Samba runtime assets from repo root into `platform/linux/` (`smb.conf`, `smbusers`) and updated build/runtime scripts (`Dockerfile`, `run_local.sh`) to use the new paths.
- **Client-level global maps support**: Added runtime support for client-level `maps` + `local_base_path` so shared content (e.g., `Native/Clients/RetroBat/bios`) can be mapped once per client and merged with system-specific mappings (e.g., `atom.zip`) under `/RetroBat/bios`
- **Dual-share SMB architecture**: Added a dedicated native SMB share (`TransFSNative`) and removed the `Native` bind-mount into `/mnt/transfs`, separating virtual and native access at the share level.
- **Windows setup dual-drive flow**: Updated setup profile/script generation and both setup templates to capture, validate, persist, and reuse separate virtual/native drive mappings (including distinct share names and drive letters).
- **Windows virtual mapping path correction**: Setup profile and scripts now target `\\<host>\TransFS\RetroBat` for the virtual Windows mapping (instead of share root), and BIOS config path generation avoids duplicate `RetroBat` segments.
- **Setup Clients native visibility**: Updated the Setup Clients tab to display native share name and native Windows mapping command alongside the existing virtual SMB details.
- **Native/Clients and Native/Systems architecture**: Added config-time normalization in `app/config.py` so system `local_base_path` and source `base_path` resolve to `Systems/...` without requiring immediate YAML rewrites

### Removed
- **Hardcoded Native virtual directory**: Removed bind-mount of `Native` into `/mnt/transfs` root
  - Now use dedicated SMB shares: `TransFS` (virtual) and `TransFSNative` (native)
- **Redundant SharedBIOS system**: Removed from `app/config/clients/default/retrobat.yaml`
  - Consolidated BIOS file mappings into client-level maps for cleaner configuration

### Fixed
- **TransFS crash on client directories with `maps: null`**: Hardened map iteration across `app/dirlisting.py`, `app/sourcepath.py`, `app/pathutils.py`, and `app/transfs.py` to treat null map collections as empty lists.
  - Fixes Trio/FUSE crash `TypeError: 'NoneType' object is not iterable` during `READDIR` on paths like `/mnt/transfs/Mame`.
  - Prevents unmount/connection-abort behavior when client or system map lists are omitted or explicitly null in config.
- **joeblade.dsk lookup performance**: Fixed 8.8-second silent delay on first access caused by recursive scan of 5,406 files in Software/Sources directory
  - Now resolved with startup pre-warming and longer cache TTL (900s)
  - Pre-builds recursive filename indexes for large directories at startup
- **Shared BIOS zip map rendering**: Fixed zip-mode resolution for category-level mapped files (e.g., `/RetroBat/bios/atom.zip`)
  - Now honors `file.zip_mode: file` configuration
  - Items exposed as regular files instead of virtual directories
- **RetroBat query-map file open pathing**: Fixed category-based map file resolution for query maps (e.g., `/RetroBat/ROMS/AcornAtom/Tapes/*.uef`)
  - Lookups now resolve against configured query `source_dir` with flattened recursive fallback
  - Prevents incorrect fallback paths like `.../Atom/Tapes/...`
- **RetroBat BIOS deep category-path visibility**: Fixed `/RetroBat/bios/mame/ini` directory listing initialization
  - Correctly discovers and exposes deep paths including files like `mame.ini`
  - Previously appeared empty due to initialization issue
- **Windows setup BIOS copy PowerShell syntax error**: Fixed `TrimStart()` method calls in map_win_drive.ps1 and setup_windows.ps1 templates - changed from `TrimStart('\\')` to `TrimStart('\')` to correctly pass a single backslash character instead of an escaped string, resolving "Cannot convert value "\\" to type "System.Char"" error during RetroBat BIOS folder setup
- **Windows setup BIOS copy error handling**: Added comprehensive error handling to `map_win_drive.ps1` Copy-BiosWithProgress function to catch and report individual file copy failures (permissions, locked files, long paths) instead of silently continuing
- **Windows setup BIOS copy verification diagnostics**: Enhanced verification logic to identify and display specific missing files when copy count mismatch occurs, making it easier to diagnose which file failed and why
- **Windows setup native BIOS path**: Setup scripts copy BIOS to `V:\Clients\RetroBat\bios` (matching retrobat.yaml client-level local_base_path) so files appear in virtual mount via client-level query map
  - Updated RetroBat setup PowerShell templates to copy to correct physical location while configuring virtual path
  - Added automatic database synchronization after BIOS copy completion
  - Fixed Mode 3 (dual-drive) config prompt to reference full client path (`V:\Clients\RetroBat\bios`)
- **Windows setup ROM paths migration**: Added optional post-BIOS update flow to migrate all ROM paths in `es_systems.cfg` from relative (`../roms`) to network share paths (`V:\roms`), with backup and rollback support
- **TransFS release crash (KeyError)**: Hardened file-handle teardown in `app/transfs.py` `release()` to handle duplicate/reordered release events and shared inode scenarios without crashing the Trio FUSE loop
- **SMB 0KB mapped file metadata**: Fixed `readdir` fast-path cached stat construction in `app/transfs.py` to use real file sizes from `DirEntry.stat()` instead of reporting non-directory entries as `0` bytes
- **TransFS readdir crash (UnboundLocalError)**: Fixed `app/transfs.py` `readdir` fast-path to avoid `stat` name shadowing (`UnboundLocalError: local variable 'stat' referenced before assignment`) during `readdirplus`
- **SMB auth/guest parity across shares**: Updated SMB config mutation logic so guest/auth settings are consistently applied to both `TransFS` and `TransFSNative` shares
- **Samba FUSE compatibility**: Added delete veto files settings to `smb.conf` for improved FUSE-backed file deletion operations
- **Windows setup write-access validation**: Fixed false-negative write checks on mapped drive root paths
  - Script no longer hard-fails when `V:\` root is non-writable (Mode 3 dual-drive)
  - Now validates and tests write access on actual target path (`<share>\RetroBat\bios`)
  - Changed mapped drive root writability check from hard error to warning
  - Preserved strict validation at BIOS destination path
  - Archived root-level one-off check/cleanup/test scripts used during feature development
  - Archived abandoned Windows helper prototype at `legacy/tools/Tranfs_Retrobat_Config/`
  - Kept runtime/production scripts in place (including `map_win_drive.ps1`)
- **Subdirectory query caching optimization**: Implemented empty-result caching for `_get_subdirectories_from_db()` queries, dramatically improving cascade deletion performance
  - Queries returning 0 subdirectories are now cached for 5 seconds, preventing repeated expensive table scans
  - Eliminates 400-800ms database queries that were repeatedly hitting the same empty directory paths
- **Stable file scan order during database sync**: Added explicit sorting to all `os.walk()` and `os.scandir()` iterations in `sync_database.py` to ensure deterministic file processing order
  - File scan now sorts both directory and file lists alphabetically before processing
  - Eliminates non-deterministic file rename behavior across container restarts
  - Duplicate files are now consistently renamed with predictable `_2`, `_3` suffixes regardless of filesystem scan order
  - Applies to all sync methods: `_scan_system_directory()`, `_scan_directory()`, `_scan_directory_recursive()`, and file counting
- **Database sync error resilience**: Removed problematic database queries during collision detection that were causing "current transaction is aborted" errors
  - Simplified duplicate detection logic to focus on in-memory batch + DB collision detection without additional lookups
  - Improved robustness of sync startup on systems with transaction state issues
  - Performance improvement: **11,000x faster** for cached empty directory checks (1,472ms → 0.2ms)
  - Directly addresses slow deletion operations (previously ~2 items/second) during multi-folder deletes
- **READDIR performance optimization**: Eliminated redundant `get_source_path()` calls in directory listing loop
  - Removed per-entry `get_source_path()` call that was executing 44x for directories with 44 files
  - Reuses cached pipeline information from source_paths dictionary instead of recalculating
  - Falls back to system_transform_map for efficient transform lookups
  - Performance: **3-4x faster** initial directory access (600-900ms → 145-220ms)
  - Performance: **2x faster** subsequent directory access (100ms → 20-60ms)
  - Dramatically improves directory traversal responsiveness in File Explorer and SMB clients

### Fixed
- **Critical deletion slowness**: Fixed 100-200+ second hangs during folder deletion
  - **Root cause**: Duplicate detection query used `regexp_replace(virtual_path, '/[^/]+$', '')` on every row
  - Regex operations cannot use indexes, causing full table scan during deletion cascade
  - **Solution**: Changed to `virtual_path LIKE 'target_dir/%'` which uses existing index
  - **Performance**: Deletion now completes in seconds instead of minutes
- **Setup Clients host fallback and script template resolution**: Fixed two setup onboarding issues for non-local clients
  - Setup profile now avoids loopback-only hostnames and falls back to `AVAHI_HOSTNAME` (default `transfs.local`) when request host is `localhost`
  - `/api/download/setup-windows` now searches multiple runtime-safe template paths, including `/app/setup_windows.ps1.template`
  - Added `app/setup_windows.ps1.template` so the endpoint works correctly with the current `/app` bind mount layout

- **Windows setup credential prompt reliability**: Improved script behavior when `Get-Credential` UI does not appear
  - Added `Get-TransFSCredential` helper with fallback to console-based username/password entry
  - Added clearer guidance when running in non-interactive hosts
  - Replaced special bullet glyphs in credential instructions with ASCII to avoid mojibake in some terminals

- **File-based map path resolution**: Fixed `boot.vhd` and other file-based maps not appearing in FUSE filesystem
  - Extended `get_source_path()` in `app/sourcepath.py` to support modern `file: {path: ...}` configuration format
  - Previously only handled legacy `default_source->source_filename` syntax
  - Now properly handles both regular files and ZIP extraction with `unzip`/`zip_internal_file` options
  - Resolves paths relative to system's `local_base_path` for correct physical file location

- **SMB authenticated access configuration**: Fixed Windows clients denied access when using authenticated mode
  - Added automatic injection of `valid users = root` and `force user = root` directives in `app/smb_config.py`
  - Updated `smb.conf` to explicitly set authentication for TransFS share
  - Removed deprecated `write cache size` parameter from SMB configuration
  - All SMB operations now consistently run as root user to match FUSE mount permissions

- **Docker startup sequence (SMB + FUSE)**: Fixed persistent "Permission denied" when SMB tried to access FUSE mount
  - **Root cause**: SMB daemon was starting BEFORE FUSE filesystem mounted, causing `vfs_ChDir(/mnt/transfs) failed`
  - Modified `docker-compose.yml` entrypoint to mount FUSE first, then wait for mount confirmation before starting SMB
  - Added 30-second mountpoint validation with retry loop (`mountpoint -q /mnt/transfs`)
  - Added error handling that exits container if FUSE fails to mount within timeout
  - New startup order: Configure SMB → Start FUSE → Wait for mount → Start SMB services → Start web service

- **FUSE access callback for SMB chdir**: Fixed SMB mapping that authenticated but failed on drive access with "Access is denied"
  - **Root cause**: FUSE `access()` callback returned `None` instead of explicit allow, causing execute/chdir checks to fail for `/mnt/transfs`
  - Updated `app/transfs.py` to return explicit success from `access()`
  - Verified in-container behavior: `os.chdir('/mnt/transfs')` and `os.chdir('/mnt/transfs/MiSTer')` now succeed
  - This directly resolves Samba `vfs_ChDir(/mnt/transfs) failed: Permission denied` during tree connect

- **Windows setup script writability false-negative**: Fixed BIOS folder probe incorrectly reporting "not writable"
  - **Root cause**: writability test created hidden temp files (`.transfs_write_test_*.tmp`) while TransFS intentionally hides dotfiles
  - Updated writability probes to use non-hidden temp filenames (`transfs_write_test_*.tmp`)
  - Applied to both setup script templates and `map_win_drive.ps1`
  - This allows valid writable TransFS folders (e.g., `V:\RetroBat\bios`) to pass script validation

- **Directory listing filesystem fallback for write-through visibility**: Fixed writability tests failing when written files didn't appear in directory listings
  - **Root cause**: Query map directories fetched entries ONLY from database; FUSE-written files weren't synced yet, so appeared invisible immediately after write
  - Windows writability tests: create temp file → list directory → verify file exists → test fails if file invisible
  - Added filesystem fallback to `_get_subdirectories_from_db()` in `app/dirlisting.py` - merges disk files not in database
  - Added filesystem merge to `list_query_map()` - supplements database results with files from disk
  - Added filesystem fallback to FUSE `readdir` in `app/transfs.py` for database-backed query maps
  - **Result**: Files written via SMB/FUSE now appear immediately in listings → writability detection now works correctly

- **Windows setup mapping scope choice**: Added explicit mapping mode selection for non-standard SMB port setups
  - Script now prompts for `current user` (no admin) vs `all users` (admin required)
  - Stores `MappingScope` in registry defaults for future runs
  - Shows clear admin guidance when all-users mapping is selected without elevation

- **Windows setup write-access validation**: Fixed false-negative write checks on mapped drive root paths
  - Script no longer hard-fails when `V:\` root is non-writable
  - Now validates and tests write access on actual target path (`<share>\RetroBat\bios`)

- **Windows setup Explorer refresh option**: Added optional Explorer restart after successful drive mapping
  - Script now prompts to restart Explorer so newly mapped drives appear immediately in File Explorer
  - Restart can now be queued and executed only after script completion to avoid closing setup windows launched from Explorer
  - Uses detached PowerShell process control (`Stop-Process explorer` / `Start-Process explorer.exe`) with safe error handling
  - Improved error message when target directory cannot be created

- **Query Map Directory Access for Virtual Paths**: Fixed intermittent "No such file or directory" error for query map directories
  - Query maps like ROMs, Tapes, FDs are purely database-driven with no physical filesystem backing
  - Previously, when `get_source_path()` returned a non-existent physical path, `getattr()` would fall through to "unhandled case" error
  - Added fallback logic in `getattr()` to detect query map directories with non-existent physical paths
  - Returns virtual directory attributes (mode 0o040755) for these directories instead of raising ENOENT
  - Ensures consistent access across category-based clients (RetroBat with ROMS/BIOS categories) and non-category clients (MiSTer)
  - Verified all three maps (FDs, ROMs, Tapes) consistently accessible with 123+ ROM files

- **SMB Authenticated Access**: Fixed "Access is denied" error when connecting to SMB share with authentication
  - Added `valid users = root` and `force user = root` directives to SMB TransFS share configuration  
  - Dynamic configuration now automatically adds these when guest access is disabled
  - Removed deprecated `write cache size` parameter causing Samba warnings
  - SMB authenticated connections now work correctly from Windows clients
  
- **MAME Nested ZIP Download**: Fixed MAME downloader to handle Internet Archive's nested ZIP structure
  - Updated download logic to download `{softwarelist}/{software}.zip` nested ZIP files
  - Extracts individual ROM files from within the downloaded ZIP
  - Properly URL-encodes nested paths (e.g., `atom_cass%2F747.zip`)
  - Fixed `download_file()` method signature to accept both SoftwareEntry and ROMFile
  - Added `softwarelist_name` field to SoftwareEntry dataclass
  - Updated hash parser to extract software list name from XML root element
  - Verified checksum validation works correctly with extracted files
  - Resolves "404 Not Found" errors during MAME pack installation
  
- **MAME Source Configuration**: Fixed incorrect filter and archive URL configuration
  - Changed `exclude_unsupported` from `true` to `false` in Atom.yaml
  - The "supported" attribute in MAME hash files refers to emulation status in MAME, not file availability
  - All Atom software was being filtered out because entries are marked `supported="no"` 
  - Files should still be downloadable even when marked as unsupported in MAME
  
- **Pack Installation System Name Matching**: Fixed system name resolution in pack installation
  - Both client-based and client-agnostic pack installation endpoints now correctly match systems by actual name AND mapping name
  - Resolves "System not found" errors when using mapping names like "Atom" instead of actual names like "AcornAtom"
  - Enables proper pack installation for all system name variations
  
- **MAME Source Pack Installation**: Fixed pack installation to properly handle type:mame sources
  - MAME sources are now correctly processed before URL normalization
  - Eliminated spurious "no URL(s) configured" warnings for MAME sources
  - Pack installation now properly detects and handles media_types and filters for MAME sources
  - Downloads are performed using MAMEDownloadManager for checksummed verification
  - Improved error handling with specific exception types (Timeout, ConnectionError, HTTPError)
  - Added warning message when no entries are found (likely network issue)

### Added
- **Client-Level File Maps**: New feature enabling file maps at the client directory level
  - File maps can now be defined at client level in addition to system level
  - Example: `/mnt/transfs/RetroBat/bios/atom.zip` for shared BIOS files across all systems
  - Supports nested map structure (e.g., `bios/atom.zip` appears as `/RetroBat/bios/` directory containing `atom.zip` file)
  - Enables sharing common files (BIOS, ROMs, etc.) across multiple systems within a client
  - Configure using `maps:` section at client level in client YAML files
- **Nested File Maps Within Query Maps**: File maps can now be nested inside query map directories
  - Enables placing static files alongside dynamic query-based content
  - Example: `FDs/bios/atom.zip` creates virtual `bios/` subdirectory within `FDs/` query map containing BIOS file
  - Supports arbitrary nesting depth (e.g., `FDs/bios/lr-mame/atom.zip`)
  - Virtual directories are automatically created for nested map paths
  - Useful for emulators that require BIOS files in specific subdirectories relative to ROM directory
- **MAME Software List Downloader**: Integrated downloader for MAME verified software from Internet Archive
  - Parses official MAME hash XML files from GitHub for metadata
  - Downloads individual files from 70GB MAME collection (no need for full archive download)
  - SHA1 checksum verification ensures file integrity
  - Configurable filters: publisher, year range, support status
  - Integrates as new source type (`type: mame`) in existing sources array
  - RESTful API for programmatic access
  - Hash file caching minimizes GitHub requests
  - Supports all MAME systems with hash files (100+ systems)
  - Documentation: [MAME_DOWNLOADER.md](docs/MAME_DOWNLOADER.md)
- **Query Map Structure Preservation**: New `preserve_structure` option for query maps
  - Set `preserve_structure: true` in map config to preserve source directory structure in virtual filesystem
  - Default: `false` (flattens all files into the map root)
  - Enables organizing files by subdirectory while still using query-based filtering
  - Example: `Software/Sources/hoglet67/AA/GALAXIAN` can appear as `FDs/Sources/hoglet67/AA/GALAXIAN` instead of just `FDs/GALAXIAN`

### Changed
- Renamed the Debug tab to Logs in the web UI for future log expansions.
- System support icons now reflect pack-level `supported_by` metadata when available, ensuring system badges match pack client coverage.
- **Cache Naming & UI Cleanup**: Renamed file attribute caching to **Stat Cache** in UI and API
  - Updated cache configuration endpoints to use `stat_cache_*` keys
  - Dashboard now surfaces Stat Cache and ZIP Index cache stats
  - Removed directory cache indicators and hit-rate cards tied to deprecated pickle caches
  - Removed Cache tab in favor of Config-tab cache controls and inline virtual browser status

### Removed
- **Deprecated Directory Pickle Cache Controls**: Removed config toggles and UI controls for directory listing pickle caches
  - Directory cache has been disabled in code for stability and staleness reasons
  - Cache UI now reflects only active caches (Stat Cache, ZIP Index, Transform caches)

### Fixed
- **Inode Collision for Multi-Client Systems**: Fixed critical bug where multiple clients mapping to the same physical directory would share inodes
  - System directories (level 2, e.g., `/mnt/transfs/MiSTer/AcornAtom`) now use synthetic inodes instead of real filesystem inodes
  - Prevents configuration bleeding between clients (e.g., MiSTer showing RetroBat's file-based maps)
  - Each client now maintains isolated virtual views even when sharing underlying storage
- Restored Test Results tab rendering, including per-test output parsing, run tabs, and progress updates.
- Restored download log carriage return handling so progress updates overwrite the current line instead of spamming new lines.
- Restored Debug tab log loading by fetching FUSE logs from the correct endpoint on tab activation.
- Fixed Debug tab log fetch path to use `/api/logs` (API is mounted under `/api`).
- Restored test progress status rendering to keep the progress bar updated during test runs.
- Pack installation now selects a valid configured client when pack `supported_by` includes clients not present in the current config set.
- Restored Browse Native/Virtual functionality in the web UI (rich file rendering, Zaparoo launch controls, metadata panel, cache status, and deep-link initialization).
- Fixed `preserve_structure` directory browsing to return child entries for nested paths without O(N^2) lookups.
- Fixed `preserve_structure` virtual directory getattr so nested folders resolve correctly in FUSE.
- **Metadata Rulesets Docker Accessibility**: Moved `/config/metadata/rulesets/` to `/app/config/metadata/rulesets/`
  - Ensures ruleset YAML files are accessible inside Docker container
  - Previous location was outside `/app` directory mount point
  - Affects GoodTools, TOSEC, Atarimania, and other metadata parsing rulesets
- **File-Based Map Database Sync**: Extended database sync to properly handle file-based maps (e.g., `boot.vhd`)
  - Fixed `_sync_system()` to process both file-based maps and query maps
  - Added `_sync_file_based_map()` handler for single-file map entries
  - Flush file-based map entries before query map scanning to prevent overwrites
- **File-Based Map Path Resolution**: Fixed sourcepath.py to resolve file-based maps
  - Added support for `file:` configuration format in get_source_path()
  - Handles both regular files and ZIP archives with unzip/zip_internal_file options
  - Ensures file-based maps appear in FUSE directory listings
- **Nested Map Virtual Directory Handling**: Added proper handling for nested maps in path resolution
  - Virtual directories like 'bios' (for 'bios/atom.zip' maps) now correctly identified as virtual
  - Prevents cross-client configuration mixing (e.g., MiSTer files showing in RetroBat when sharing same physical directory)
- **Pack Default Extension for Nested Folders**: Fixed `metadata.defaults.extension` feature for deeply nested folder structures
  - Added per-file pack context lookup in _scan_system_directory() to apply default extensions
  - Fixes RetroBat Acorn Atom: 3,197 extensionless files (in Software/Sources/hoglet67/*/...) now indexed with ATM extension
  - Default extensions applied before query map matching, allowing files to match appropriate maps
  - Source folder path corrected in Atom.yaml from Science Collections to Software/Sources/hoglet67
- **File-Based Map Metadata Enrichment**: Fixed metadata enrichment for file-based maps
  - Modified sync_database.py to commit files before enriching metadata
  - Changed enrichment.py to use commit=True for file_metadata INSERT
  - Resolves foreign key constraint violations during sync
  - Ensures file-based maps have complete metadata available in database and API
  - Added deduplication logic to preserve file-based map assignment when same file appears in multiple maps
  - Updated upsert query to use COALESCE to preserve existing map_name on conflict
  - Ensures files from file-based maps are synced with correct `client`, `system`, and `map_name` columns
- **File-Based Map Path Resolution**: Added support for 'file' config format in get_source_path()
  - Handles file-based maps alongside legacy 'default_source' format
  - Supports ZIP files with unzip and zip_internal_file options
  - Enables boot.vhd and other file-based maps to resolve correctly in FUSE filesystem
  - Fixes missing file-based map entries appearing in system-level directory listings
- **File-Based Map Metadata Enrichment**: Added metadata enrichment during file sync
  - Modified _flush_file_batch() to enrich metadata for synced files
  - Captures file_ids from UPSERT RETURNING clause
  - Calls enrich_file_metadata() for each file after insertion
  - Fixes "no metadata available" message for boot.vhd and other file-based maps in UI

### Added
- **Multi-Config-Set Support**: Switch between different configuration libraries for clients and sources
  - New directory structure: `config/clients/<set_name>/` and `config/sources/<set_name>/`
  - Moved default configs to `config/clients/default/` and `config/sources/default/`
  - Active config sets tracked in app.yaml: `config_sets.active_client_config`, `config_sets.active_source_config`
  - UI in Config tab with dropdowns to switch between config sets (triggers page reload)
  - ZIP import functionality to upload and extract new config sets
  - Backend API endpoints:
    - GET `/api/config/sets` - List available config sets
    - GET `/api/config/sets/active` - Get currently active config sets
    - POST `/api/config/sets/switch` - Switch active config set
    - POST `/api/config/sets/import` - Import ZIP containing new config set
  - Maintains backward compatibility with legacy flat structure
  - Useful for testing configurations, production vs development, or different source collections

- **API Namespace Organization**: All API endpoints now consistently accessible under `/api/` prefix
  - FastAPI app mounted at `/api` in main.py for clean namespace
  - Swagger documentation available at `/api/docs` and `/api/redoc`
  - OpenAPI spec at `/api/openapi.json`
  - All endpoints properly tagged for Swagger organization (Clients & Systems, Downloads, Database, Cache, File Browsing, System)
  - Frontend HTML already calling `/api/*` endpoints for compatibility

### Added (Previous)
- **Modular Client Configuration**: Refactored clients.yaml into per-client files for better maintainability
  - Created `app/config/clients/` directory with individual YAML files: `mister.yaml`, `mame.yaml`, `retrobat.yaml`, `retropie.yaml`, `generic.yaml`
  - Updated `read_clients_config()` to dynamically discover and load all YAML files from clients directory
  - Maintains backward compatibility with legacy `clients.yaml` as fallback
  - Enables parallel contributions and reduces merge conflicts as configs grow
  - MiSTer client: 40+ systems with detailed mappings in dedicated mister.yaml
- **Streaming Sync Progress**: Database sync API now supports Server-Sent Events for real-time progress updates
  - Added `stream=true` parameter to `/api/db/sync` endpoint
  - Streams progress messages for client/system processing, file counts, and completion status
  - Includes heartbeat messages to keep connection alive during long syncs
  - Progress callbacks throughout sync process emit structured JSON events
- **System-Wide File Scanning**: Database sync now scans entire system base paths instead of per-map directories
  - Finds all files under a system's local_base_path (e.g., `/Native/Acorn/Atom/`)
  - Matches files to maps based on extension, regardless of subdirectory location
  - Eliminates issues with files in non-standard locations (e.g., `Software/VHD/` vs `Software/Sources/`)
  - Single scan per system instead of multiple scans per map
- **Batch Processing Performance**: Implemented PostgreSQL bulk upsert for 2.4x sync speedup
  - Added file batching with configurable `BATCH_SIZE` (default 1000 files)
  - Uses `executemany()` with `ON CONFLICT DO UPDATE` for efficient bulk operations
  - Performance improvement: 384s → 158s for ~12,000 files (2.4x faster)
  - Reduced database round-trips from per-file to per-batch

### Changed
- **Sync System Consolidation**: Unified to single DatabaseSync implementation
  - Removed dual-sync architecture (FilesystemSync + DatabaseSync)
  - Updated API `/api/db/sync` endpoint to use DatabaseSync exclusively
  - Updated data_provider_db sync_on_startup to use DatabaseSync
  - Moved deprecated db/sync.py to legacy folder
  - All syncs now properly populate system/client/map_name fields
- **Configuration Performance**: Added LRU cache to read_config() function
  - Eliminated 870ms overhead on every API request
  - API browse requests reduced from 2.8s to <100ms
  - Added reload_config() function to clear cache when needed
- **Metadata Enrichment Race Condition Fix**: Fixed foreign key violations during concurrent sync
  - Changed _ensure_lookup() to use `INSERT ON CONFLICT DO NOTHING` with commit=True
  - Eliminates race conditions when multiple files try to create same lookup entries
- **Default Extension Support**: Pack metadata can now specify `extension` in defaults to assign extensions to files without one
  - Added `default_extension` field to `PackContext` dataclass
  - Modified database sync to apply default extension during file scanning when files lack an extension
  - Updated Acorn Atom pack configuration to use `extension: ATM` in defaults for files without extensions
  - Enables proper handling of archives with extensionless files (e.g., hoglet67 Acorn Atom software archive)

### Fixed
- **Zaparoo Launch Path Normalization**: Added lstrip("/") to path construction
  - Fixes Zaparoo launch failures where paths started with double slash (//)
  - Ensures clean path construction from virtual_path components
- Fixed schema initialization to execute multi-statement SQL safely and continue after idempotent failures
- Improved virtual mappings generation to match systems using normalized client config fields

### Performance
- Database sync: 384s → 158s (2.4x faster) for ~12,000 files
- API latency: 2.8s → <100ms for browse requests
- Database connection pooling: 5-15 concurrent connections
- Batch size: 1000 files per bulk operation

### Migration Notes
- **PostgreSQL Migration (COMPLETE)**
  - Replaced SQLite with PostgreSQL 15-alpine in docker-compose
  - Added persistent postgres_data volume for database persistence
  - Implemented psycopg2-binary connection pooling (5 min, 15 max connections)
  - Converted all database operations to use PostgreSQL %s parameter syntax
  - Updated schema.py for PostgreSQL (SERIAL PRIMARY KEY, BIGINT timestamps, BOOLEAN types)
  - Migrated all SQL queries from ? to %s placeholders across all modules
  - Converted SQLite-specific syntax to PostgreSQL equivalents
  - Fixed RealDictCursor row access (dict keys instead of tuple indices)
  - Eliminated concurrent access locking errors with PostgreSQL MVCC
  - Validated: 20,213 files indexed, 6,641 enriched with metadata

### Added
  - Added info icon next to Zaparoo button with hover tooltip for file metadata
  - Added `/api/file-metadata` endpoint to serve normalized metadata for UI display
- **Source-Based Download Layout**
  - Added source-based download layout option to store files under Software/Sources/<source>
  - Applied MiSTer default download layout to source-based storage
  - Sync, listing, and source-path resolution now support recursive source folders
- **Atarimania Ruleset**
  - Renamed Atari 2600 ruleset to atarimania
  - Linked Atari 2600 pack metadata and client config to the renamed ruleset
- **Filename Parsing Enhancements for Atari 2600**
  - Date/Year bracket detection to derive title prefix and publisher candidate
  - Fallback publisher extraction from remaining tags (excluding Prototype/CX/MT/DA)
  - Added PAL/SECAM region recognition
  - Stored parsed title in file metadata
- **Database-Only Architecture for Query Maps** - Complete end-to-end database-driven file access
  - Query maps (FDs, HDs, etc.) now bypass parse_trans_path entirely
  - Three-tier database-only implementation:
    1. **Readdir**: query_files_by_client_system_and_map() → 76+ files, pagination support
    2. **Getattr**: query_file_by_client_system_map_and_name() → stat structures with mtime/size
    3. **Open**: Direct database lookup → transform pipeline → source file access
  - Validated: 76 FDs files + 420 HDs files successfully listed, stat'd, and read
  - File integrity verified: 143KB test file copied correctly (bit-for-bit match)
  - Performance: Database queries replace expensive parse_trans_path/filesystem traversal

- **Database-Only Readdir for Query Maps** - Query map directories now list files from database without filesystem access
  - Eliminates parse_trans_path overhead for directory listings
  - Direct database queries via query_files_by_client_system_and_map()
  - Proper extension filtering from query.extensions configuration
  - Pagination support for large directories (tested with 76 FD files)
  - Graceful fallback to filesystem mode if database fails
  - Validates query map configuration before attempting database mode

- **Database-Only Getattr for Query Maps** - File attribute queries now use database-only lookups
  - Query single files by client/system/map/filename via query_file_by_client_system_map_and_name()
  - Proper stat structures with size and mtime from database
  - Transform size adjustment for transformed files
  - Significantly faster than filesystem-based stat calls

- **Database-Only Open for Query Maps** - File opens now resolved via database lookups
  - Simplifies source path resolution for files in query maps
  - Applies transform pipelines after database lookup
  - Complete database-driven file access without parse_trans_path overhead
  - Tested: Successfully reading file contents for Apple-II disks

- **Byte-Size Filtering for Source Paths** - New `extension_filters` configuration for per-extension byte-size constraints
  - Configure size limits per file extension (e.g., 2MG files < 865KB go to FDs, ≥ 865KB go to HDs)
  - Filter source paths to separate collections by file size at database query time
  - Useful for separating multi-purpose extensions (e.g., 2MG can be FD or HD image)
  - Configuration: Add `extension_filters: {2MG: {max_size: X, min_size: Y}}` to query map config
  - Applied in both query_files_by_client_system_and_map and query_files_by_system_and_query
  - Validation: Apple-II FDs (2MG ≤ 865KB) = 76 files, HDs (2MG > 865KB) = 210 files correctly separated

- **Normalized Metadata Tables (Initial Implementation)**
  - Added controlled vocab tables (media types, regions, languages, genres, app types, publishers)
  - Added `file_metadata`, `file_tags`, `packs`, `file_packs`, and `metadata_edits` tables

### Fixed
- Fixed PostgreSQL sync cleanup in sync_database.py to return pooled connections cleanly
- Added progress logging during file counting in database sync to show filesystem walk activity - Improved database sync UI responsiveness by adding early initialization logging and output flushing- **Download Log CR Handling**
  - Added carriage-return-aware progress output for DDL and torrent downloads
  - Updated UI log renderer to handle in-place progress updates without line spam
  - Added filename-based metadata enrichment hook during database sync
  - Pack-level metadata defaults now flow into metadata enrichment during sync
  - Added starter ruleset files for GoodTools and TOSEC in config/metadata/rulesets
- **Query Map Database Lookup Alignment**
  - Aligns database query `source_dir` with source-based layout
  - Falls back to system name when manufacturer/system identifiers differ
  - Prevents slow filesystem scans for large ROM directories when database mode is enabled
- **Database Readdir Cache for Query Maps**
  - Caches database-only readdir results to avoid repeated full queries during large listings
  - Reduces listing time for large ROM directories (e.g., Atari 2600 ROMs)
- **Unique Virtual Filenames for Duplicates**
  - Disambiguates virtual filenames when multiple source files would collide
  - Prevents duplicate entries in virtual listings and avoids OS confusion
  - Reuses existing virtual filename when the same source path already exists (update instead of duplicate)
- **Database Sync Performance Optimization**
  - Uses single persistent database connection with batched commits (100 files per batch)
  - Eliminates per-file connection overhead, dramatically improving sync speed
  - Adds file counting and progress reporting every 100 files
  - Progress shown as percentage and file count (e.g., "Progress: 45.2% (3000/6639)")

### Fixed
- **Database Sync Schema Initialization** - Sync now uses centralized schema initialization
  - Ensures v2 metadata tables are created during sync
  - Prevents missing-table errors during metadata enrichment

- **SQLite PRAGMA Compatibility on WSL Mounts** - Disabled WAL mode to avoid disk I/O errors
  - Uses DELETE journal mode for mounted filesystem compatibility

- **Pack Context Folder Matching** - Normalized pack folder paths during sync
  - Supports folders that already include Software/ prefixes
  - Enables pack defaults to match files stored under Software/BIN layouts

- **Atari 2600 Pack Source Folder Alignment** - Source folder now matches on-disk Software/BIN layout
  - Allows pack metadata defaults to resolve against actual file paths

- **Explicit output_extension Configuration for Transformed Files** - Large 2MG files in HDs now appear as .hdv
  - Issue: 2MG files ≥ 908,289 bytes appearing with wrong extension (.do) in HDs directory
  - Root cause: TwoMGTransform auto-detection returning "do" format override explicit "output_extension: hdv" config
  - Solution: Modified TransformPipeline.get_effective_output_extension() to prioritize explicit config over auto-detection
  - Result: Files in HDs map now correctly display as .hdv, FDs files still show as .do/.po based on detection
  - 494 FDs files properly filtered and displayed, 6 HDs files with large 2MG images now in .hdv format

- **Case-Insensitive Extension Transform Lookup** - Fixed transforms not applying when extension case mismatched
  - Issue: Database stored extensions as lowercase (e.g., "2mg") but FUSE code looked up transforms with uppercase keys ("2MG")
  - Solution: Updated all extension lookups in transform map to try both uppercase and lowercase
  - Impacts: READDIR file renaming, getattr size adjustment, all places using system_transform_map
  - Tested: 2MG files correctly transformed regardless of extension case in database

- **Extension-Aware Sample File Selection** - Transform detection now uses appropriate sample files for size-filtered extensions
  - Issue: Building transform pipeline for 2MG files in HDs was finding small floppy samples instead of large drives
  - Solution: When building system transform map, filter sample files by extension_filters to match the map's size constraints
  - Result: HDs map correctly detects hard drive format characteristics using large 2MG file samples

- **System Name Format Normalization** - Fixed FUSE queries failing to find files in database
  - Issue: Database stored system names as "Apple/AppleII" (from source_path extraction) but FUSE queries used "Apple-II" format
  - Root cause: System name mismatch prevented query_files_by_client_system_and_map() from matching database records
  - Solution: Normalized all system names in database to match URL path format (e.g., "Apple-II" instead of "Apple/AppleII")
  - Validation: 4th & Inches 2MG files (819KB) now correctly appear in FDs listing, 500+ disk files restored

- **Database Out-of-Sync Issues After Schema Changes** - Complete database resync and population
  - Issue: After adding client and map_name columns, database required repopulation with correct values
  - Solution: Extracted system names from source_path patterns and populated client='MiSTer' for all 15,984 files
  - Map name assignment: Matched file extensions to virtual directories (/2mg/→2MG, /hdv/→HDs, /dsk/→FDs, etc.)
  - Size-based filtering: Applied 908,288-byte threshold for 2MG files (≤threshold→FDs, ≥threshold→HDs)
  - Result: Database fully synced with 510 files in FDs, 6 files in HDs for Apple-II system

- **Query Map Extension Configuration** - Fixed readdir not finding extensions in query config
  - Issue: Extensions were stored under query.extensions but code looked for top-level extensions
  - Solution: Updated _readdir_database_only to use get_query_config() to access nested extensions

- **2MG Transform Bogus Header Support** - Fixed reading 2MG files with invalid data_offset values
  - Issue: 2MG files with bogus data_offset=819200 (should be 64) only read 69 bytes instead of 819KB
  - Root Cause: Header field pointed beyond actual data, clamping calculation limited reads
  - Solution: Added validation in `_parse_header()` to detect and reject bogus offsets
  - Validation: If data_offset leaves <1KB data remaining, use header_size (64) instead
  - Impact: Also fixes format detection (FD vs HD) which was using bogus offset in calculations
  - Verification: Files now read full 819200 bytes with correct disk data (not "2IMGRVLW" header)

- **2MG Format Detection Threshold** - Updated floppy/hard disk threshold to 800KB
  - Changed from 200KB to 800KB to match Apple IIe 3.5" floppy capacity
  - Files ≤800KB: Classified as floppy (.do/.po based on format byte)
  - Files >800KB: Classified as hard disk (.hdv)
  - Supports both 140KB (5.25") and 800KB (3.5") floppy formats


- **Query Map Listing Performance** - Avoided expensive per-entry resolution in query map directories
  - Issue: Large query map directories (e.g., Apple-II FDs) took several minutes to list
  - Solution: Added fast-path readdir for query maps to emit entries without per-file stat
  - Impact: Listings return immediately; file stats are resolved on demand

- **Data Corruption in Large File Delivery** - REVERTED problematic retry logic in read() function
  - Issue: Previous "fix" for FUSE short reads introduced data corruption
  - Root Cause: Concatenating multiple os.read() calls corrupted the byte stream
  - Solution: Reverted to original simple read() function (single os.lseek + os.read call)
  - Verification: Files now return correct MD5 checksums
    - boot.vhd: b9e3f5e78ccfb5d7523f82f3113445ca ✓ (was corrupted with retry logic)
    - Size: 104.8 MB delivered correctly, no truncation
  - Impact: MiSTer will receive correct file checksums and boot properly
  - Note: FUSE short read issue resolved by kernel/pyfuse3 v3.4.2 - works correctly without retry logic

- **Query Map File Access** - Fixed inability to open files from query map directories
  - Issue: Files listed in query maps (e.g., HDs/) couldn't be opened - returned "file not found"
  - Root Cause: File resolution code didn't query database for actual file locations
  - Solution: Added database lookup in `TransFS.open()` to resolve query map filenames to actual paths
  - Verification: Query maps now list and open files correctly, full reads work with correct checksums
  - Impact: Query map-based views (HDs, FDs, etc.) are now fully functional

- **Query Map Directory Listing (Apple-II)** - Fixed empty FDs/HDs listings despite indexed files
  - Issue: /MiSTer/Apple-II/FDs and /MiSTer/Apple-II/HDs appeared empty even though files existed
  - Root Cause: Query-map resolution was skipped when `...SoftwareArchives...` was absent; readdir sent no entries
  - Solution: Allow query-map resolution without `...SoftwareArchives...` and add a safe fallback listing for query maps
  - Verification: Apple-II FDs/HDs now list correctly with transformed extensions (do/po/hdv)

### Added (Phase 3 Batch Testing - WIP)
- Batch dual-mode verification for target systems via legacy scripts (filesystem vs database counts)
- Helper scripts moved to legacy for non-production use: `fix_systems_batch.py`, `phase3_batch_verify.py`, `phase3_sync_and_cleanup.py`, `phase3_diff_report.py`, `phase3_dualmode_batch.py`

### Changed
- Moved migration-only Python scripts from app/ to legacy/
- Moved migration summaries/guides from repo root to docs/development/
- Enabled query-based mode for all `...SoftwareArchives...` maps via `db_mode: true`
- Passed `db_mode` and optional `extensions` from config into `list_dynamic_map()`
- Replaced `...SoftwareArchives...` with explicit query/file maps in clients.yaml
- Added structured query support for query maps and new schema documentation

### Added (Phase 2 Proof of Concept - BBC_B Real Data Validation - COMPLETE)
- **Phase 2.1-2.8**: BBC_B Pilot Implementation with Real User Data
  - Real-world test system: Acorn BBC_B with 52 actual software files (50 floppy images + 2 hard disk images)
  - Comprehensive Phase 2 documentation: `PHASE_2_BBC_B_COMPLETE.md` with detailed task breakdown and performance metrics
  - Database migration for BBC_B: All 52 files indexed with correct system extraction (Acorn/BBC_B)
  - Dual-mode validation: Verified identical results between YAML-driven (folder_based) and database-driven access
  - Flattening proof-of-concept: Successfully merged SSD/ + MMB/ subfolders into flat layout with rollback verification
  - Performance baseline established: Database queries 3-28ms, file access <16ms with mixed media types
  - Migration scripts created: `migrate_database_phase1.py`, `fix_bbc_b_system.py` for reusable system migrations
  - Comprehensive test suite: 8 test scripts validating assessment, queries, dual-mode, flattening, and performance
  - Backup/restore validation: Software.backup.tar.gz (21M) created and verified for safe round-trip testing

### Added (Phase 1 Foundation - Database-Driven File Organization - COMPLETE)
- **Phase 1.0-1.5**: Database Infrastructure
  - Database schema enhancements: `system` column (e.g., "Apple/AppleII") and `content_type` column for files table
  - System extraction logic: `_extract_system(source_path)` automatically populates system metadata during sync
  - 7 database query helpers in `app/db/queries.py` for system-based file discovery
  - 4 REST API endpoints (`/api/systems`, `/api/systems/{system}/query-mapping`, etc.) for database-driven queries
  
- **Phase 1.6**: Configuration Infrastructure
  - `download_layout` field (folder_based|flat) in SystemConfig for layout preference storage
  - All 25 systems in clients.yaml now configured with `download_layout: folder_based`
  - Configuration fully backward compatible with zero breaking changes
  
- **Phase 1.7**: Dual-Mode Directory Listing
  - `list_dynamic_map()` refactored with `db_mode` parameter for dual-mode operation:
    - YAML-driven mode (default): Folder-based scanning (existing behavior)
    - Database-driven mode (new): Database queries for file discovery
  - Graceful fallback to folder-based mode if database unavailable
  - 100% backward compatible - existing code works unchanged
  
- **Phase 1.8-1.9**: Testing & Validation
  - Comprehensive test suite created: `tests/test_phase1.py` (23 tests)
  - Test results: 12/12 passed, 11 skipped (require database/filesystem)
  - Verified: SystemConfig, configuration loading, dual-mode signature, integration
  
- **Documentation** (10+ pages):
  - [docs/PHASE_1_COMPLETE.md](docs/PHASE_1_COMPLETE.md) - Phase 1 completion summary
  - [docs/PHASE_1_7_COMPLETION.md](docs/PHASE_1_7_COMPLETION.md) - Dual-mode refactoring details
  - [docs/FLAT_LAYOUT_MIGRATION.md](docs/FLAT_LAYOUT_MIGRATION.md) - 4-phase migration plan
  - [docs/DATABASE_DRIVEN_MAPPINGS.md](docs/DATABASE_DRIVEN_MAPPINGS.md) - Technical assessment
  - Additional guides and reference documentation

### Changed
- `list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)` signature updated:
  - Added optional `db_mode: bool = False` parameter
  - Added optional `extensions: list = None` parameter
  - Enhanced docstring with 40-line comprehensive documentation
  
### Technical Details
- Database queries optimized for system + extension combinations
- System metadata extracted from source path: `/Native/{manufacturer}/{system}/...` → `{manufacturer}/{system}`
- All 25 systems configured for layout: Acorn, Apple, Atari, Coleco, Commodore, GCE, Mattel, Microsoft, MITS, NEC, Nintendo, Sega, Sinclair, SNK, Tandy
- Dual-mode supports gradual Phase 2 migration (systems can be flattened one-by-one)
- Complete backward compatibility maintained throughout

### Added
- `/sync/client/{client}/system/{system}` API endpoint for manual system cache population
- Comprehensive logging to track getattr cache hits, database lookups, and transform calculations
- Support for `display_name` field in clients.yaml for custom UI display names independent of filesystem paths
- Real filestore path tooltips in Virtual browse UI - shows actual filestore location when hovering over files
- `/api/source-paths` endpoint for resolving virtual paths to their real filestore locations using clients.yaml mapping rules
- UI configuration option `show_real_path_tooltips` (enabled by default) to toggle path tooltips in Config tab
- Transform plugin system with auto-discovery from `app/transform_plugins`
- Transform plugin documentation index and feature page
- Mapping and filtering documentation: `docs/MAPPING_AND_FILTERING.md`

### Changed
- **PERF**: Getattr cache validation now uses file's own mtime instead of parent directory mtime (prevents false invalidations)
- **PERF**: Readdir batch phase now checks getattr cache FIRST, before source path lookups and transform calculations
- **PERF**: Getattr priority reordered: cache → database → full resolution (prevents unnecessary database lookups)
- Cache warmer now calls `os.stat()` on files to pre-populate transform sizes, not just directory listings
- Disabled persistent PKL dir/getattr caches in favor of in-memory session cache + database to prevent stale listings
- Moved `two_mg` transform into plugin (`app/transform_plugins/two_mg_transform.py`)

### Fixed
- Catastrophic slowdown for systems with file transforms (38-45x speedup for Apple-II: 76s → 2s)
- Cache hits now properly reflected in batch phase instead of only in send phase
- Unbound variable error in readdir cache_hits initialization
- Apple-II DSK image loading - removed incorrect 64-byte header strip transform (only 2MG files need 512-byte strip)

## [2026-02-14] - Display Name System Implementation

### Added
- Optional `display_name` field in clients.yaml configuration
- Display name resolution system in pathutils.py for virtual path mapping
- Web API returns display_name for UI while filesystem operations use actual names
- Fall-back to `name` field when display_name not provided (backward compatible)

### Changed
- Config API endpoint (`/clients/{client}/systems`) now returns display_name for system list
- Virtual path resolution updated to handle both display_name and name lookups

### Technical Details
- `resolve_system_name()` function maps display names back to actual system names
- Display names work across all path resolution functions
- Separate concerns: `name` (filesystem/internal), `display_name` (UI), `canonical_system_name` (config), `local_base_path` (filestore)

## [2026-02-07] - Previous Release

### Features
- Core FUSE filesystem with caching strategies
- Multi-source support (HTTP/HTTPS, MEGA, Torrent, local archives)
- File transformation pipeline (strip_header, zip remapping, etc.)
- Web UI with file browser and download management
- SMB server integration
- Database-backed metadata storage for large collections

---

## Template for Future Entries

When adding new changes, use this format:

```markdown
## [YYYY-MM-DD] - Feature/Fix Description

### Added
- New features

### Changed
- Modifications to existing functionality

### Fixed
- Bug fixes

### Performance
- Performance improvements

### Technical
- Internal changes, refactoring, API changes
```

## Release Strategy

Releases are made from the `dev` branch to `main` when:
- A significant feature is complete and tested
- Multiple bug fixes are accumulated
- Performance improvements are validated
- At minimum: monthly snapshot

Each release should:
1. Update CHANGELOG.md with date and version
2. Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
3. Push tag: `git push origin vX.Y.Z`
4. Update version in relevant files (if applicable)
