# FEATURES.md

## TransFS: Feature & Behavior Reference

### 1. Virtual Filesystem Structure

- The FUSE mount presents a virtual filesystem at `/mnt/transfs`.
- Structure:
  ```
  /mnt/transfs/<client>/<system>/<map>/<subfolders/files>
  ```
  - `<client>`: As defined in YAML (`name` field).
  - `<system>`: As defined in YAML (`name` field under `systems`).
  - `<map>`: Either a static map name or a dynamic map (e.g. `...SoftwareArchives...` creates virtual folders like `ROM`, `Tape`, etc).

---

### 2. Dynamic ...SoftwareArchives... Maps

- **Virtual folders** (e.g. `ROM`, `Tape`) are created based on the `filetypes` mapping in YAML.
- Each virtual folder can map to one or more real file extensions, and can also remap extensions (e.g. `BIN:ROM` means `.BIN` files appear as `.ROM`).
- **Subfolders** under these virtual folders are mapped to real subfolders under the corresponding extension directory.

---

### 3. File and Folder Listing

- **Directories**: All real subdirectories under the mapped real extension directory are shown as virtual subdirectories.
- **Files**: All files with the mapped real extension are shown, with their extension replaced by the virtual extension if needed.
- **Zip files**:
  - If a zip contains only one relevant file, the file is shown directly in the virtual folder (flattened).
  - If a zip contains multiple relevant files, the zip is shown as a virtual folder. Entering this folder lists the files inside the zip.
- **Hidden files** (starting with `.`) are not shown.

---

### 4. File Access

- **Opening/Stat-ing a virtual file**:
  - If the file is a real file, it is opened directly.
  - If the file is inside a zip, it is extracted to a temp file and opened.
- **Opening/Stat-ing a virtual directory**:
  - If the directory exists in any mapped real extension directory, it is treated as a real directory.
  - Otherwise, a fake stat is returned to allow navigation.

---

### 5. Extension Mapping

- If a `filetypes` entry is `BIN:ROM`, then:
  - All `.BIN` files are shown as `.ROM` in the virtual folder.
  - Opening `TEST.ROM` will open the real file `TEST.BIN`.
- If a `filetypes` entry is just `UEF`, then `.UEF` files are shown as `.UEF`.

---

### 6. Zip Handling

- **Flattening**: If a zip contains only one relevant file, the file appears directly in the virtual folder.
- **Zip as folder**: If a zip contains multiple relevant files, the zip appears as a folder. Entering it lists the files inside.
- **Opening files in zips**: When a virtual file corresponds to a file inside a zip, it is extracted to a temp file for access.

---

### 7. Fallbacks

- If a virtual directory or file does not exist in the real filesystem, a fake stat is returned for directories (to allow navigation), and file access fails as expected for files.

---

### 8. Examples

- `/mnt/transfs/MiSTer/AcornElectron/Tape/Apps/` lists all subfolders and `.UEF` files (real or inside zips) in `/mnt/filestorefs/Native/Acorn/Electron/Software/UEF/Apps/`.
- `/mnt/transfs/MiSTer/AcornElectron/ROM/TEST.ROM` could be backed by `ROM/TEST.ROM`, `BIN/TEST.BIN`, or `HEX/TEST.HEX` in the real filesystem, depending on mapping.

---

### 9. Known Limitations

- Only single-level extension mapping is supported (e.g. `BIN:ROM`).
- Only files with mapped extensions are shown in virtual folders.
- Only zip files in mapped extension directories are handled as described.

---