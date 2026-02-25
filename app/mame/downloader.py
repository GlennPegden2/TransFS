"""
MAME Software Downloader

Downloads MAME software files from Internet Archive with checksum verification.
"""

import os
import io
import hashlib
import logging
import requests
import zipfile
from typing import Optional, Callable
from pathlib import Path
from .hash_parser import ROMFile, SoftwareEntry

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
    
    def build_download_url(self, softwarelist_name: str, software_name: str) -> str:
        """
        Build download URL for a MAME software zip file.
        
        MAME Software Lists are organized as nested ZIPs:
        archive.zip/atom_cass/747.zip (contains the actual ROM files)
        
        Internet Archive allows direct file access within zip archives using:
        https://server/path/archive.zip/subfolder/file.zip
        
        Args:
            softwarelist_name: Software list name (e.g., "atom_cass")
            software_name: Software name (e.g., "747")
            
        Returns:
            Full download URL for the nested zip file
        """
        from urllib.parse import quote
        # Build path to nested zip: softwarelist/software.zip
        nested_path = f"{softwarelist_name}/{software_name}.zip"
        # URL encode the path (Internet Archive requires proper encoding)
        return f"{self.archive_base_url}/{quote(nested_path, safe='')}"
    
    def download_file(
        self,
        software_entry: SoftwareEntry,
        rom_file: ROMFile,
        target_folder: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        force: bool = False
    ) -> bool:
        """
        Download a single ROM file from a MAME software entry.
        
        Downloads the nested ZIP file ({softwarelist}/{software}.zip),
        extracts the ROM file from inside it, and verifies checksums.
        
        Args:
            software_entry: SoftwareEntry containing software metadata
            rom_file: ROMFile object with file metadata
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
        
        # Build URL for nested zip file
        url = self.build_download_url(software_entry.softwarelist_name, software_entry.software_name)
        self.logger.info(f"Downloading {software_entry.software_name}.zip from {url}")
        
        try:
            # Download the nested zip file
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            # Read zip content into memory
            zip_content = io.BytesIO()
            downloaded = 0
            
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    zip_content.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback:
                        progress_callback(downloaded, total_size if total_size > 0 else rom_file.size)
            
            # Extract ROM file from the zip
            zip_content.seek(0)
            with zipfile.ZipFile(zip_content, 'r') as zf:
                # Find the ROM file in the zip
                if rom_file.name not in zf.namelist():
                    self.logger.error(f"ROM file '{rom_file.name}' not found in zip '{software_entry.software_name}.zip'")
                    self.logger.debug(f"Available files in zip: {zf.namelist()}")
                    return False
                
                # Extract to target location
                with zf.open(rom_file.name) as rom_data:
                    with open(target_path, 'wb') as f:
                        f.write(rom_data.read())
            
            # Verify download
            if self.verify_checksums:
                if not self._verify_file(target_path, rom_file):
                    self.logger.error(f"Checksum verification failed for {rom_file.name}")
                    os.remove(target_path)
                    return False
            
            self.logger.info(f"Successfully downloaded and extracted: {rom_file.name}")
            return True
            
        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout downloading {software_entry.software_name}.zip from {url} (timeout: 30s)")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error downloading {software_entry.software_name}.zip: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error downloading {software_entry.software_name}.zip: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except zipfile.BadZipFile as e:
            self.logger.error(f"Invalid zip file for {software_entry.software_name}.zip: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except requests.RequestException as e:
            self.logger.error(f"Download failed for {software_entry.software_name}.zip: {type(e).__name__}: {e}")
            if os.path.exists(target_path):
                os.remove(target_path)
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error downloading {software_entry.software_name}.zip: {type(e).__name__}: {e}")
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
