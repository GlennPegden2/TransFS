#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from app.sourcepath import get_source_path
from app.config import read_config
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
config = read_config('/app/config')

result = get_source_path(logger, config, '/mnt/transfs', '/mnt/transfs/MiSTer/Archie/riscos.rom')
print(f"Result type: {type(result)}")
print(f"Result: {result}")
