#!/usr/bin/env python3
import sys

files = [
    '/tmp/4th_inches_disk1.dos33-original.dsk',
    '/tmp/4th_inches_disk1.prodos-reordered.dsk',
    '/tmp/4th_inches_disk1.do',
    '/tmp/4th_inches_disk1.po',
]

print("Boot sector comparison:")
print("="*80)
for fpath in files:
    with open(fpath, 'rb') as f:
        boot = f.read(32)
        name = fpath.split('/')[-1]
        print(f'\n{name}')
        print(f'  {" ".join(f"{b:02x}" for b in boot[:16])}')
        print(f'  {" ".join(f"{b:02x}" for b in boot[16:32])}')
