"""
MAME Download Manager

Orchestrates MAME software downloads based on configuration.
"""

import os
import json
import shutil
import logging
from typing import List, Dict, Optional, Callable
from pathlib import Path
from dataclasses import asdict
from .hash_parser import MAMEHashParser, SoftwareEntry
from .downloader import MAMEDownloader

logger = logging.getLogger(__name__)


class MAMEDownloadManager:
    """Manage MAME software downloads for configured systems."""
    
    def __init__(self, config: Dict, logger_instance=None):
        """
        Initialize manager with configuration.
        
        Args:
            config: Full application configuration dict
            logger_instance: Optional logger instance
        """
        self.logger = logger_instance or logger
        self.config = config
        
        # Extract MAME config
        mame_config = config.get('mame', {})
        self.hash_repo_url = mame_config.get(
            'hash_repo_url',
            'https://raw.githubusercontent.com/mamedev/mame/master/hash'
        )
        self.archive_base_url = mame_config.get(
            'archive_base_url',
            'https://ia801806.us.archive.org/12/items/MAME_0.228_Software_List_ROMs_merged/MAME_0.228_Software_List_ROMs_merged.zip'
        )
        self.download_root = mame_config.get(
            'download_root',
            '/data/retronas/Downloads/MAME'
        )
        self.verify_checksums = mame_config.get('verify_checksums', True)
        self.max_concurrent = mame_config.get('max_concurrent_downloads', 3)
        self.cache_hash_files = mame_config.get('cache_hash_files', True)
        filestore_root = config.get('filestore', '/data/retronas')
        
        # Initialize components
        self.parser = MAMEHashParser(logger_instance=self.logger)
        self.downloader = MAMEDownloader(
            archive_base_url=self.archive_base_url,
            download_root=self.download_root,
            verify_checksums=self.verify_checksums,
            logger_instance=self.logger
        )
        
        # Hash file cache directory (runtime data belongs in filestore, not config)
        default_cache_dir = os.path.join(filestore_root, 'Native', 'Clients', 'Mame', 'mame_cache')
        self.cache_dir = mame_config.get('hash_cache_dir', default_cache_dir)
        self.legacy_cache_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'mame_cache')
        if self.cache_hash_files:
            os.makedirs(self.cache_dir, exist_ok=True)
            self._migrate_legacy_hash_cache()
            self.logger.info(f"MAME hash cache directory: {os.path.abspath(self.cache_dir)}")
        else:
            self.logger.info("MAME hash file caching disabled (cache_hash_files=false)")

    def _migrate_legacy_hash_cache(self) -> None:
        """Migrate legacy hash cache files from app/config/mame_cache to filestore."""
        legacy_dir = os.path.abspath(self.legacy_cache_dir)
        new_dir = os.path.abspath(self.cache_dir)

        if legacy_dir == new_dir or not os.path.isdir(legacy_dir):
            return

        moved = 0
        for filename in os.listdir(legacy_dir):
            if not filename.lower().endswith('.xml'):
                continue

            src = os.path.join(legacy_dir, filename)
            dst = os.path.join(new_dir, filename)
            if os.path.exists(dst):
                continue

            try:
                shutil.copy2(src, dst)
                moved += 1
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(f"Failed to migrate legacy hash cache file {filename}: {exc}")

        if moved > 0:
            self.logger.info(
                f"Migrated {moved} MAME hash cache file(s) from {legacy_dir} to {new_dir}"
            )
    
    def discover_systems_with_mame_sources(self) -> List[Dict]:
        """
        Scan all source YAML files for sources with type: mame.
        
        Returns:
            List of dicts with system info and MAME source config
        """
        from config import load_yaml
        
        systems = []
        
        # Scan all source directories
        sources_root = os.path.join(
            os.path.dirname(__file__),
            '..',
            'config',
            'sources',
            'default'  # TODO: Support multiple source sets
        )
        
        if not os.path.exists(sources_root):
            self.logger.warning(f"Sources directory not found: {sources_root}")
            return systems
        
        # Walk through all YAML files
        for root, dirs, files in os.walk(sources_root):
            for filename in files:
                if filename.endswith('.yaml'):
                    filepath = os.path.join(root, filename)
                    try:
                        source_config = load_yaml(filepath)
                        
                        # Check sources array for type: mame entries
                        mame_sources = []
                        for source in source_config.get('sources', []):
                            if source.get('type') == 'mame':
                                mame_sources.append(source)
                        
                        if mame_sources:
                            # Extract system path from file structure
                            rel_path = os.path.relpath(filepath, sources_root)
                            system_path = os.path.dirname(rel_path)
                            
                            systems.append({
                                'config_file': filepath,
                                'system_path': system_path,
                                'mame_sources': mame_sources
                            })
                            
                            self.logger.info(
                                f"Found MAME sources in {rel_path}: "
                                f"{len(mame_sources)} source(s)"
                            )
                    except Exception as e:
                        self.logger.warning(f"Error reading {filepath}: {e}")
        
        return systems
    
    def download_for_system(
        self,
        system: str,
        media_type: str,
        target_folder: str,
        filters: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        base_path_override: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Download all software for a specific system and media type.
        
        Args:
            system: System name (e.g., "atom")
            media_type: Media type (e.g., "cass", "flop", "rom")
            target_folder: Target folder path (relative or absolute depending on base_path_override)
            filters: Optional filters dict with keys:
                - publishers: List of publisher names
                - exclude_unsupported: bool
                - year_range: tuple of (min_year, max_year)
            progress_callback: Optional callback(filename, file_num, total_files, bytes, total_bytes)
            base_path_override: If provided, use this as the base path instead of download_root
            
        Returns:
            Dict with download statistics
        """
        stats = {
            'total_entries': 0,
            'filtered_entries': 0,
            'total_files': 0,
            'downloaded': 0,
            'already_existed': 0,
            'failed': 0,
            'downloaded_bytes': 0
        }
        
        # Determine the base path to use
        base_path = base_path_override if base_path_override else self.download_root
        
        # Fetch hash file
        hash_content = self._get_hash_file(system, media_type)
        if not hash_content:
            self.logger.error(f"Failed to fetch hash file for {system}_{media_type}")
            return stats
        
        # Parse hash file
        entries = self.parser.parse_hash_file(hash_content)
        stats['total_entries'] = len(entries)
        
        if not entries:
            self.logger.warning(f"No entries found in hash file for {system}_{media_type}")
            return stats
        
        # Apply filters
        if filters:
            entries = self.parser.filter_entries(
                entries,
                publishers=filters.get('publishers'),
                exclude_unsupported=filters.get('exclude_unsupported', False),
                year_range=filters.get('year_range')
            )
        
        stats['filtered_entries'] = len(entries)
        
        # Count total files
        total_files = sum(len(entry.rom_files) for entry in entries)
        stats['total_files'] = total_files
        
        self.logger.info(
            f"Downloading {total_files} files from {len(entries)} software entries "
            f"for {system}_{media_type} to {base_path}/{target_folder}"
        )
        
        # Download files
        file_num = 0
        for entry in entries:
            for rom_file in entry.rom_files:
                file_num += 1
                
                # Check if already exists
                target_path = os.path.join(base_path, target_folder, rom_file.name)
                already_exists = os.path.exists(target_path)
                
                # Progress callback
                if progress_callback:
                    progress_callback(
                        rom_file.name,
                        file_num,
                        total_files,
                        0,
                        rom_file.size
                    )
                
                # Download with progress tracking
                def file_progress(bytes_downloaded, total_bytes):
                    if progress_callback:
                        progress_callback(
                            rom_file.name,
                            file_num,
                            total_files,
                            bytes_downloaded,
                            total_bytes
                        )
                
                success = self.downloader.download_file(
                    entry,  # Pass SoftwareEntry for nested ZIP download
                    rom_file,
                    target_folder,
                    progress_callback=file_progress,
                    base_path_override=base_path
                )
                
                if success:
                    if already_exists:
                        stats['already_existed'] += 1
                    else:
                        stats['downloaded'] += 1
                        stats['downloaded_bytes'] += rom_file.size
                else:
                    stats['failed'] += 1
        
        self.logger.info(
            f"Download complete for {system}_{media_type}: "
            f"{stats['downloaded']} new, {stats['already_existed']} existing, "
            f"{stats['failed']} failed"
        )
        
        return stats
    
    def _get_hash_file(self, system: str, media_type: str) -> Optional[str]:
        """
        Get hash file content, using cache if available.
        
        Args:
            system: System name
            media_type: Media type
            
        Returns:
            XML content or None
        """
        filename = f"{system}_{media_type}.xml"
        cache_path = os.path.join(self.cache_dir, filename)
        
        # Check cache first
        if self.cache_hash_files and os.path.exists(cache_path):
            self.logger.info(f"Using cached hash file: {filename}")
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                self.logger.warning(f"Failed to read cache: {e}")
        
        # Fetch from repository
        content = self.downloader.fetch_hash_file(
            self.hash_repo_url,
            system,
            media_type
        )
        
        # Cache for future use
        if content and self.cache_hash_files:
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.logger.info(f"Cached hash file: {filename}")
            except Exception as e:
                self.logger.warning(f"Failed to cache hash file: {e}")
        
        return content
    
    def download_all_configured(
        self,
        progress_callback: Optional[Callable[[str, Dict], None]] = None
    ) -> Dict[str, Dict]:
        """
        Download all configured MAME software across all systems.
        
        Args:
            progress_callback: Optional callback(system_key, stats_dict)
            
        Returns:
            Dict mapping system keys to download stats
        """
        systems = self.discover_systems_with_mame_sources()
        
        if not systems:
            self.logger.warning("No systems configured for MAME downloads")
            return {}
        
        all_stats = {}
        
        for system_config in systems:
            for mame_source in system_config['mame_sources']:
                source_name = mame_source.get('name', 'Unknown')
                system = mame_source.get('system')
                media_types = mame_source.get('media_types', [])
                filters = mame_source.get('filters')
                
                if not system or not media_types:
                    self.logger.warning(f"Invalid MAME source config: {source_name}")
                    continue
                
                for media_config in media_types:
                    media_type = media_config.get('type')
                    # Support both 'folder' (new) and 'target_folder' (legacy) field names
                    target_folder = media_config.get('folder') or media_config.get('target_folder')
                    
                    if not media_type or not target_folder:
                        continue
                    
                    key = f"{system}_{media_type}"
                    self.logger.info(f"Starting download for {key} ({source_name})")
                    
                    stats = self.download_for_system(
                        system,
                        media_type,
                        target_folder,
                        filters
                    )
                    
                    all_stats[key] = stats
                    
                    if progress_callback:
                        progress_callback(key, stats)
        
        return all_stats
    
    def get_download_status(self) -> Dict[str, any]:
        """
        Get current download status and inventory.
        
        Returns:
            Dict with download directory stats and file counts
        """
        if not os.path.exists(self.download_root):
            return {'exists': False}
        
        total_files = 0
        total_size = 0
        
        for root, dirs, files in os.walk(self.download_root):
            total_files += len(files)
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except:
                    pass
        
        return {
            'exists': True,
            'download_root': self.download_root,
            'total_files': total_files,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        }
