"""
MAME Software Downloader

Automatically downloads MAME software based on hash file definitions
from the Internet Archive MAME software collection.
"""

from .hash_parser import MAMEHashParser, SoftwareEntry
from .downloader import MAMEDownloader
from .manager import MAMEDownloadManager

__all__ = ['MAMEHashParser', 'SoftwareEntry', 'MAMEDownloader', 'MAMEDownloadManager']
