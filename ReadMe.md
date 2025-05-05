# TransFS  
*A Virtual Translation Filesystem for Archive-Based Content*

**TransFS** is a FUSE-based virtual filesystem that presents structured, emulator-friendly views of software archives (e.g., ROMs, BIOS, software packs) without modifying their original format. By dynamically mapping archive.org content into the file layouts required by various emulation platforms, TransFS eliminates the need for local file extraction, renaming, or repackaging.

---

## 🔍 Key Features

- **FUSE-powered virtual filesystem** – Present data download from archive.org in the format expected by various apps (e.g. emulators).
- **Zero modification** – Original archive content remains untouched; translations occur in-memory.
- **Smart naming & structure** – Automatically adapts files/folders to the conventions of target emulators/platforms.
- **ROMset and BIOS handling** – Merge split ROMs, unzip on-demand, or reshape sets for compatibility.
- **Dockerised deployment** – Fully containerised SMB server for network-based sharing with retro devices and VMs.
- **Extensible plugin system** – Support additional emulators, platforms, or structural conventions.

---

## 📦 Use Cases

- Retro emulation environments (e.g. RetroArch, MAME, MiSTer)
- Software preservation setups
- Testing environments requiring specific file layout conventions
- Dynamic presentation of large archive.org datasets via Samba/SMB

---

## 🚀 Getting Started

### Requirements

- Linux (FUSE support)
- Docker (if using containerised mode)
- Python 3.9+ (for non-containerised dev mode)
- `fuse3` / `libfuse` installed

### Quick Start (Dockerised SMB Mode)

```bash
git clone https://github.com/your-org/transfs.git
cd transfs
docker-compose up -d
```

### Project Name

This name TransFS was chosen because it translates between one expected dir structure and another
It has nothing specifically to do with the Trans community
However, I am an ardant supporter of Trans Rights, and if that bothers you, any license to use this
software, implied or explict, is revoked in any way I reasonable can.
Also, FUCK YOU! Trans Rights are Human Rights.

If however, it doesn't bother you and you find this software useful, please donate whatever you can
to a Trans charity such as https://mermaidsuk.org.uk/