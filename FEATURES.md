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
| Native External Mounts (SMB->Native subpath) | Working | Requires reachable NAS and valid CIFS credentials | Enables persistent lower-level mappings like Native/Systems/.../Software/Sources/Nas-Collection |
| Per-Client Disc Cache (for archived images) | Working | None | Preserves extracted archives (e.g., .7z) per (client, system) pair to eliminate re-extraction on mid-game re-reads (audio streaming, etc.) |
| RetroNAS Artifact Build Profile | Working | Assumes Docker runtime and Linux shell inside container | Optional Compose profile generates RetroNAS-ready installer bundle and tarball under artifacts/retronas |