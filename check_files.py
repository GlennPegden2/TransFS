#!/usr/bin/env python3
import os

print("=== Files in A52/Prototype Games/ ===")
a52_files = os.listdir('/mnt/filestorefs/Native/Atari/5200/Software/A52/Prototype Games')
print(f"Count: {len(a52_files)}")
for f in sorted(a52_files)[:10]:
    print(f"  {f}")

print("\n=== Files in BIN/Prototype Games/ ===")
bin_files = os.listdir('/mnt/filestorefs/Native/Atari/5200/Software/BIN/Prototype Games')
print(f"Count: {len(bin_files)}")
for f in sorted(bin_files)[:10]:
    print(f"  {f}")

print("\n=== Union of both ===")
all_files = sorted(set(a52_files + bin_files))
print(f"Count: {len(all_files)}")
for f in all_files[:10]:
    print(f"  {f}")

print("\n=== Check if 'Astro Chase' is in either ===")
astro_in_a52 = [f for f in a52_files if 'Astro Chase' in f]
astro_in_bin = [f for f in bin_files if 'Astro Chase' in f]
print(f"In A52: {astro_in_a52}")
print(f"In BIN: {astro_in_bin}")
