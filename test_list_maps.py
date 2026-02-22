#!/usr/bin/env python3
from pathlib import Path
from config import read_config
from dirlisting import list_maps

config = read_config('config')
client = next(c for c in config['clients'] if c['name'] == 'MiSTer')
system = next(s for s in client['systems'] if s['name'] == 'AcornAtom')

print('System maps defined in AcornAtom:')
for m in system['maps']:
    name = list(m.keys())[0]
    val = m[name]
    print(f'  {name}: {val}')

root = Path('/mnt/transfs')
path = root / 'MiSTer' / 'AcornAtom'
maps = list_maps(config, path, root.parts)
print(f'\nlist_maps() returns: {maps}')
