from typing import Dict, List, Tuple, Optional

def parse_filetype_map(filetypes_entry) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    Parse a filetypes entry like {'ROM': 'ROM, BIN:ROM, HEX:ROM'} or {'HDs': 'MMB:VHD,VHD'}
    Returns a dict: {virtual_folder: [real_exts]}
    and a reverse map: {real_ext: virtual_ext}
    
    The folder name (key) is always used as the virtual folder.
    For entries with REAL:VIRTUAL syntax, the REAL extension is added to the folder's
    real_exts list, and the reverse map records REAL->VIRTUAL for display transformation.
    """
    mapping = {}
    reverse = {}
    for virtual_folder, exts in filetypes_entry.items():
        mapping.setdefault(virtual_folder.upper(), [])
        for ext in exts.split(','):
            ext = ext.strip()
            if ':' in ext:
                # REAL:VIRTUAL syntax - add REAL to this folder, map REAL->VIRTUAL for display
                real_ext, virt_ext = ext.split(':', 1)
                mapping[virtual_folder.upper()].append(real_ext.upper())
                reverse[real_ext.upper()] = virt_ext.upper()
            else:
                # Plain extension - add to this folder
                mapping[virtual_folder.upper()].append(ext.upper())
                # Do NOT add to reverse here!
    return mapping, reverse

def get_filetype_transforms(sa_entry) -> Dict[str, List]:
    """
    Extract transformation configuration from ...SoftwareArchives... filetypes.
    Returns: {real_ext: [transform_specs]}
    
    Example configuration in clients.yaml:
      filetypes:
      - Disks: "DSK,DO,2MG"
        transforms:
          DSK:
            - type: strip_header
              bytes: 64
    """
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    transform_map = {}
    
    for filetype_entry in filetypes:
        if isinstance(filetype_entry, dict):
            # Check if 'transforms' key exists in this entry
            if 'transforms' in filetype_entry:
                transforms_config = filetype_entry['transforms']
                if isinstance(transforms_config, dict):
                    for ext, transform_specs in transforms_config.items():
                        transform_map[ext.upper()] = transform_specs
    
    return transform_map

def get_filetype_maps(sa_entry) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    Build filetype mapping and reverse mapping for a ...SoftwareArchives... entry.
    Returns: {virtual_folder: [real_exts]}, {real_ext: virtual_ext}
    """
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    mapping = {}
    reverse = {}
    for filetype in filetypes:
        for virtual_folder, exts in filetype.items():
            # Skip non-filetype keys like 'transforms'
            if virtual_folder == 'transforms':
                continue
            m, r = parse_filetype_map({virtual_folder: exts})
            for k, v in m.items():
                mapping.setdefault(k, []).extend(v)
            reverse.update(r)
    return mapping, reverse

def virtual_to_real_candidates(virtual_folder, filename, filetype_map):
    """
    Given a virtual folder (e.g. 'ROM') and filename (e.g. 'TEST.ROM'),
    return a list of possible real file paths.
    """
    import os
    name, _ = os.path.splitext(filename)
    real_exts = filetype_map.get(virtual_folder.upper(), [])
    return [f"{name}.{real_ext.lower()}" for real_ext in real_exts]

def real_to_virtual_name(real_name, real_ext, virtual_ext):
    """
    Given a real filename and its extension, return the virtual filename with the virtual extension.
    """
    import os
    name, _ = os.path.splitext(real_name)
    return f"{name}.{virtual_ext.lower()}"