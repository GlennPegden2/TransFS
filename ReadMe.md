# TransFS  
*A Virtual Translation Filesystem for Archive-Based Content*

**TransFS** is a FUSE-based virtual filesystem that presents structured, emulator-friendly views of software archives (e.g., ROMs, BIOS, software packs) without modifying their original format. By dynamically mapping archive.org content into the file layouts required by various emulation platforms, TransFS eliminates the need for local file extraction, renaming, or repackaging.

---

## 🔍 Key Features

- **FUSE-powered virtual filesystem** – Present data download from archive.org in the format expected by various apps (e.g. emulators).
- **On copy of the contents** – Original archive content remains untouched; translations occur in-memory.
- **Smart naming & structure** – Automatically adapts files/folders to the conventions of target emulators/platforms.
- **ROMset and BIOS handling** – Merge split ROMs, unzip on-demand, or reshape sets for compatibility. (Planned)
- **Dockerised deployment** – Fully containerised SMB server for network-based sharing with retro devices and VMs.

---

## 📦 Use Cases

- Retro emulation environments (e.g. RetroArch, MAME, MiSTer)
- Software preservation setups
- Testing environments requiring specific file layout conventions
- Dynamic presentation of large archive.org datasets via Samba/SMB

---

## 🚀 Getting Started

### Requirements

 #### Conatiner-ised

 Docker on linux (see below why a windows host isn't likely to work)

 #### Natively
- Linux (for FUSE support)
- Python 3.9+ to 3.10 (for non-containerised dev mode) - Inc venv and pip. (3.10+ won't work with the Mega library used)
- `fuse3` / `libfuse` 
- Samba
- uvicorn
- tar
- unzip
- guestfish
- 7zip-full

### Quick Start (Dockerised SMB Mode)

```bash
git clone https://github.com/your-org/transfs.git
cd transfs
docker-compose up -d
```

### Notes on Windows (either running locally or as Host OS for containers)

If windows binds SMB to 443 (as it will want to), we can't bind too, so the SMB server can't run (and SMB doesn't play nicely with many clients when run on other ports). This stops SMB sharing working either natively, under Windows Hosted Docker or under WSL. A linux VM under a hypervisor (i.e. a VM) fine. It also won't run natively in windows as FUSE isn't available. Just run it under linux.

# System Compatibility Table

| System             | MiSTer | Mame | RetroPie | RetroBat | Notes |
|--------------------|--------|------|----------|----------|-------|
| Acorn Archimedes |    ✅ ADF, HDF    |      |          |          |  See https://github.com/MiSTer-devel/Archie_MiSTer for info on how to attach disk images. CROS4 errors a few times on first open but does work     |
| Acorn Atom         | ✅ VHD    |      |          |          | Shift F10 Lauch the StarDot collection      |
| Acorn BBC Micro  |        |      |          |          |       |
| Acorn Electron     | ✅ VHD, MMB , UEF    |      |          |          |       |
| Amstrad PCW        | ✅ DSK     |      |          |          |       |
| Amstrad CPC        | ✅ DSK  |      |          |          |       |
| Apple II            |        |      |          |          |       |
| Atari 2600          |        |      |          |          |       |
| Atari 5200          |        |      |          |          |       |
| Atari 7800          |        |      |          |          |       |
| Atari 800           |        |      |          |          |       |
| Atari Lynx         |        |      |          |          |       |
| ColecoVision       |        |      |          |          |       |
| Commoder Amiga              |        |      |          |          |       |
| Commodore 128       |        |      |          |          |       |
| Commodore 64        |        |      |          |          |       |
| Commodore PET       |        |      |          |          |       |
| Commodore Plus4     |        |      |          |          |       |
| Vectrex            |        |      |          |          |       |
| Intellivision      |        |      |          |          |       |
| MSX                |        |      |          |          |       |
| Altair 8800         |        |      |          |          |       |
| PC-Engine          |        |      |          |          |       |
| TurboGrafx 16       |        |      |          |          |       |
| GameBoy            |        |      |          |          |       |
| GameBoy Advance     |        |      |          |          |       |
| GameBoy Color       |        |      |          |          |       |
| NES                |        |      |          |          |       |
| SNES               |        |      |          |          |       |
| SegaGameGear       |        |      |          |          |       |
| SegaGenesis        |        |      |          |          |       |
| SegaMasterSystem   |        |      |          |          |       |
| ZX Spectrum        |        |      |          |          |       |
| NeoGeo             |        |      |          |          |       |
| AliceMC10          |        |      |          |          |       |

### Project Name

This name TransFS was chosen because it translates between one expected dir structure and another
It has nothing specifically to do with the Trans community
However, I am an ardant supporter of Trans Rights, and if that bothers you, any license to use this
software, implied or explict, is revoked in any way I reasonable can.
Also, FUCK YOU! Trans Rights are Human Rights.

If however, it doesn't bother you and you find this software useful, please donate whatever you can
to a Trans charity such as https://mermaidsuk.org.uk/