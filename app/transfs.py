#!/usr/bin/env python

import os
import tempfile
import time
from pathlib import Path
import zipfile
from typing import Any, Optional, Tuple, Literal
import yaml
from fuse import FUSE
from passthroughfs import Passthrough
import errno
from fuse import FuseOSError



class TransFS(Passthrough):
    """FUSE filesystem for translating virtual paths to real files, including zip logic and filetype mapping."""

    def __init__(self, root_path: str):
        super().__init__(root_path)
        print("Starting TransFS")
        self.root = root_path
        with open("transfs.yaml", "r", encoding="UTF-8") as f:
            self.config = yaml.safe_load(f)

    # --- Filetype mapping helpers ---

    def _parse_filetype_map(self, filetypes_entry):
        """
        Parse a filetypes entry like {'ROM': 'ROM, BIN:ROM, HEX:ROM'}
        Returns a dict: {virtual_ext: [real_exts]}
        and a reverse map: {real_ext: virtual_ext}
        """
        mapping = {}
        reverse = {}
        for virtual_folder, exts in filetypes_entry.items():
            mapping.setdefault(virtual_folder.upper(), [])
            for ext in exts.split(','):
                ext = ext.strip()
                if ':' in ext:
                    real_ext, virt_ext = ext.split(':', 1)
                    mapping.setdefault(virt_ext.upper(), []).append(real_ext.upper())
                    reverse[real_ext.upper()] = virt_ext.upper()
                else:
                    mapping[virtual_folder.upper()].append(ext.upper())
                    # Do NOT add to reverse here!
        return mapping, reverse

    def _get_filetype_maps(self, sa_entry):
        """
        Build filetype mapping and reverse mapping for a ...SoftwareArchives... entry.
        Returns: {virtual_folder: [real_exts]}, {real_ext: virtual_ext}
        """
        filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
        mapping = {}
        reverse = {}
        for filetype in filetypes:
            for virtual_folder, exts in filetype.items():
                m, r = self._parse_filetype_map({virtual_folder: exts})
                for k, v in m.items():
                    mapping.setdefault(k, []).extend(v)
                reverse.update(r)
        return mapping, reverse

    def _virtual_to_real_candidates(self, virtual_folder, filename, filetype_map):
        """
        Given a virtual folder (e.g. 'ROM') and filename (e.g. 'TEST.ROM'),
        return a list of possible real file paths.
        """
        name, _ = os.path.splitext(filename)
        real_exts = filetype_map.get(virtual_folder.upper(), [])
        return [f"{name}.{real_ext.lower()}" for real_ext in real_exts]

    def _real_to_virtual_name(self, real_name, real_ext, virtual_ext):
        """
        Given a real filename and its extension, return the virtual filename with the virtual extension.
        """
        name, _ = os.path.splitext(real_name)
        return f"{name}.{virtual_ext.lower()}"

    # --- End filetype mapping helpers ---

    def _is_virtual_path(self, full_path: str) -> bool:
        """Check if a path is a virtual (not real) path."""
        parts = Path(full_path).parts
        if not os.path.isdir(full_path) and not os.path.isfile(full_path):
            if self._client_exists(parts[len(Path(self.root).parts)]):
                return True
        return False

    def _client_exists(self, name_to_check: str) -> bool:
        """Check if a client exists in the config."""
        return any(client.get("name") == name_to_check for client in self.config.get("clients", []))

    def _full_path(self, partial: str) -> str:
        """Convert a FUSE path to a full path in the filestore."""
        if partial.startswith("/"):
            partial = partial[1:]
        return os.path.join(self.root, partial)

    def _get_system_info(self, client: dict, rel_parts: list, path_template_parts: tuple) -> Optional[dict]:
        """Extract system info from the config."""
        system_name = None
        if "{system_name}" in path_template_parts:
            idx = path_template_parts.index("{system_name}")
            if len(rel_parts) > idx:
                system_name = rel_parts[idx]
        else:
            for sys in client['systems']:
                if sys['name'] in rel_parts:
                    system_name = sys['name']
                    break
        return next((s for s in client['systems'] if s['name'] == system_name), None)

    def _find_software_archive_entry(self, system_info: dict) -> Optional[dict]:
        """Find the ...SoftwareArchives... entry in a system's maps."""
        return next((m for m in system_info['maps'] if list(m.keys())[0] == "...SoftwareArchives..."), None)

    def _list_zip_file(self, zip_path: str) -> list:
        """Return a list of files (not directories) in a zip archive."""
        with zipfile.ZipFile(zip_path, 'r') as zf:
            return [n for n in zf.namelist() if not n.endswith('/')]


    def _find_file_in_zips(self, parent_dir: str, filename: str) -> Optional[Tuple[str, str]]:
        """Search all zip files in a directory for a file with the given name."""
        for entry in os.listdir(parent_dir):
            if entry.lower().endswith('.zip'):
                zip_path = os.path.join(parent_dir, entry)
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for name in zf.namelist():
                        if name.split('/')[-1] == filename:
                            return zip_path, name
        return None

    def _parse_trans_path(self, full_path: str) -> list:
        """
        Return directory entries for the given virtual path, using get_source_path for translation.
        Supports dynamic expansion of ...SoftwareArchives... maps, including subfolders and zip logic.
        """
        path = Path(full_path)
        root_parts = Path(self.root).parts
        lev = len(path.parts) - len(root_parts)

        if lev == 0:
            return self._list_clients()
        if lev == 1:
            return self._list_systems(path, root_parts)
        if lev == 2:
            return self._list_maps(path, root_parts)
        return self._list_dynamic_or_regular(path, root_parts)

    def _list_clients(self) -> list:
        """List all clients."""
        return [client['name'] for client in self.config['clients']]

    def _list_systems(self, path: Path, root_parts: tuple) -> list:
        """List all systems for a client."""
        client_name = path.parts[len(root_parts)]
        client = next((c for c in self.config['clients'] if c['name'] == client_name), None)
        if not client:
            return []
        return [system['name'] for system in client['systems']]

    def _list_maps(self, path: Path, root_parts: tuple) -> list:
        """List all maps and dynamic SoftwareArchives for a system."""
        client_name = path.parts[len(root_parts)]
        client = next((c for c in self.config['clients'] if c['name'] == client_name), None)
        if not client:
            return []
        system_name = path.parts[len(root_parts) + 1]
        system = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system:
            return []
        maps = []
        for map_entry in system['maps']:
            map_name = list(map_entry.keys())[0]
            if map_name == "...SoftwareArchives...":
                filetypes = map_entry[map_name].get("filetypes", [])
                for filetype in filetypes:
                    maps.extend(filetype.keys())
            else:
                maps.append(map_name)
        return maps

    def _list_dynamic_or_regular(self, path: Path, root_parts: tuple) -> list:
        """List dynamic SoftwareArchives subfolders and their contents, or regular map subfolders."""
        client_name = path.parts[len(root_parts)]
        client = next((c for c in self.config['clients'] if c['name'] == client_name), None)
        if not client:
            return []
        system_name = path.parts[len(root_parts) + 1]
        system = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system:
            return []
        map_name = path.parts[len(root_parts) + 2]
        sa_entry = self._find_software_archive_entry(system)
        if sa_entry and self._is_dynamic_map(map_name, sa_entry):
            return self._list_dynamic_map(path, root_parts, system, sa_entry, map_name)
        return self._list_regular_map(path, root_parts, system, map_name)

    def _is_dynamic_map(self, map_name: str, sa_entry: dict) -> bool:
        """Check if the map is a dynamic ...SoftwareArchives... map."""
        filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
        for filetype in filetypes:
            if map_name in filetype:
                return True
        return False

    def _list_dynamic_map(
        self, path: Path, root_parts: tuple, system: dict, sa_entry: dict, map_name: str
    ) -> list:
        """
        List files and directories for a dynamic ...SoftwareArchives... map,
        handling extension mapping and zip flattening.
        """
        filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
        supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
        source_dir = os.path.join(
            self.config["filestore"],
            "Native",
            system["local_base_path"],
            sa_entry["...SoftwareArchives..."]["source_dir"]
        )
        filetype_map, reverse_map = self._get_filetype_maps(sa_entry)
        real_exts = filetype_map.get(map_name.upper(), [])
        subpath = path.parts[len(root_parts) + 3:]
        entries = set()
        for real_ext in real_exts:
            dir_path = os.path.join(source_dir, real_ext, *subpath)
            if os.path.isdir(dir_path):
                for entry in os.listdir(dir_path):
                    if entry.startswith('.'):
                        continue
                    entry_path = os.path.join(dir_path, entry)
                    # Handle directories
                    if os.path.isdir(entry_path):
                        entries.add(entry)
                    # Handle zip files
                    elif entry.lower().endswith('.zip'):
                        try:
                            namelist = self._list_zip_file(entry_path)
                            # Only files with the correct extension (case-insensitive)
                            filtered = [
                                n for n in namelist
                                if n.upper().endswith(f".{real_ext.upper()}")
                            ]
                            if len(filtered) == 1:
                                # Flatten: show the file directly in this folder
                                zname = filtered[0]
                                name, ext = os.path.splitext(os.path.basename(zname))
                                virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                                entries.add(f"{name}.{virt_ext.lower()}")
                            elif len(filtered) > 1:
                                # Show the zip as a folder
                                entries.add(entry)
                        except Exception:
                            # If zip is bad, just show as a file
                            entries.add(entry)
                    else:
                        # Regular file: check extension case-insensitively
                        name, ext = os.path.splitext(entry)
                        if ext[1:].upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
        return sorted(entries)

    def _list_dir_with_zip(self, dir_path: str, supports_zip: bool) -> set:
        """List directory contents, handling zip-as-folder logic if needed."""
        entries = set()
        if os.path.isdir(dir_path):
            for entry in os.listdir(dir_path):
                entry_path = os.path.join(dir_path, entry)
                if (
                    entry.lower().endswith('.zip')
                    and not supports_zip
                ):
                    try:
                        namelist = self._list_zip_file(entry_path)
                        if len(namelist) == 1:
                            entries.add(namelist[0].split('/')[-1])
                        elif len(namelist) > 1:
                            entries.add(entry)
                    except zipfile.BadZipFile:
                        entries.add(entry)
                else:
                    entries.add(entry)
        elif (
            os.path.isfile(dir_path)
            and dir_path.lower().endswith('.zip')
            and not supports_zip
        ):
            try:
                namelist = self._list_zip_file(dir_path)
                if len(namelist) == 1:
                    entries.add(namelist[0].split('/')[-1])
                else:
                    for name in namelist:
                        entries.add(name.split('/')[-1])
            except zipfile.BadZipFile:
                pass
        return entries

    def _list_regular_map(self, path: Path, root_parts: tuple, system: dict, map_name: str) -> list:
        """List contents of a regular map subfolder."""
        map_entry = next((m for m in system['maps'] if list(m.keys())[0] == map_name), None)
        if not map_entry:
            return []
        mapdict = map_entry[map_name]
        if "source_dir" in mapdict:
            base = os.path.join(
                self.config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system['local_base_path'],
                mapdict["source_dir"]
            )
            subpath = path.parts[len(root_parts) + 3:]
            dir_path = os.path.join(base, *subpath)
            if os.path.isdir(dir_path):
                return sorted(os.listdir(dir_path))
        return []

    def get_source_path(self, translated_path: str) -> Optional[Any]:
        """
        Given a translated path (as seen under the FUSE mount), return the corresponding
        source path in the filestore, using the translation logic from TransFS.
        Supports dynamic ...SoftwareArchives... mapping, including zip-as-folder logic and filetype mapping.
        """
        path = Path(translated_path)
        root_parts = Path(self.root).parts
        rel_parts = path.parts[len(root_parts):]

        if not rel_parts:
            return self.config.get("filestore", "/mnt/filestorefs")

        client = self._get_client(rel_parts)
        if not client:
            return None

        if len(rel_parts) == 1:
            return self.config.get("filestore", "/mnt/filestorefs")

        path_template_parts = Path(client['default_target_path']).parts
        system_info = self._get_system_info(
            client, list(rel_parts), path_template_parts
        )
        if not system_info:
            return None

        # Try dynamic SoftwareArchives first
        dynamic_result = self._get_dynamic_source_path(system_info, rel_parts)
        if dynamic_result is not None:
            return dynamic_result

        # Try regular map logic
        regular_result = self._get_regular_source_path(system_info, rel_parts)
        if regular_result is not None:
            return regular_result

        # Fallback: just join filestore, local_base_path, and the rest
        base = os.path.join(
            self.config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system_info['local_base_path']
        )
        subpath = rel_parts[len(path_template_parts):]
        return os.path.join(base, *subpath) if subpath else base

    def _get_client(self, rel_parts: tuple) -> Optional[dict]:
        """Return the client dict for the given rel_parts."""
        client_name = rel_parts[0]
        return next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)

    def _get_dynamic_source_path(self, system_info: dict, rel_parts: tuple) -> Optional[Any]:
        """Handle ...SoftwareArchives... dynamic folders with zip logic and filetype mapping."""
        if "...SoftwareArchives..." not in [list(m.keys())[0] for m in system_info['maps']]:
            return None
        if len(rel_parts) < 4:
            return None

        map_name = rel_parts[2]
        sa_entry = self._find_software_archive_entry(system_info)
        if not sa_entry:
            return None

        filetype_map, reverse_map = self._get_filetype_maps(sa_entry)
        real_exts = filetype_map.get(map_name.upper(), [])
        supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
        source_dir = os.path.join(
            self.config["filestore"],
            "Native",
            system_info["local_base_path"],
            sa_entry["...SoftwareArchives..."]["source_dir"]
        )
        subpath = rel_parts[3:]
        if not subpath:
            return None

        # If the last component has no extension, treat as a virtual directory
        last = subpath[-1]
        if '.' not in last:
            # Check if any real directory exists for this virtual directory
            for real_ext in real_exts:
                dir_path = os.path.join(source_dir, real_ext, *subpath)
                if os.path.isdir(dir_path):
                    return dir_path  # This allows getattr/readdir to work
            # If no real dir, treat as virtual dir (return None, getattr will fake stat)
            return None

        # Otherwise, treat as file
        filename = subpath[-1]
        name, virt_ext = os.path.splitext(filename)
        virt_ext = virt_ext[1:].upper()
        for real_ext in real_exts:
            real_filename = f"{name}.{real_ext.lower()}"
            real_path = os.path.join(source_dir, real_ext, *subpath[:-1], real_filename)
            if os.path.exists(real_path):
                return real_path
            # Check for file in zip files in the real_ext directory
            parent_dir = os.path.join(source_dir, real_ext, *subpath[:-1])
            if os.path.isdir(parent_dir):
                for entry in os.listdir(parent_dir):
                    if entry.lower().endswith('.zip'):
                        zip_path = os.path.join(parent_dir, entry)
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            for zname in zf.namelist():
                                if zname.split('/')[-1] == real_filename:
                                    return (zip_path, zname)
        return None

    def _get_regular_source_path(self, system_info: dict, rel_parts: tuple) -> Optional[Any]:
        """Handle regular map logic."""
        if len(rel_parts) < 3:
            return None
        map_name = rel_parts[2]
        map_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == map_name), None)
        if not map_entry:
            return None
        mapdict = map_entry[map_name]
        subpath = rel_parts[3:]
        if "source_dir" in mapdict:
            base = os.path.join(
                self.config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                mapdict["source_dir"]
            )
            return os.path.join(base, *subpath) if subpath else base
        if "source_filename" in mapdict:
            base = os.path.join(
                self.config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                mapdict["source_filename"]
            )
            return os.path.join(base, *subpath) if subpath else base
        if "default_source" in mapdict:
            ds = mapdict["default_source"]
            if "source_dir" in ds:
                base = os.path.join(
                self.config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system_info['local_base_path'],
                    ds["source_dir"]
                )
                return os.path.join(base, *subpath) if subpath else base
            if "source_filename" in ds:
                base = os.path.join(
                    self.config.get("filestore", "/mnt/filestorefs"),
                    "Native",
                    system_info['local_base_path'],
                    ds["source_filename"]
                )
                return os.path.join(base, *subpath) if subpath else base
        return None

    def readdir(self, path: str, fh: int):
        """FUSE readdir implementation."""
        full_path = self._full_path(path)
        dirents = ['.', '..']
        dirents.extend(self._parse_trans_path(full_path))
        if os.path.isdir(full_path):
            dirents.extend(os.listdir(full_path))
        for entry in dirents:
            yield entry


    def getattr(
        self,
        path: str,
        fh: Optional[int] = None
    ) -> dict[
        Literal[
            'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
            'st_nlink', 'st_size', 'st_uid'
        ],
        int
    ]:
        """FUSE getattr implementation."""
        full_path = self._full_path(path)
        fspath = self.get_source_path(full_path)

        if fspath is None:
            # If this is a known virtual directory, return a fake stat for a directory
            if self._is_virtual_path(full_path):
                now = int(time.time())
                return {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o040755,  # directory
                    'st_nlink': 2,
                    'st_size': 4096,
                }
            # Otherwise, fallback to real stat (will raise FileNotFoundError if missing)
            st = os.lstat(full_path)
            keys = (
                'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
                'st_nlink', 'st_size', 'st_uid'
            )
            return {key: int(getattr(st, key)) for key in keys}

        if isinstance(fspath, tuple):
            # (zip_path, internal_file)
            zip_path, internal_file = fspath
            with zipfile.ZipFile(zip_path, 'r') as zf:
                info = zf.getinfo(internal_file)
                class StatObj:
                    st_atime = st_mtime = st_ctime = int(os.path.getmtime(zip_path))
                    st_gid = 0
                    st_uid = 0
                    st_mode = 0o100444  # regular file, read-only
                    st_nlink = 1
                    st_size = info.file_size
                st = StatObj()
            mode = 0o100444
        else:
            st = os.lstat(fspath)
            # Use the real file type, but force permissions to 755 for dirs, 644 for files
            if os.path.isdir(fspath):
                mode = 0o040755
            elif os.path.isfile(fspath):
                mode = 0o100644
            else:
                raise FuseOSError(errno.ENOENT)

        keys = (
            'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
            'st_nlink', 'st_size', 'st_uid'
        )
        out = {key: int(getattr(st, key)) for key in keys}
        out['st_mode'] = mode
        return out

    def open(self, path: str, flags: int) -> int:
        """FUSE open implementation."""
        full_path = self._full_path(path)
        trans_path = self.get_source_path(full_path)
        if trans_path is None:
            return os.open(full_path, flags)
        if isinstance(trans_path, tuple):
            zip_path, internal_file = trans_path
            with zipfile.ZipFile(zip_path, 'r') as zf:
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(zf.read(internal_file))
                temp.close()
                return os.open(temp.name, flags)
        return os.open(trans_path, flags)

    def _is_system_root(self, path):
        # e.g. /MiSTer/ARCHIE or /MiSTer/AcornAtom
        parts = path.strip("/").split("/")
        return len(parts) == 2  # ["MiSTer", "ARCHIE"]

    def _map_virtual_to_real(self, path):
        # Only allow writes in /MiSTer/<system>
        if not self._is_system_root(path):
            return None
        # Map to real storage, e.g. /mnt/filestorefs/Native/Acorn/Archimedes
        # You may need to look this up from your YAML config
        # Example:
        client, system = path.strip("/").split("/")
        # Lookup real path from config here...
        # For demo, just join filestore root:
        return os.path.join("/mnt/filestorefs", client, system)

    def create(self, path, mode, fi=None):
        real_dir = self._map_virtual_to_real(os.path.dirname(path))
        real_path = os.path.join(real_dir, os.path.basename(path))
        if os.path.isdir(real_path):
            raise FuseOSError(errno.EISDIR)
        os.makedirs(real_dir, exist_ok=True)
        return os.open(real_path, os.O_WRONLY | os.O_CREAT, mode)

    def mkdir(self, path, mode):
        real_dir = self._map_virtual_to_real(path)
        if real_dir is None:
            raise FuseOSError(errno.EROFS)
        os.makedirs(real_dir, mode=mode, exist_ok=True)
        return 0

    def access(self, path, mode):
        """
        FUSE access implementation.
        Always allow access to virtual directories and files that exist in the virtual namespace.
        """
        full_path = self._full_path(path)
        fspath = self.get_source_path(full_path)

        # If it's a virtual directory, allow access
        if fspath is None and self._is_virtual_path(full_path):
            return 0

        # If it's a real file or directory, check access using os.access
        if fspath and os.path.exists(fspath):
            if os.access(fspath, mode):
                return 0
            else:
                raise FuseOSError(errno.EACCES)

        # If not found, deny access
        raise FuseOSError(errno.ENOENT)


def main(mount_path: str, root_path: str):
    """Mount the FUSE filesystem."""
    FUSE(
        TransFS(root_path=root_path),
        mount_path,
        nothreads=True,
        foreground=True,
        debug=True,
        encoding='utf-8',
        allow_other=True
    )


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
