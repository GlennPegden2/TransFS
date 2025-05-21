#!/usr/bin/env python

import os
from pathlib import Path
import zipfile

import yaml
from fuse import FUSE

from passthroughfs import Passthrough


class TransFS(Passthrough):
    def __init__(self, root_path):
        super().__init__(root_path)  # Call the base class __init__ method
        print("Starting TransFS")
        self.root = root_path
        with open("/app/transfs.yaml", "r", encoding="UTF-8") as f:
            self.config = yaml.safe_load(f)

    def _is_virtual_path(self, full_path):
        if not os.path.isdir(full_path) and not os.path.isfile(full_path) \
                and self._client_exists(Path(full_path).parts[len(Path(self.root).parts)]):
            return True
        return False

    def _client_exists(self, name_to_check):
        return any(client.get("name") == name_to_check for client in self.config.get("clients", []))

    def _parse_trans_path(self, full_path):
        """
        Return directory entries for the given virtual path, using get_source_path for translation.
        Supports dynamic expansion of ...SoftwareArchives... maps, including subfolders and zip logic.
        """
        path = Path(full_path)
        lev = len(path.parts) - len(Path(self.root).parts)
        dirents = []

        # Top level: list clients
        if lev == 0:
            for client in self.config['clients']:
                dirents.append(client['name'])
            return dirents

        # Client level: list systems
        client_name = path.parts[len(Path(self.root).parts)]
        client = next((c for c in self.config['clients'] if c['name'] == client_name), None)
        if not client:
            return dirents

        if lev == 1:
            for system in client['systems']:
                dirents.append(system['name'])
            return dirents

        # System level: list maps and dynamic SoftwareArchives
        system_name = path.parts[len(Path(self.root).parts) + 1]
        system = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system:
            return dirents

        if lev == 2:
            for map_entry in system['maps']:
                map_name = list(map_entry.keys())[0]
                if map_name == "...SoftwareArchives...":
                    filetypes = map_entry[map_name].get("filetypes", [])
                    for filetype in filetypes:
                        for key in filetype.keys():
                            dirents.append(key)
                else:
                    dirents.append(map_name)
            return dirents

        # Dynamic SoftwareArchives subfolders and their contents
        map_name = path.parts[len(Path(self.root).parts) + 2]
        sa_entry = next((m for m in system['maps'] if list(m.keys())[0] == "...SoftwareArchives..."), None)
        if sa_entry:
            filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
            supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
            source_dir = os.path.join(
                self.config["filestore"],
                system["local_base_path"],
                sa_entry["...SoftwareArchives..."]["source_dir"]
            )
            for filetype in filetypes:
                for key, subdirs in filetype.items():
                    if key == map_name:
                        subdir_list = [s.strip() for s in subdirs.split(",")]
                        subpath = path.parts[len(Path(self.root).parts) + 3:]
                        entries = set()
                        for subdir in subdir_list:
                            dir_path = os.path.join(source_dir, subdir, *subpath)
                            if os.path.isdir(dir_path):
                                for entry in os.listdir(dir_path):
                                    entry_path = os.path.join(dir_path, entry)
                                    if entry.lower().endswith('.zip') and not supports_zip:
                                        # Present zip as folder or single file
                                        try:
                                            with zipfile.ZipFile(entry_path, 'r') as zf:
                                                namelist = [n for n in zf.namelist() if not n.endswith('/')]
                                                if len(namelist) == 1:
                                                    # Present the file directly
                                                    entries.add(namelist[0].split('/')[-1])
                                                elif len(namelist) > 1:
                                                    # Present the zip as a directory
                                                    entries.add(entry)
                                        except Exception as e:
                                            # If zip is invalid, just show as file
                                            entries.add(entry)
                                    else:
                                        entries.add(entry)
                            # If the current path is a .zip, list its contents
                            elif os.path.isfile(dir_path) and dir_path.lower().endswith('.zip') and not supports_zip:
                                try:
                                    with zipfile.ZipFile(dir_path, 'r') as zf:
                                        namelist = [n for n in zf.namelist() if not n.endswith('/')]
                                        if len(namelist) == 1:
                                            # Present the file directly
                                            entries.add(namelist[0].split('/')[-1])
                                        else:
                                            for n in namelist:
                                                entries.add(n.split('/')[-1])
                                    return sorted(entries)
                                except Exception as e:
                                    return []
                        return sorted(entries)
        # Regular map subfolders (e.g. xHDs and its subfolders)
        map_entry = next((m for m in system['maps'] if list(m.keys())[0] == map_name), None)
        if map_entry:
            mapdict = map_entry[map_name]
            if "source_dir" in mapdict:
                base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                    system['local_base_path'], mapdict["source_dir"])
                subpath = path.parts[len(Path(self.root).parts) + 3:]
                dir_path = os.path.join(base, *subpath)
                if os.path.isdir(dir_path):
                    return sorted(os.listdir(dir_path))
        return dirents

    def _full_path(self, partial):
        print(f"full path is {partial}")

        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path


    # Public Helpers
    # ==============

    def readdir(self, path, fh):
        full_path = self._full_path(path)

        dirents = ['.', '..']

        dirents.extend(self._parse_trans_path(full_path))

        if os.path.isdir(full_path):
            dirents.extend(os.listdir(full_path))

        for r in dirents:
            yield r

    def getattr(self, path, fh=None):
        full_path = self._full_path(path)

        fspath = self.get_source_path(full_path)
        if fspath is None:
            st = os.lstat(full_path)
        elif isinstance(fspath, tuple):
            # (zip_path, internal_file)
            zip_path, internal_file = fspath
            with zipfile.ZipFile(zip_path, 'r') as zf:
                info = zf.getinfo(internal_file)
                # Simulate a stat result
                class statobj:
                    st_atime = st_mtime = st_ctime = info.date_time and int(os.path.getmtime(zip_path)) or 0
                    st_gid = getattr(os, "getgid", lambda: 0)()
                    st_uid = getattr(os, "getuid", lambda: 0)()
                    st_mode = 0o100444  # regular file, read-only
                    st_nlink = 1
                    st_size = info.file_size
                st = statobj()
        else:
            st = os.lstat(fspath)

        print(f"getattr: {path} -> {full_path} - Mode is {oct(st.st_mode)}")

        return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                                                        'st_gid', 'st_mode', 'st_mtime', 
                                                        'st_nlink', 'st_size', 'st_uid'))

    def open(self, path, flags):
        full_path = self._full_path(path)
        trans_path = self.get_source_path(full_path)
        if trans_path is None:
            return os.open(full_path, flags)
        if isinstance(trans_path, tuple):
            # (zip_path, internal_file)
            zip_path, internal_file = trans_path
            # You will need to implement a file-like object for zip streaming, or extract to temp and open
            # Example: extract to temp and open
            import tempfile
            with zipfile.ZipFile(zip_path, 'r') as zf:
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(zf.read(internal_file))
                temp.close()
                return os.open(temp.name, flags)
        return os.open(trans_path, flags)

    def get_source_path(self, translated_path):
        """
        Given a translated path (as seen under the FUSE mount), return the corresponding
        source path in the filestore, using the translation logic from TransFS.
        Supports dynamic ...SoftwareArchives... mapping, including zip-as-folder logic.
        """
        path = Path(translated_path)
        mountpoint = Path(self.root)
        parts = path.parts
        root_parts = mountpoint.parts
        rel_parts = parts[len(root_parts):]

        if not rel_parts:
            return self.config.get("filestore", "/mnt/filestorefs")

        # Find client
        client_name = rel_parts[0]
        client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
        if not client:
            return None

        if len(rel_parts) == 1:
            return self.config.get("filestore", "/mnt/filestorefs")

        # Parse default_target_path template
        path_str = client['default_target_path']
        path_template_parts = Path(path_str).parts

        # Try to extract system_name
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

        # Find system_info
        system_info = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system_info:
            return None

        # Handle ...SoftwareArchives... dynamic folders with zip logic
        if "...SoftwareArchives..." in [list(m.keys())[0] for m in system_info['maps']]:
            if len(rel_parts) >= 3:
                map_name = rel_parts[2]
                sa_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == "...SoftwareArchives..."), None)
                if sa_entry:
                    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
                    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
                    source_dir = os.path.join(
                        self.config["filestore"],
                        system_info["local_base_path"],
                        sa_entry["...SoftwareArchives..."]["source_dir"]
                    )
                    for filetype in filetypes:
                        for key, subdirs in filetype.items():
                            if key == map_name:
                                subdir_list = [s.strip() for s in subdirs.split(",")]
                                subpath = rel_parts[3:]
                                # If supports_zip is False, handle zip-as-folder logic
                                if not supports_zip and subpath:
                                    zip_candidate = subpath[0]
                                    for subdir in subdir_list:
                                        zip_path = os.path.join(source_dir, subdir, zip_candidate)
                                        if os.path.isfile(zip_path) and zip_candidate.lower().endswith('.zip'):
                                            with zipfile.ZipFile(zip_path, 'r') as zf:
                                                namelist = [n for n in zf.namelist() if not n.endswith('/')]
                                                if len(namelist) == 1:
                                                    # If accessing the file inside the zip
                                                    if len(subpath) > 1 and subpath[1] == namelist[0].split('/')[-1]:
                                                        return (zip_path, namelist[0])
                                                    # If accessing the zip as a folder, return zip path
                                                    return zip_path
                                                else:
                                                    # If accessing a file inside the zip
                                                    if len(subpath) > 1:
                                                        for n in namelist:
                                                            if subpath[1] == n.split('/')[-1]:
                                                                return (zip_path, n)
                                                    # If accessing the zip as a folder, return zip path
                                                    return zip_path
                                # Standard logic: join subpath to each mapped subdir
                                for subdir in subdir_list:
                                    candidate = os.path.join(source_dir, subdir, *subpath)
                                    if os.path.exists(candidate):
                                        return candidate
                                    # If not a real file, check all zip files in the same directory
                                    parent_dir = os.path.join(source_dir, subdir, *subpath[:-1])
                                    if os.path.isdir(parent_dir):
                                        for entry in os.listdir(parent_dir):
                                            if entry.lower().endswith('.zip'):
                                                zip_path = os.path.join(parent_dir, entry)
                                                with zipfile.ZipFile(zip_path, 'r') as zf:
                                                    for n in zf.namelist():
                                                        if n.split('/')[-1] == subpath[-1]:
                                                            return (zip_path, n)
        # Handle normal maps (unchanged)
        if len(rel_parts) >= 3:
            map_name = rel_parts[2]
            map_entry = next((m for m in system_info['maps'] if list(m.keys())[0] == map_name), None)
            if map_entry:
                mapdict = map_entry[map_name]
                if "source_dir" in mapdict:
                    base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                        system_info['local_base_path'], mapdict["source_dir"])
                    subpath = rel_parts[3:]
                    return os.path.join(base, *subpath) if subpath else base
                elif "source_filename" in mapdict:
                    base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                        system_info['local_base_path'], mapdict["source_filename"])
                    subpath = rel_parts[3:]
                    return os.path.join(base, *subpath) if subpath else base
                elif "default_source" in mapdict:
                    ds = mapdict["default_source"]
                    if "source_dir" in ds:
                        base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                            system_info['local_base_path'], ds["source_dir"])
                        subpath = rel_parts[3:]
                        return os.path.join(base, *subpath) if subpath else base
                    elif "source_filename" in ds:
                        base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                            system_info['local_base_path'], ds["source_filename"])
                        subpath = rel_parts[3:]
                        return os.path.join(base, *subpath) if subpath else base
        # Fallback: just join filestore, local_base_path, and the rest
        base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                            system_info['local_base_path'])
        subpath = rel_parts[len(path_template_parts):]
        return os.path.join(base, *subpath) if subpath else base


def main(mount_path, root_path):
#    FUSE(TransFS(root_path=root_path), mount_path, nothreads=True,
#         foreground=True, **{'allow_other': True})
    FUSE(TransFS(root_path=root_path), mount_path, nothreads=True,
         foreground=True, debug=True, encoding='utf-8' , **{'allow_other': True})


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
