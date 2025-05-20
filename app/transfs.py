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

        path = Path(full_path)
        lev = len(path.parts) - len(Path(self.root).parts)

        dirents = []

        if lev == 0:
            # It's the top level, return Client List

            for client in self.config['clients']:
                dirents.extend({client['name']})
        else:
            # Part 1 should contain the client, so lets look for that and get the remaining parth

            for client in self.config['clients']:

                if path.parts[len(Path(self.root).parts)] == client["name"]:

                    system_name = ""

                    path_str = client['default_target_path']
                    
                    if lev <= len(Path(path_str).parts)-1:
                        final_dir = Path(path_str).parts[lev]
                    else:
                        final_dir = ""
                        
                    if "{system_name}" in final_dir:
                        for systemtype in client['systems']:
                            output_dir = final_dir.replace(
                                "{system_name}", systemtype['name'])
                            dirents.extend({output_dir})
                    elif "{system_name}" in path_str:
                        first_match = next(((i, s) for i, s in enumerate(
                            Path(path_str).parts) if "{system_name}" in s), None)
                        if first_match:
                            system_name = Path(
                                full_path).parts[first_match[0]+len(Path(self.root).parts)]
                        else:
                            system_name = f"Unknown {system_name}"
                    if "{maps}" in path_str:
                        if system_name:       
                            for system_info in client['systems']:
                                if system_name == system_info['name']:
                                    local_base_path = system_info['local_base_path']
                                    mapinfo = system_info['maps']
                                    keys = [list(d.keys())[0] for d in mapinfo]

                                    if "{maps}" in final_dir:

                                        for mapfilename in keys:
                                            outputfilename = os.path.basename(mapfilename)
                                            output_dir = final_dir.replace(
                                                "{maps}", outputfilename)
                                            dirents.extend({output_dir})
                                    else: 
                                        end_path = os.path.join(*path.parts[len(Path(path_str).parts)+len(Path(self.config['mountpoint']).parts)-1:])

                                        for parts in Path(end_path).parts:
                                            maplist = next((m for m in mapinfo if parts == list(m.keys())[0]), None)
                                            if maplist is not None:
                                                maplist = maplist[parts]

                                                if "source_dir" in maplist:
                                                    end_path = end_path.replace(parts, maplist["source_dir"])
                                                elif "source_filename" in maplist:
                                                    end_path = end_path.replace(parts, maplist["source_filename"])

                                        local_path = self.config['filestore']+"/"+local_base_path+"/" +end_path

                                        if Path(local_path).is_dir():

                                            for files in os.listdir(local_path):
                                                dirents.extend({files})

                                        print(f"local_base_path: {local_path}")


        return dirents

    # Helpers
    # =======
    def _full_path(self, partial):
        print(f"full path is {partial}")

        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

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
