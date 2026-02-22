#!/usr/bin/env python3
from config import read_config
from sourcepath import get_source_path
from logging import getLogger
import os

logger = getLogger()
config = read_config('config')
path = '/mnt/transfs/MiSTer/Archie/riscos3_71.rom'
result = get_source_path(logger, config, '/mnt/transfs', path)
print(f'Path: {path}')
print(f'Result: {result}')
if isinstance(result, str):
    print(f'Is file: {os.path.isfile(result)}')
    print(f'Is dir: {os.path.isdir(result)}')
    if os.path.exists(result):
        stat_info = os.stat(result)
        print(f'Size: {stat_info.st_size}')
        print(f'Mode: {oct(stat_info.st_mode)}')
