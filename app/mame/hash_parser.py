"""
MAME Hash XML Parser

Parses MAME hash files from the official MAME repository to extract
software metadata including filenames, checksums, and descriptions.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ROMFile:
    """Represents a single ROM file within a software entry."""
    name: str
    size: int
    crc: str
    sha1: str


@dataclass
class SoftwareEntry:
    """Represents a MAME software entry from hash XML."""
    softwarelist_name: str  # Software list name (e.g., "atom_cass")
    software_name: str  # Unique ID from <software name="">
    description: str
    year: Optional[str]
    publisher: Optional[str]
    supported: bool  # True unless supported="no"
    rom_files: List[ROMFile]
    interface: str  # e.g., "atom_cass", "floppy_5_25"
    usage_info: Optional[str]  # <info name="usage"> content


class MAMEHashParser:
    """Parse MAME hash XML files to extract software listings."""
    
    def __init__(self, logger_instance=None):
        self.logger = logger_instance or logger
    
    def parse_hash_file(self, xml_content: str) -> List[SoftwareEntry]:
        """
        Parse a MAME hash XML file.
        
        Args:
            xml_content: Raw XML content as string
            
        Returns:
            List of SoftwareEntry objects
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse XML: {e}")
            return []
        
        # Extract software list name from root element
        softwarelist_name = root.get('name', 'unknown')
        
        entries = []
        
        for software in root.findall('.//software'):
            entry = self._parse_software_entry(software, softwarelist_name)
            if entry:
                entries.append(entry)
        
        self.logger.info(f"Parsed {len(entries)} software entries from hash file")
        return entries
    
    def _parse_software_entry(self, software_elem, softwarelist_name: str) -> Optional[SoftwareEntry]:
        """Parse a single <software> element."""
        software_name = software_elem.get('name')
        if not software_name:
            return None
        
        # Check if supported
        supported_attr = software_elem.get('supported', 'yes')
        supported = supported_attr.lower() != 'no'
        
        # Extract metadata
        description_elem = software_elem.find('description')
        description = description_elem.text if description_elem is not None else software_name
        
        year_elem = software_elem.find('year')
        year = year_elem.text if year_elem is not None else None
        
        publisher_elem = software_elem.find('publisher')
        publisher = publisher_elem.text if publisher_elem is not None else None
        
        # Extract usage info
        usage_info_elem = software_elem.find('.//info[@name="usage"]')
        usage_info = usage_info_elem.get('value') if usage_info_elem is not None else None
        
        # Extract ROM files from all parts
        rom_files = []
        interface = None
        
        for part in software_elem.findall('.//part'):
            part_interface = part.get('interface')
            if interface is None:
                interface = part_interface
            
            for rom in part.findall('.//rom'):
                rom_file = self._parse_rom_element(rom)
                if rom_file:
                    rom_files.append(rom_file)
        
        if not rom_files:
            self.logger.debug(f"Software '{software_name}' has no ROM files, skipping")
            return None
        
        return SoftwareEntry(
            softwarelist_name=softwarelist_name,
            software_name=software_name,
            description=description,
            year=year,
            publisher=publisher,
            supported=supported,
            rom_files=rom_files,
            interface=interface or "unknown",
            usage_info=usage_info
        )
    
    def _parse_rom_element(self, rom_elem) -> Optional[ROMFile]:
        """Parse a <rom> element."""
        name = rom_elem.get('name')
        size_str = rom_elem.get('size')
        crc = rom_elem.get('crc')
        sha1 = rom_elem.get('sha1')
        
        if not all([name, size_str, crc, sha1]):
            self.logger.debug(f"ROM element missing required attributes: {ET.tostring(rom_elem, encoding='unicode')}")
            return None
        
        try:
            size = int(size_str)
        except ValueError:
            self.logger.warning(f"Invalid size '{size_str}' for ROM '{name}'")
            return None
        
        return ROMFile(
            name=name,
            size=size,
            crc=crc,
            sha1=sha1
        )
    
    def filter_entries(
        self,
        entries: List[SoftwareEntry],
        publishers: Optional[List[str]] = None,
        exclude_unsupported: bool = False,
        year_range: Optional[tuple] = None
    ) -> List[SoftwareEntry]:
        """
        Filter software entries based on criteria.
        
        Args:
            entries: List of software entries
            publishers: Only include entries from these publishers
            exclude_unsupported: Skip entries with supported="no"
            year_range: Tuple of (min_year, max_year)
            
        Returns:
            Filtered list of entries
        """
        filtered = entries
        
        if exclude_unsupported:
            filtered = [e for e in filtered if e.supported]
            self.logger.info(f"Filtered out unsupported entries: {len(entries)} -> {len(filtered)}")
        
        if publishers:
            filtered = [e for e in filtered if e.publisher and e.publisher in publishers]
            self.logger.info(f"Filtered by publisher: {len(entries)} -> {len(filtered)}")
        
        if year_range:
            min_year, max_year = year_range
            filtered = [
                e for e in filtered
                if e.year and e.year.isdigit() and min_year <= int(e.year) <= max_year
            ]
            self.logger.info(f"Filtered by year range {year_range}: {len(entries)} -> {len(filtered)}")
        
        return filtered
