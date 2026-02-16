# Virtual File System (VFS) Contents

## Overview
The TransFS virtual file system provides a unified, client-specific view of the filestore. Mappings define how physical files appear in the virtual tree, and transform plugins modify file contents or extensions on the fly.

## Contents
1. Virtual File System overview
   - See [docs/FEATURES.md](FEATURES.md) for the current VFS behavior reference.
2. Mappings
   - Mapping behavior is described under Dynamic ...SoftwareArchives... Maps in [docs/FEATURES.md](FEATURES.md).
3. Transform plugins (subfeature of mappings)
   - See [docs/TRANSFORM_PLUGINS.md](TRANSFORM_PLUGINS.md).

## Hierarchy
- Virtual File System
  - Mappings (client presentation)
    - Transform plugins (per-extension transforms)
