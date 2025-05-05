#!/usr/bin/env python

import os
import yaml

from fuse import FUSE
from passthroughfs import Passthrough
from pathlib import Path


class trans_fs(Passthrough):
    def __init__(self, root):
        print("Starting TransFS")
        self.root = root
        with open("transfs.yaml", "r", encoding="UTF-8") as f:
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

                    path_str = client['default_target_path']

                    final_dir = Path(path_str).parts[lev]

                    if "{system_name}" in final_dir:
                        for systemtype in client['systems']:
                            output_dir = final_dir.replace(
                                "{system_name}", systemtype['name'])
                            dirents.extend({output_dir})
                    elif "{system_name}" in path_str:
                        first_match = next(((i, s) for i, s in enumerate(
                            Path(path_str).parts) if "{system_name}" in s), None)
                        system_name = Path(
                            full_path).parts[first_match[0]+len(Path(self.root).parts)]

                    if "{map}" in final_dir:

                        # TODO - This is where you are up to
                        pass

                    else:
                        dirents.extend(
                            {'XXX2'+str(path.parts[len(path.parts)-1])+client["name"]})

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

        if self._is_virtual_path(full_path):
            st = os.lstat("/")
        else:
            st = os.lstat(full_path)

        return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                                                        'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))


def main(mountpoint, root):
    FUSE(trans_fs(root), mountpoint, nothreads=True,
         foreground=True, **{'allow_other': True})


if __name__ == '__main__':
    mountpoint = "/mnt/transfs"
    root = "/mnt/filestorefs"
    main(mountpoint, root)
