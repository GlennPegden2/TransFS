# System Compatibility

This table tracks the progress and completeness of features

| Feature       | Status             | Problems | Planned Subfeatures | Notes |
|---------------|--------------------|----------|------|----------|
| Translating FS        | Working                | Config is fickle and likes to beale    | 
| Downloaders           | Working
| Web UI                | Mostly working
| Metadata Handler      | Partly working
| Web File Browser      | Working
| Client Setup          | Working
| Testing System        | Broken
| Config System         | Mostly Working | | 
| Native External Mounts (/mnt/filestore aggregate) | Working | Runtime mount availability depends on network path/auth and mount type | Supports CIFS, NFS, and local bind mounts; exposes configured external sources under /mnt/filestore for direct non-FUSE access; Browse Native now surfaces live mount metadata plus failed configured mount diagnostics for bridge-backed folders |
| Per-Client Disc Cache (for archived images) | Working | None | Preserves extracted archives (e.g., .7z) per (client, system) pair to eliminate re-extraction on mid-game re-reads (audio streaming, etc.) |
| RetroNAS Artifact Build Profile | Working | Assumes Docker runtime and Linux shell inside container | Optional Compose profile generates RetroNAS-ready installer bundle and tarball under artifacts/retronas |