#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from config import read_config
import json

config = read_config()
clients = [c['name'] for c in config.get('clients', [])]
print(json.dumps(clients, indent=2))
