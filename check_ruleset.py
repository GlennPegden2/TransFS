#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from app.config import load_sources

sources = load_sources()
atari = [s for s in sources if s['id'] == 'Atari2600']
if atari:
    atari = atari[0]
    for pack in atari.get('packs', []):
        meta = pack.get('metadata', {})
        ruleset = meta.get('ruleset')
        print(f"Pack {pack.get('id')}:")
        print(f"  ruleset={repr(ruleset)}")
        print(f"  type={type(ruleset).__name__}")
        print(f"  is None: {ruleset is None}")
