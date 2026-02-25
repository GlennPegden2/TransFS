#!/usr/bin/env python3
"""Test MAME download manager directly."""

import sys
import os
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add app directory to path
sys.path.insert(0, '/app')

from config import read_config
from mame.manager import MAMEDownloadManager

def test_mame_download():
    """Test MAME download for Atom system."""
    logger.info("=" * 60)
    logger.info("MAME Download Test Starting")
    logger.info("=" * 60)
    
    logger.info("Loading configuration...")
    config = read_config()
    
    logger.info("Initializing MAME Download Manager...")
    manager = MAMEDownloadManager(config)
    
    logger.info(f"Configuration:")
    logger.info(f"  Hash repo URL: {manager.hash_repo_url}")
    logger.info(f"  Archive base URL: {manager.archive_base_url}")
    logger.info(f"  Download root: {manager.download_root}")
    logger.info(f"  Verify checksums: {manager.verify_checksums}")
    logger.info(f"  Cache hash files: {manager.cache_hash_files}")
    logger.info("")
    
    logger.info("Testing hash file fetch for atom_cass...")
    hash_content = manager._get_hash_file("atom", "cass")
    if hash_content:
        logger.info(f"✓ Hash file fetched successfully ({len(hash_content)} bytes)")
        logger.info(f"  First 200 chars: {hash_content[:200]}...")
    else:
        logger.error("✗ Failed to fetch hash file")
        return 1
    
    logger.info("")
    logger.info("Attempting to download Atom cassette software...")
    logger.info("(This will download to: {}/Software/MAME/Cassettes)".format(manager.download_root))
    
    try:
        stats = manager.download_for_system(
            system="atom",
            media_type="cass",
            target_folder="Software/MAME/Cassettes",
            filters={"exclude_unsupported": True}
        )
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("Download completed!")
        logger.info("=" * 60)
        logger.info(f"Statistics:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        
        return 0
        
    except Exception as e:
        logger.error("")
        logger.error("=" * 60)
        logger.error(f"Download failed with exception:")
        logger.error("=" * 60)
        logger.error(f"{type(e).__name__}: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(test_mame_download())
