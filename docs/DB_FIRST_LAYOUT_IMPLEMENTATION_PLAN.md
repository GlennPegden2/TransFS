# DB-First Layout-Agnostic Mapping Plan (Pre-Alpha)

## Purpose

This document defines the implementation plan for moving TransFS query-map behavior from path-anchored assumptions to a database-first model that can support arbitrary native filestore layouts after scan/index.

This plan is intended to be durable across sessions and should be treated as the canonical project context for this feature stream.

## Scope Decision

The project is pre-alpha, and there are no existing installs to preserve.

Design decision for this plan:
- We will not preserve legacy query-map path assumptions.
- We will preserve explicit file-path maps (file maps) as path-based behavior.

In short:
- Query maps -> DB-first, layout-agnostic.
- File maps -> explicit path maps, unchanged by default.

## Problem Statement

Current query-map behavior still relies heavily on local_base_path + source_dir assumptions at runtime and during sync assignment.

This prevents fully layout-agnostic operation even though the database already stores authoritative source_path per indexed file.

## Current-State Findings (Code Reality)

### What already exists

- Database stores canonical physical path:
  - files.source_path is unique.
  - files.system and system indexes already exist.
- Query-map DB querying exists:
  - query_files_by_system_and_query is already in place.
  - list_query_map already uses DB-first logic in many paths.
- Runtime DB adapters exist for readdir/getattr/open.

### What still blocks layout-agnostic behavior

- Sync assignment for query maps is still rooted under per-system base path and source_dir prefix checks.
- Source resolution still reconstructs many paths from local_base_path and source_dir.
- Preserve-structure relative path extraction is still string-based around source_dir anchors.
- Category-level and fallback flows still contain source_dir rooted assumptions.

## Target Architecture

### Core principle

For query maps, virtual routing is based on DB-indexed file facts and query rules, not on where files sit under a single configured base subtree.

### Routing model

For each query map, we evaluate a DB predicate over indexed files, then project resulting files into that map's virtual namespace.

Conceptually:

1. Candidate set:
   - files where system matches map system identity
   - plus optional metadata/tag/pack predicates
2. Optional file-type and size filters:
   - extensions, extension_filters, transform_zip rules
3. Optional map-specific folder anchors:
   - if query specifies source_dir or equivalent anchor, it becomes a filter, not a hard requirement
4. Virtual projection:
   - map-level name normalization, extension_map, transforms
   - preserve_structure path generation from DB metadata/path decomposition, not source_dir string slicing

### Explicit non-goals

- Replacing file maps with DB-based inference.
- Removing map categories or category_paths.
- Changing Native bypass behavior.

## Required Data/Schema Enhancements

No major schema rewrite is required to start.

Recommended enhancements for reliability and performance:

1. Query-map assignment table (recommended):
   - file_query_maps(file_id, client, system, map_name, relative_path, created_at, updated_at)
   - Purpose: deterministic lookup and fast virtual projection without recomputing map membership every read.

2. Optional derived path columns (if needed):
   - source_dir_rel or path_tokens cache for faster preserve_structure logic.

3. Index checks:
   - ensure files(system, extension), files(source_path), files(client, system, map_name) paths are performant for new predicates.

## Config Model Changes

### Query maps

Add/standardize DB-first query-map semantics:

- query.mode: db (default for query maps)
- query.source_dir: optional filter anchor (no longer required)
- query.preserve_structure: supported in DB-first mode
- query.transform_zip, query.zip_mode: preserved

### File maps

No behavioral change:
- Continue resolving from explicit configured path.

### Validation changes

Config validation should fail only when:
- file maps have invalid/empty explicit path.
- query maps have invalid query structure.

It should not fail query maps for missing local_base_path/source_dir in DB-first mode.

## Phased Implementation Plan

## Phase 0: Feature Branch Setup and Guardrails

Objectives:
- Establish isolated feature stream and test harness.
- Add feature flag for controlled adoption while iterating.

Tasks:
1. Add app-level feature flag:
   - database.query_maps_db_first = true (default true for this pre-alpha track)
2. Add logging marker for DB-first query-map path selection.
3. Add smoke tests for current map types before changes (baseline snapshots).

Exit criteria:
- Baseline tests pass.
- DB-first flag is wired and observable in logs.

## Phase 1: Query-Map Runtime Resolution (Read Path)

Objectives:
- Make query-map read flows (readdir/getattr/open) DB-first and layout-agnostic.

Tasks:
1. Refactor query-map listing path:
   - remove hard dependency on local_base_path/source_dir for membership.
   - treat source_dir as optional narrowing filter when present.
2. Refactor query-map source resolution:
   - for query-map files, resolve virtual path to source_path via DB mapping first.
   - keep explicit file map logic unchanged.
3. Preserve zip and transform behavior:
   - keep flatten/hierarchical/file semantics stable.
   - keep extension_map and transform output extension behavior stable.
4. Preserve_structure rewrite:
   - replace source_dir string slicing with DB-backed relative path derivation.

Exit criteria:
- Query-map browsing works with files indexed outside legacy source_dir subtree.
- get/open succeed from DB-derived source paths.
- Existing explicit file maps continue to resolve.

## Phase 2: Sync Assignment Rework (Write/Index Path)

Objectives:
- Decouple query-map membership assignment from path-prefix assumptions.

Tasks:
1. Replace prefix-only assignment logic with query evaluation assignment:
   - evaluate each query map against indexed files for system.
2. Populate deterministic map membership table (recommended).
3. Keep file-map ingestion path unchanged.
4. Ensure duplicate handling remains deterministic across multiple matching maps.

Exit criteria:
- Sync can classify files into query maps regardless of underlying folder layout.
- No regressions in map precedence and duplicate behavior.

## Phase 3: Category and Shared-BIOS Compatibility Hardening

Objectives:
- Keep category_paths, shared_bios, and mixed map roots stable under DB-first behavior.

Tasks:
1. Category-root directory generation from map assignments (not filesystem shape assumptions).
2. Shared BIOS map visibility under client roots validated.
3. Mixed file+query map root listings validated.

Exit criteria:
- Category path navigation remains correct across clients.
- Shared bios and mixed map roots show expected entries.

## Phase 4: Performance and Index Tuning

Objectives:
- Ensure DB-first operations remain performant for large libraries.

Tasks:
1. Add/verify indexes for dominant query predicates.
2. Add query-plan logging for slow map listings.
3. Tune short-lived cache layers for readdir/getattr bursts.

Exit criteria:
- Large-map browsing latency is acceptable.
- No pathological slow queries in logs under expected workloads.

## Phase 5: Cleanup and Consolidation

Objectives:
- Remove obsolete legacy query-map path assumptions.

Tasks:
1. Remove dead fallback paths that reconstruct query-map source paths from legacy assumptions.
2. Simplify code paths to single DB-first query-map model.
3. Update docs and inline comments to new model.

Exit criteria:
- Query-map code paths are coherent and minimal.
- No hidden legacy coupling remains for query maps.

## Impact Analysis by Feature Area

1. Query-map directory listing
- High impact, positive.
- Primary area being redesigned.

2. File open/getattr resolution
- Medium-high impact.
- Must preserve transform + archive behavior.

3. Explicit file maps
- Low impact expected.
- Must remain path-based and stable.

4. Shared BIOS and category paths
- Medium risk.
- Requires explicit regression tests.

5. Metadata attach/apply
- Low-medium impact.
- Depends on consistent file_id/source_path lookups; expected to improve consistency.

## Regression Risk Matrix

1. Wrong map membership after sync
- Severity: High
- Mitigation: deterministic membership table + map precedence tests

2. Missing entries in category roots
- Severity: High
- Mitigation: category-root integration tests for each client archetype

3. Archive/zip flatten mismatch
- Severity: High
- Mitigation: dedicated archive-mode tests per zip_mode

4. Preserve_structure wrong relative paths
- Severity: Medium
- Mitigation: path-decomposition tests for nested sources

5. Performance regression on large libraries
- Severity: Medium
- Mitigation: query-plan checks + index tuning + cache tuning

## Test Strategy

### Unit tests

1. Query predicate evaluation for map assignment
2. Preserve_structure path derivation from source_path
3. Extension_map + transform extension projection
4. Shared bios/category route composition

### Integration tests

1. Mixed map roots: file maps + query maps
2. Client category paths (RetroBat/MiSTer/RomM archetypes)
3. Archive modes: file/hierarchical/flatten
4. get/open for DB-only query-map entries

### Snapshot tests

Lock snapshots for representative routes:
1. Client root
2. Category root
3. System root
4. Query map root
5. Query map nested path

### Performance checks

1. Readdir hot-path latency under repeated emulator probing
2. Query latency for large systems
3. Sync classification throughput

## Proposed Delivery Order (Practical)

1. Phase 1 runtime read path
2. Phase 2 sync assignment
3. Phase 3 category/shared-bios hardening
4. Phase 4 performance
5. Phase 5 cleanup

Reasoning:
- Fastest path to proving layout-agnostic value is runtime DB-first read behavior.
- Sync/membership can then be hardened to make behavior deterministic and fast.

## Session Continuity Notes

If a future session resumes this feature, start by doing only this:

1. Read this document.
2. Confirm current branch status against Phase 0-5 checklist.
3. Continue from the first incomplete phase.

Do not redo full feasibility analysis unless architecture constraints have changed.

## Phase Checklist

- [ ] Phase 0 complete
- [ ] Phase 1 complete
- [ ] Phase 2 complete
- [ ] Phase 3 complete
- [ ] Phase 4 complete
- [ ] Phase 5 complete

## Implementation Log

### 2026-06-17 - Phase 1 (first runtime slice)

Completed in this slice:
- `app/vfs/dirlisting.py`
   - Query-map listing now treats `query.source_dir` as optional (no implicit `Software` anchor).
   - DB query payload includes `source_dir` only when configured.
   - Filesystem fallback/merge logic is gated to explicit `source_dir` usage.
   - Subpath handling now supports DB-backed filtering for preserve-structure flows.
   - `_extract_relative_path(...)` now supports `source_dir=None` and can derive relative path from `/Native/{local_base_path}/` anchor.
- `app/transfs.py`
   - DB-only query payload construction now includes `source_dir` only when configured.
   - `getattr`/`open` source-path reconstruction no longer assumes implicit `Software` when `source_dir` is absent.
- `app/tests/test_db_first_query_paths.py`
   - Added focused helper tests for relative path extraction with and without `source_dir`.
   - Local run result: `3 passed`.

### 2026-06-17 - Phase 1 (second runtime slice)

Completed in this slice:
- `app/transfs.py`
   - Added `_query_record_virtual_name(...)` and `_query_record_relative_dir(...)` helper functions to centralize DB-record-to-virtual matching logic.
   - Refactored `_getattr_database_only(...)` query-map resolution to match against DB candidate sets (and map-root cache entries) instead of reconstructing candidate source paths from config path assumptions.
   - Refactored `_open_database_only(...)` with the same DB candidate-set matching strategy so open-path resolution follows the same source_dir-optional semantics as getattr.
- `app/tests/test_db_first_query_paths.py`
   - Added archive-marker path extraction contract coverage for source_dir-omitted helper behavior.
   - Local run result: `4 passed`.

Validation notes:
- Focused helper tests passed on host with `PYTHONPATH=app`.
- Broader host-side regression run (`tests/test_phase1.py -k query_mapping_endpoint`) failed at collection due to missing `psycopg2` in host environment; this path should be re-validated in-container where integration deps are present.

### 2026-06-17 - Phase 2 (initial sync-assignment slice)

Completed in this slice:
- `app/sync_database.py`
   - Query-map sync assignment no longer defaults `query.source_dir` to `Software`.
   - `source_dir` is now resolved and applied only when explicitly configured, making query-map assignment layout-agnostic by default.
   - Map-assignment scanning now treats `source_dir` as an optional narrowing filter rather than a hard requirement.
   - Preserve-structure relative-dir derivation now works for source_dir-omitted query maps (system-base-relative fallback).
- `app/vfs/pathutils.py`
   - Added `derive_query_map_relative_dir(...)` helper for consistent preserve-structure relative directory derivation across source_dir-anchored and source_dir-omitted flows.
- `app/tests/test_db_first_query_paths.py`
   - Added focused tests for `derive_query_map_relative_dir(...)` anchor and no-anchor behavior.
   - Local run result: `7 passed`.

Validation notes:
- Focused helper-path suite passed locally (`app/tests/test_db_first_query_paths.py`).
- Containerized integration validation is still required for end-to-end sync behavior.

Next immediate tasks:
1. Add integration-focused tests for sync assignment behavior when query maps omit `source_dir`.
2. Re-run query-map and sync integration coverage in containerized test environment (with `psycopg2` available).
3. Continue Phase 2 by hardening deterministic multi-map precedence/duplicate behavior under DB-first assignment.

## Decision Log

1. Pre-alpha simplifies migration strategy.
- Decision: no legacy query-map compatibility layer required.

2. Explicit path mappings remain intentional.
- Decision: file maps remain path-based.

3. Query maps become DB-first by design.
- Decision: source_dir is optional filter, not required anchor.

## Open Technical Questions

1. Should map membership be materialized (table) immediately, or computed on read first and materialized in Phase 2?
2. What precedence rule should apply when one file matches multiple query maps in same system?
3. Should preserve_structure paths normalize case from source_path or preserve native case exactly?
4. Should DB-first query mode become the only mode for query maps after Phase 5?

## Acceptance Criteria for Feature Completion

1. A system with files indexed in arbitrary folder layout can be surfaced correctly via query maps without requiring local_base_path/source_dir alignment.
2. Explicit file maps continue to function unchanged.
3. Category/shared-bios paths remain correct.
4. Archive and transform semantics remain functionally equivalent.
5. Tests and snapshots pass for representative clients and systems.
