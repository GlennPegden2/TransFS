"""
Filename parsing for metadata extraction.

Supports common ROM naming conventions like No-Intro, TOSEC, GoodTools.
"""
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ParsedFilename:
    """Result of filename parsing."""
    title: str
    region: Optional[str] = None
    language: Optional[str] = None
    version: Optional[str] = None
    year: Optional[int] = None
    publisher: Optional[str] = None
    is_prototype: bool = False
    is_homebrew: bool = False
    is_translation: bool = False
    is_hack: bool = False
    is_demo: bool = False
    is_beta: bool = False
    is_sample: bool = False
    tags: List[str] = None
    raw_tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.raw_tags is None:
            self.raw_tags = []


class FilenameParser:
    """Parse ROM filenames to extract metadata."""
    
    # Common region codes
    REGIONS = {
        'USA': 'USA',
        'US': 'USA',
        'Europe': 'Europe',
        'EU': 'Europe',
        'Japan': 'Japan',
        'JP': 'Japan',
        'JPN': 'Japan',
        'World': 'World',
        'UK': 'United Kingdom',
        'Germany': 'Germany',
        'DE': 'Germany',
        'France': 'France',
        'FR': 'France',
        'Spain': 'Spain',
        'ES': 'Spain',
        'Italy': 'Italy',
        'IT': 'Italy',
        'Australia': 'Australia',
        'AU': 'Australia',
        'Canada': 'Canada',
        'CA': 'Canada',
        'Korea': 'Korea',
        'KR': 'Korea',
        'China': 'China',
        'CN': 'China',
        'Brazil': 'Brazil',
        'BR': 'Brazil',
        'Netherlands': 'Netherlands',
        'NL': 'Netherlands',
        'Sweden': 'Sweden',
        'SE': 'Sweden',
    }
    
    # Language codes
    LANGUAGES = {
        'En': 'English',
        'English': 'English',
        'Ja': 'Japanese',
        'Japanese': 'Japanese',
        'Fr': 'French',
        'French': 'French',
        'De': 'German',
        'German': 'German',
        'Es': 'Spanish',
        'Spanish': 'Spanish',
        'It': 'Italian',
        'Italian': 'Italian',
        'Pt': 'Portuguese',
        'Portuguese': 'Portuguese',
        'Nl': 'Dutch',
        'Dutch': 'Dutch',
        'Sv': 'Swedish',
        'Swedish': 'Swedish',
        'No': 'Norwegian',
        'Norwegian': 'Norwegian',
        'Da': 'Danish',
        'Danish': 'Danish',
        'Fi': 'Finnish',
        'Finnish': 'Finnish',
        'Ko': 'Korean',
        'Korean': 'Korean',
        'Zh': 'Chinese',
        'Chinese': 'Chinese',
    }
    
    # Status flags
    STATUS_FLAGS = {
        'Proto': 'is_prototype',
        'Prototype': 'is_prototype',
        'Beta': 'is_beta',
        'Alpha': 'is_beta',
        'Demo': 'is_demo',
        'Sample': 'is_sample',
        'Unl': 'is_homebrew',
        'Unlicensed': 'is_homebrew',
        'Homebrew': 'is_homebrew',
        'Hack': 'is_hack',
        'Alt': 'is_hack',
    }

    DATE_TAG_PATTERNS = [
        re.compile(r'^(19\d{2}|20\d{2})$'),
        re.compile(r'^(19\d{2}|20\d{2})[-.](0[1-9]|1[0-2])$'),
        re.compile(r'^(19\d{2}|20\d{2})[-.](0[1-9]|1[0-2])[-.](0[1-9]|[12]\d|3[01])$'),
        re.compile(r'^(0[1-9]|1[0-2])[-.](0[1-9]|[12]\d|3[01]|XX)[-.](19\d{2}|20\d{2})$', re.IGNORECASE),
        re.compile(r'^(0[1-9]|1[0-2])[-.](19\d{2}|20\d{2})$'),
    ]

    PUBLISHER_IGNORE_PATTERNS = [
        re.compile(r'^Prototype$', re.IGNORECASE),
        re.compile(r'^CX\d+.*$', re.IGNORECASE),
        re.compile(r'^MT\d+.*$', re.IGNORECASE),
        re.compile(r'^DA\d+.*$', re.IGNORECASE),
    ]
    
    # Translation patterns
    TRANSLATION_PATTERNS = [
        r'\[T[-+]',  # [T-Eng], [T+Fre]
        r'\[tr',  # [tr es]
        r'\(T-',  # (T-English)
    ]
    
    def parse(self, filename: str) -> ParsedFilename:
        """
        Parse filename to extract metadata.
        
        Args:
            filename: Filename to parse (without path)
        
        Returns:
            ParsedFilename with extracted metadata
        """
        # Remove extension
        name_without_ext = filename.rsplit('.', 1)[0]
        
        # Extract tags in parentheses and brackets (preserve order)
        tag_matches = list(re.finditer(r'(\(|\[)([^)\]]+)(\)|\])', name_without_ext))
        all_tags = [match.group(2) for match in tag_matches]
        
        # Remove tags from title to get clean name
        clean_name = re.sub(r'\([^)]+\)', '', name_without_ext)
        clean_name = re.sub(r'\[([^\]]+)\]', '', clean_name)
        clean_name = clean_name.strip()
        
        title_override, publisher_from_date = self._extract_title_and_publisher_from_date_tag(
            name_without_ext,
            tag_matches,
        )

        result = ParsedFilename(
            title=title_override or clean_name,
            raw_tags=all_tags,
        )

        if publisher_from_date:
            result.publisher = publisher_from_date
            result.tags.append(f"Publisher:{publisher_from_date}")
        
        # Parse each tag
        for tag in all_tags:
            self._parse_tag(tag, result)

        if result.publisher is None:
            publisher_from_tags = self._extract_publisher_from_remaining_tags(all_tags)
            if publisher_from_tags:
                result.publisher = publisher_from_tags
                result.tags.append(f"Publisher:{publisher_from_tags}")
        
        return result
    
    def _parse_tag(self, tag: str, result: ParsedFilename):
        """Parse individual tag and update result."""
        tag_clean = tag.strip()

        region_override = self._parse_special_region(tag_clean)
        if region_override:
            result.region = region_override
            result.tags.append(f"Region:{region_override}")
            return
        
        # Check for region
        for region_code, region_name in self.REGIONS.items():
            if region_code in tag_clean.split(','):
                result.region = region_name
                result.tags.append(f"Region:{region_name}")
                break
        
        # Check for language(s)
        # Format: (En,Fr) or (English)
        languages_found = []
        for lang_parts in tag_clean.split(','):
            lang = lang_parts.strip()
            if lang in self.LANGUAGES:
                languages_found.append(self.LANGUAGES[lang])
        
        if languages_found:
            result.language = ', '.join(languages_found)
            for lang in languages_found:
                result.tags.append(f"Language:{lang}")
        
        # Check for status flags
        for flag_text, flag_field in self.STATUS_FLAGS.items():
            if flag_text.lower() in tag_clean.lower():
                setattr(result, flag_field, True)
                result.tags.append(flag_text)
        
        # Check for translation
        for pattern in self.TRANSLATION_PATTERNS:
            if re.search(pattern, tag, re.IGNORECASE):
                result.is_translation = True
                result.tags.append('Translation')
                break
        
        # Check for version (v1.0, Rev 1, etc.)
        version_match = re.search(r'(v|ver|version|rev|revision)\s*[\d.]+', tag_clean, re.IGNORECASE)
        if version_match:
            result.version = version_match.group(0)
            result.tags.append(f"Version:{result.version}")
        
        # Check for year (19xx, 20xx)
        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', tag_clean)
        if year_match:
            result.year = int(year_match.group(1))
            result.tags.append(f"Year:{result.year}")
        
        # Add generic tag if not already categorized
        if not any([
            result.region and tag_clean in self.REGIONS,
            any(lang in tag_clean for lang in self.LANGUAGES),
            any(flag in tag_clean for flag in self.STATUS_FLAGS),
            version_match,
            year_match,
        ]):
            result.tags.append(tag_clean)

    def _parse_special_region(self, tag_clean: str) -> Optional[str]:
        if tag_clean.upper() in {"PAL", "SECAM", "SECOM"}:
            return "SECAM" if tag_clean.upper() == "SECOM" else tag_clean.upper()
        return None

    def _is_date_or_year_tag(self, tag_clean: str) -> bool:
        return any(pattern.match(tag_clean) for pattern in self.DATE_TAG_PATTERNS)

    def _extract_title_and_publisher_from_date_tag(
        self,
        name_without_ext: str,
        tag_matches: List[re.Match],
    ) -> tuple[Optional[str], Optional[str]]:
        for index, match in enumerate(tag_matches):
            tag_clean = match.group(2).strip()
            if self._is_date_or_year_tag(tag_clean):
                title_prefix = name_without_ext[:match.start()].strip().rstrip("-_").strip()
                publisher = None
                if index + 1 < len(tag_matches):
                    publisher = self._publisher_from_tag(tag_matches[index + 1].group(2))
                return title_prefix or None, publisher
        return None, None

    def _publisher_from_tag(self, tag_clean: str) -> Optional[str]:
        tag_clean = tag_clean.strip()
        if not tag_clean:
            return None
        if ',' in tag_clean:
            return tag_clean.split(',', 1)[0].strip() or None
        return tag_clean or None

    def _extract_publisher_from_remaining_tags(self, tags: List[str]) -> Optional[str]:
        remaining = []
        for tag in tags:
            tag_clean = tag.strip()
            if not tag_clean:
                continue
            if self._is_date_or_year_tag(tag_clean):
                continue
            if any(pattern.match(tag_clean) for pattern in self.PUBLISHER_IGNORE_PATTERNS):
                continue
            remaining.append(tag_clean)

        if len(remaining) == 1:
            return self._publisher_from_tag(remaining[0])
        return None
    
    def parse_to_dict(self, filename: str) -> Dict[str, Any]:
        """
        Parse filename and return as dictionary.
        
        Args:
            filename: Filename to parse
        
        Returns:
            Dictionary of metadata fields
        """
        parsed = self.parse(filename)
        return {
            'title': parsed.title,
            'region': parsed.region,
            'language': parsed.language,
            'version': parsed.version,
            'year': parsed.year,
            'publisher': parsed.publisher,
            'is_prototype': parsed.is_prototype,
            'is_homebrew': parsed.is_homebrew,
            'is_translation': parsed.is_translation,
            'is_hack': parsed.is_hack,
            'is_demo': parsed.is_demo,
            'is_beta': parsed.is_beta,
            'is_sample': parsed.is_sample,
            'tags': parsed.tags,
            'raw_tags': parsed.raw_tags,
        }


# Global parser instance
_parser = FilenameParser()


def parse_filename(filename: str) -> ParsedFilename:
    """
    Convenience function to parse a filename.
    
    Args:
        filename: Filename to parse
    
    Returns:
        ParsedFilename with extracted metadata
    """
    return _parser.parse(filename)
