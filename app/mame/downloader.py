"""
MAME Software Downloader

Downloads MAME software files from Internet Archive with checksum verification.
"""

import os
import hashlib
import logging
import requests
from typing import Optional, Callable
from pathlib import Path
from .hash_parser import ROMFile

logger = logging.getLogger(__name__)


class MAMEDownloader:
    """Download MAME software files with verification."""
    
    def __init__(
        self,
        archive_base_url: str,
        download_root: str,
        verify_checksums: bool = True,
        logger_instance=None
    ):
        """
        Initialize downloader.
        
        Args:
            archive_base_url: Base URL for Internet Archive MAME collection
            download_root: Root directory for downloads
            verify_checksums: Whether to verify SHA1 checksums after download
            logger_instance: Optional logger instance
        """
        self.archive_base_url = archive_base_url.rstrip('/')
        self.download_root = download_root
        self.verify_checksums = verify_checksums
        self.logger = logger_instance or logger
        
        # Create download root if it doesn't exist
        os.makedirs(self.download_root, exist_ok=True)
    
    def build_download_url(self, filename: str) -> str:
        """
        Build download URL for a file.
        
        Internet Archive allows direct file access within zip archives using:
        https://server/path/archive.zip/filename
        
        Args:
            filename: Name of file to download
            
        Returns:
            Full download URL
        """
        # Internet Archive quirk: files inside zip archives can be accessed directly
        return f"{self.archive_base_url}/{filename}"
    
    def download_file(
        self,
        rom_file: ROMFile,
        target_folder: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        force: bool = False
    ) -> bool:
        """
        Download a single ROM file.
        
        Args:
            rom_file: ROMFile object with metadata
            target_folder: Target folder relative to download_root
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            force: Force re-download even if file exists
            
        Returns:
            True if download succeeded, False otherwise
        """
        # Build target path
        target_dir = os.path.join(self.download_root, target_folder)
        os.makedirs(target_dir, exist_ok=True)
        
        target_path = os.path.join(target_dir, rom_file.name)
        
        # Check if already downloaded and valid
        if not force and os.path.exists(target_path):
            if self._verify_file(target_path, rom_file):
                self.logger.info(f"File already exists and verified: {rom_file.name}")
                return True
            else:
                self.logger.warning(f"File exists but checksum mismatch: {rom_file.name}, re-downloading")
        
        # Download
        url = self.build_download_url(rom_file.name)
        self.logger.info(f"Downloading {rom_file.name} from {url}")
        
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size == 0:
                total_size = rom_file.size  # Use expected size from hash
            
            downloaded = 0
            
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            # Verify download
            if self.verify_checksums:
                if not self._verify_file(target_path, rom_file):
                    self.logger.error(f"Checksum verification failed for {rom_file.name}")
                    os.remove(target_path)
                    return False
            
            self.logger.info(f"Successfully downloaded: {rom_file.name}")
            return True
            
        except requests.RequestException as e:
            self.logger.error(f"Download failed for {rom_file.name}: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error downloading {rom_file.name}: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
    
    def _verify_file(self, filepath: str, rom_file: ROMFile) -> bool:
        """
        Verify file checksum.
        
        Args:
            filepath: Path to downloaded file
            rom_file: ROMFile with expected checksums
            
        Returns:
            True if checksums match, False otherwise
        """
        if not os.path.exists(filepath):
            return False
        
        # Check size first (fast)
        actual_size = os.path.getsize(filepath)
        if actual_size != rom_file.size:
            self.logger.warning(
                f"Size mismatch for {rom_file.name}: "
                f"expected {rom_file.size}, got {actual_size}"
            )
            return False
        
        # Calculate SHA1
        sha1_hash = hashlib.sha1()
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha1_hash.update(chunk)
            
            actual_sha1 = sha1_hash.hexdigest()
            
            if actual_sha1.lower() != rom_file.sha1.lower():
                self.logger.warning(
                    f"SHA1 mismatch for {rom_file.name}: "
                    f"expected {rom_file.sha1}, got {actual_sha1}"
                )
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error verifying {filepath}: {e}")
            return False
    
    def fetch_hash_file(self, hash_repo_url: str, system: str, media_type: str) -> Optional[str]:
        """
        Fetch hash XML file from MAME GitHub repository.
        
        Args:
            hash_repo_url: Base URL for hash files (e.g., https://raw.githubusercontent.com/.../hash)
            system: System name (e.g., "atom")
            media_type: Media type (e.g., "cass", "flop", "rom")
            
        Returns:
            XML content as string, or None if fetch failed
        """
        filename = f"{system}_{media_type}.xml"
        url = f"{hash_repo_url.rstrip('/')}/{filename}"
        
        self.logger.info(f"Fetching hash file: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            self.logger.debug(f"Successfully fetched {filename} ({len(response.text)} bytes)")
            return response.text
        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout fetching hash file {filename} from {url} (timeout: 30s)")
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error fetching hash file {filename}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error fetching hash file {filename}: {e}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch hash file {filename}: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching hash file {filename}: {type(e).__name__}: {e}")
            return None
