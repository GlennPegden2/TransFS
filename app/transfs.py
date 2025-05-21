#!/usr/bin/env python

import os
from pathlib import Path

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

        # System level: list maps
        system_name = path.parts[len(Path(self.root).parts) + 1]
        system = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system:
            return dirents

        if lev == 2:
            for map_entry in system['maps']:
                map_name = list(map_entry.keys())[0]
                # Build the virtual path for this map
                map_virtual_path = os.path.join(full_path, map_name)
                source_path = self.get_source_path(map_virtual_path)
                if source_path:
                    if os.path.isdir(source_path):
                        dirents.append(map_name)
                    elif os.path.isfile(source_path):
                        dirents.append(map_name)
            return dirents

        # Map level: list files in the mapped directory, if any
        map_name = path.parts[len(Path(self.root).parts) + 2]
        map_virtual_path = str(full_path)
        source_path = self.get_source_path(map_virtual_path)
        if source_path and os.path.isdir(source_path):
            for entry in os.listdir(source_path):
                dirents.append(entry)
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
            st = os.lstat( full_path)
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
        return os.open(trans_path, flags)

    def get_source_path(self, translated_path):
        """
        Given a translated path (as seen under the FUSE mount), return the corresponding
        source path in the filestore, using the translation logic from TransFS.
        """
        path = Path(translated_path)
        mountpoint = Path(self.root)
        parts = path.parts
        root_parts = mountpoint.parts
        rel_parts = parts[len(root_parts):]  # parts after the filestore root

        if not rel_parts:
            return self.config.get("filestore", "/mnt/filestorefs")  # root maps to filestore root

        # Find client
        client_name = rel_parts[0]
        client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
        if not client:
            return None

        # If only client is specified, return filestore root
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
            # Try to find system_name in rel_parts by matching known systems
            for sys in client['systems']:
                if sys['name'] in rel_parts:
                    system_name = sys['name']
                    break

        # Find system_info
        system_info = next((s for s in client['systems'] if s['name'] == system_name), None)
        if not system_info:
            return None

        # Handle maps
        if "{maps}" in path_template_parts:
            idx = path_template_parts.index("{maps}")
            if len(rel_parts) > idx:
                map_name = rel_parts[idx]
                mapinfo = system_info['maps']
                map_entry = next((m for m in mapinfo if map_name == list(m.keys())[0]), None)
                if map_entry:
                    mapdict = map_entry[map_name]
                    # If it's a directory mapping
                    if "source_dir" in mapdict:
                        base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                            system_info['local_base_path'], mapdict["source_dir"])
                        subpath = rel_parts[idx+1:]
                        return os.path.join(base, *subpath) if subpath else base
                    # If it's a file mapping
                    elif "source_filename" in mapdict:
                        base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                            system_info['local_base_path'], mapdict["source_filename"])
                        subpath = rel_parts[idx+1:]
                        return os.path.join(base, *subpath) if subpath else base
                    elif "default_source" in mapdict:
                        ds = mapdict["default_source"]
                        if "source_dir" in ds:
                            base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                                system_info['local_base_path'], ds["source_dir"])
                            subpath = rel_parts[idx+1:]
                            return os.path.join(base, *subpath) if subpath else base
                        elif "source_filename" in ds:
                            base = os.path.join(self.config.get("filestore", "/mnt/filestorefs"),
                                                system_info['local_base_path'], ds["source_filename"])
                            subpath = rel_parts[idx+1:]
                            return os.path.join(base, *subpath) if subpath else base
        # If not a maps path, just join filestore, local_base_path, and the rest
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
