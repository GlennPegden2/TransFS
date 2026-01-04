"""
ZIP utility functions for TransFS.
Contains helper functions for working with ZIP archives in the virtual filesystem.
"""
import os
import zipfile
from typing import Optional, Tuple


def find_file_in_zip(zip_path: str, target_name: str) -> Optional[str]:
    """
    Return the internal path in zip matching the basename target_name, or None.
    
    Args:
        zip_path: Path to the ZIP file
        target_name: Basename of the file to find
        
    Returns:
        Internal path within ZIP if found, None otherwise
    """
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.split('/')[-1] == target_name:
                return name
    return None


def get_zip_mapping(logger, base: str, map_name: str) -> Optional[Tuple[str, str]]:
    """
    Return (zip_path, internal_file) if map_name is found in zip, else None.
    
    Args:
        logger: Logger instance
        base: Path to the ZIP file
        map_name: Name of the file to find within the ZIP
        
    Returns:
        Tuple of (zip_path, internal_file_path) if found, None otherwise
    """
    logger.debug(f"Trying to map {map_name} inside zip {base}")
    if not os.path.exists(base):
        return None
    internal_file = find_file_in_zip(base, map_name)
    if internal_file:
        return (base, internal_file)
    return None