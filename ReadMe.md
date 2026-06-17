# TransFS  
*A Virtual Translation Filesystem and Downloader for Archive-Based Content. Making multi-emulator retro gaming easier and tidier*

* NOTE: THIS IS A MINIMAL PRE-ALPHA PROOF OF CONCEPT, NOT A PRODUCTION READY SOLUTION *

**TransFS** is a FUSE-based virtual filesystem that presents structured, emulator-friendly views of software archives (e.g., ROMs, BIOS, software packs) avoiding modifying their original format or keeping multiple copies of the same content. By dynamically mapping content into the file layouts required by various emulation platforms, TransFS aims to eliminate the need for local file extraction, renaming, repackaging and maintaining the same content in multiple formats.

It also comes with a handy downloader to obtain the content and place it in a format the virtual layer understands.

Whilst the aim is to make it as simple and easy for new users to obtain and use content for multiple emulators, it is massively configurable to be flexible when it comes to both the file structure on the host machine and expected format by emulators and where to get the software from.

---

## Key Features

- **FUSE-powered virtual filesystem** – Display your content to emulators in the paths/formats it expects. Accessible as an SMB share with a folder per supported emulator
- **Web Based Content Downloader** - Helps you pull the right files from the right places with minimal effort
- **Dockerised deployment** – Fully containerised SMB server for network-based sharing with retro devices and VMs. Minimal config needed (as long as you have docker installed). Can be run bare-metal if needed though.
- **Highly configurable** - Emulators support, systems supported, content sources are modifiable through config. The end game is the config will become something the community can maintain.
- **Designed to work straight out of the box** - As long as you have docker installed and your emulators support SMB shares on non-standard ports (linux based normally does, windows support is patchy) then it should be ready to go!
---



## Getting Started

### Requirements

#### Containerised

Docker 
 
 #### Natively
- Linux (for FUSE support)
- Python 3.9+ to 3.10 (for non-containerised dev mode) - Inc venv and pip. (3.10+ won't work with the Mega library used)
- `fuse3` / `libfuse` 
- Samba
- uvicorn
- tar
- unzip
- guestfish
- libguestfs-tools
- 7zip-full
- unrar-free

### Quick Start (Dockerised SMB Mode)

```bash
git clone https://github.com/GlennPegden2/TransFS.git
cd transfs
docker-compose up -d
```

Then point your web browser to localhost (or wherever your docker host is) port 8080. e.g. http://localhost:8080 and you should get a web UI.

**Next steps:**
1. Browse the web UI to download content for your systems
2. Access your content via SMB at `\\<servername>@3445\<system>` (e.g. `\\localhost@3445\mister`)
3. Configure your emulator to use the SMB share

### Two Access Paths: Virtual vs Direct Native

TransFS provides **two complementary access patterns** in a single SMB share:

```
\\server\TransFS\
  ├── Generic/              (Virtual hierarchies)
  ├── Mame/                 (with transforms, filtering)
  ├── MiSTer/               
  ├── RetroBat/
  ├── RetroPie/
  └── Native/               ← Direct filesystem (bulk operations)
      ├── Clients/          (Client-specific assets, e.g. RetroBat BIOS)
      │   └── RetroBat/
      │       └── bios/
      └── Systems/          (Shared system content)
          ├── Acorn/
          └── Amstrad/
```

**Native is a discoverable top-level folder** that bypasses the FUSE virtual layer:

| Path | Use | Performance |
|------|-----|-------------|
| `\\server\TransFS\Generic\`, `\\server\TransFS\Mame\` etc. | Normal browsing, virtual transforms | Metadata-cached |
| `\\server\TransFS\Native\Systems\...` | **Bulk import/delete, direct filesystem** | **6-15ms per file** |

**For bulk operations** (importing 1000+ files or deleting large directories), use the `Native\` path for dramatically faster performance.

📖 **See [Native Bypass Architecture](docs/NATIVE_BYPASS_ARCHITECTURE.md) and [Quick Start Guide](docs/NATIVE_BYPASS_QUICK_START.md) for details.**

###  Notes on SMB Port Configuration

> **Default Port:** TransFS runs on port **3445** (not standard 445) to avoid conflicts with Windows.
>
> **Compatibility:**
> - ✅ **Linux**: Fully supported (`\\server@3445\share` or `mount -t cifs -o port=3445`)
> - ⚠️ **Windows**: Limited support (requires Windows Insider builds - [details](https://techcommunity.microsoft.com/blog/filecab/smb-alternative-ports-now-supported-in-windows-insider/3974509))
> - ❌ **macOS**: Generally not supported
>
> **To use standard port 445:**
> - Requires non-Windows host (Linux VM, bare metal)
> - Edit `docker-compose.yml` to change port mapping
> - Simplifies client configuration but may conflict with Windows SMB service


---

## Configuration

TransFS is designed to work out of the box with minimal configuration.

**Web UI/API Port:** Configured in `app/transfs.yaml` (default: 8000). For Docker, update port mapping in `docker-compose.yml`.

**Advanced Configuration:** System definitions, pack sources, and build scripts are in `app/config/`. See the [config documentation](app/config/) for details.


---

## Testing

TransFS includes validation and regression testing. Tests must be run inside the Docker container to access the FUSE mount.

**Quick validation** (~1 second):
```powershell
.\validate_docker.ps1
```

**Full regression tests** (slower, snapshot-based):
```powershell
.\run_tests_in_docker.ps1
```

For detailed testing documentation, see [tests/TESTING_GUIDE.md](tests/TESTING_GUIDE.md).

---

## System Compatibility

For the full system compatibility table including supported formats and emulator platforms, see [COMPATIBILITY.md](COMPATIBILITY.md).

**Currently tested systems:** Acorn Archimedes, Acorn Atom, Acorn BBC Micro, Acorn Electron, Amstrad PCW, Amstrad CPC

---

## What's Next?

Once you have TransFS running:

1. **Explore the web UI** - Download and manage content for your systems
2. **Configure your emulator** - Point it to the SMB share for your platform (e.g. `\\localhost@3445\mister`)
3. **Add more systems** - Edit configurations in `app/config/systems/` to add support
4. **Contribute** - Help expand system support and content sources

**Need help?** Check the [Testing Guide](tests/TESTING_GUIDE.md) to validate your setup.

---

### Project Name

This name TransFS was chosen because it translates between one expected dir structure and another
It has nothing specifically to do with the Trans community
However, I am an ardent supporter of Trans Rights, and if that bothers you, any license to use this
software, implied or explicit, is revoked in any way I reasonably can.
Also, FUCK YOU! Trans Rights are Human Rights.

If however, it doesn't bother you and you find this software useful, please donate whatever you can
to a Trans charity such as https://mermaidsuk.org.uk/