#!/usr/bin/env python3
"""Check Atari 2600 config loading."""

from config import read_config
config = read_config()
archive_sources = config.get('archive_sources', {})

# Check Atari
if 'Atari' in archive_sources:
    atari_systems = archive_sources['Atari']
    print('Atari systems:', list(atari_systems.keys()))
    
    if 'Atari2600' in atari_systems:
        atari2600_config = atari_systems['Atari2600']
        print('\nAtari 2600 Config:')
        print('  Keys:', list(atari2600_config.keys()))
        
        # Check packs
        packs = atari2600_config.get('packs', [])
        print(f'  Packs: {len(packs)}')
        for pack in packs:
            print(f'    - {pack.get("name")}: metadata = {pack.get("metadata", {})}')
        
        # Check sources
        sources = atari2600_config.get('sources', [])
        print(f'  Sources: {len(sources)}')
        for source in sources:
            print(f'    - {source.get("name")} (folder: {source.get("folder")})')
else:
    print('Atari not found in archive_sources')
    print('Available manufacturers:', list(archive_sources.keys())[:10])
