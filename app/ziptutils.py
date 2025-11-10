import os
import zipfile
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

def list_zip_file(zip_path: str) -> list:
    """Return a list of files (not directories) in a zip archive."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return [n for n in zf.namelist() if not n.endswith('/')]


def find_file_in_zips(parent_dir: str, filename: str) -> Optional[Tuple[str, str]]:
    """Search all zip files in a directory for a file with the given name."""
    for entry in os.listdir(parent_dir):
        if entry.lower().endswith('.zip'):
            zip_path = os.path.join(parent_dir, entry)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.split('/')[-1] == filename:
                        return zip_path, name
    return None


def list_dir_with_zip(dir_path: str, supports_zip: bool) -> set:
    """List directory contents, handling zip-as-folder logic if needed."""
    entries = set()
    if os.path.isdir(dir_path):
        for entry in os.listdir(dir_path):
            entry_path = os.path.join(dir_path, entry)
            if (
                entry.lower().endswith('.zip')
#                and not supports_zip
            ):
                try:
                    namelist = list_zip_file(entry_path)
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
#        and not supports_zip
    ):
        try:
            namelist = list_zip_file(dir_path)
            if len(namelist) == 1:
                entries.add(namelist[0].split('/')[-1])
            else:
                for name in namelist:
                    entries.add(name.split('/')[-1])
        except zipfile.BadZipFile:
            pass
    return entries

def find_file_in_zip(zip_path: str, target_name: str) -> Optional[str]:
    """Return the internal path in zip matching the basename target_name, or None."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.split('/')[-1] == target_name:
                return name
    return None

def get_zip_mapping(logger,base: str, map_name: str) -> Optional[Tuple[str, str]]:
    """Return (zip_path, internal_file) if map_name is found in zip, else None."""
    logger.debug(f"Trying to map {map_name} inside zip {base}")
    if not os.path.exists(base):
        return None
    internal_file = find_file_in_zip(base, map_name)
    if internal_file:
        return (base, internal_file)
    return None