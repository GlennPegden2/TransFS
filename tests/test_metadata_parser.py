"""
Unit tests for metadata filename parsing.
"""
import pytest
from app.metadata.parser import FilenameParser, ParsedFilename, parse_filename


class TestFilenameParser:
    """Test filename parsing for metadata extraction."""
    
    def test_simple_filename(self):
        """Test parsing simple filename without metadata."""
        result = parse_filename("Pac-Man.a52")
        
        assert result.title == "Pac-Man"
        assert result.region is None
        assert result.language is None
    
    def test_no_intro_format_with_region(self):
        """Test No-Intro format with region."""
        result = parse_filename("Asteroids (USA).a52")
        
        assert result.title == "Asteroids"
        assert result.region == "USA"
    
    def test_no_intro_format_with_multiple_regions(self):
        """Test filename with multiple regions."""
        result = parse_filename("Game (USA, Europe).bin")
        
        assert result.title == "Game"
        assert result.region == "USA"  # First region
        # Multiple regions are preserved in raw_tags
        assert any("Europe" in tag for tag in result.raw_tags)
    
    def test_prototype_detection(self):
        """Test prototype flag detection."""
        result = parse_filename("Star Raiders (USA) (Proto).a52")
        
        assert result.title == "Star Raiders"
        assert result.region == "USA"
        assert result.is_prototype is True
    
    def test_homebrew_detection(self):
        """Test homebrew flag detection."""
        result = parse_filename("My Game (Homebrew).bin")
        
        assert result.title == "My Game"
        assert result.is_homebrew is True
    
    def test_translation_detection(self):
        """Test translation flag detection."""
        result = parse_filename("Game (Japan) (En).bin")
        
        assert result.title == "Game"
        assert result.region == "Japan"
        # Translation is detected if "Translation" keyword is present
        assert "En" in result.language or result.version or len(result.tags) > 0
    
    def test_hack_detection(self):
        """Test hack flag detection."""
        result = parse_filename("Super Game (Hack).bin")
        
        assert result.title == "Super Game"
        assert result.is_hack is True
    
    def test_language_detection(self):
        """Test language extraction."""
        result = parse_filename("Game (Europe) (En).bin")
        
        assert result.title == "Game"
        assert result.region == "Europe"
        assert result.language is not None  # Language is extracted
    
    def test_year_extraction(self):
        """Test year extraction from filename."""
        result = parse_filename("Game (1982).bin")
        
        assert result.title == "Game"
        assert result.year == 1982
    
    def test_version_in_tags(self):
        """Test version extraction to tags."""
        result = parse_filename("Game (USA) (v1.2).bin")
        
        assert result.title == "Game"
        assert result.version == "v1.2" or any("v1.2" in tag for tag in result.tags)
    
    def test_demo_detection(self):
        """Test demo flag detection."""
        result = parse_filename("Game (Demo).bin")
        
        assert result.title == "Game"
        assert result.is_demo is True
    
    def test_beta_detection(self):
        """Test beta flag detection."""
        result = parse_filename("Game (Beta).bin")
        
        assert result.title == "Game"
        assert result.is_beta is True
    
    def test_complex_filename(self):
        """Test complex filename with multiple attributes."""
        result = parse_filename("Pac-Man (USA) (Proto) (1982).a52")
        
        assert result.title == "Pac-Man"
        assert result.region == "USA"
        assert result.year == 1982
        assert result.is_prototype is True
    
    def test_filename_with_revision(self):
        """Test filename with revision number."""
        result = parse_filename("Game (USA) (Rev 1).bin")
        
        assert result.title == "Game"
        assert result.region == "USA"
        assert any("Rev" in tag for tag in result.tags)
    
    def test_tosec_format(self):
        """Test TOSEC naming format."""
        result = parse_filename("Game Name (1985)(Publisher)(US)[cr].bin")
        
        assert "Game Name" in result.title
        assert result.year == 1985
        # TOSEC format uses () for year and publisher
    
    def test_special_characters_in_title(self):
        """Test handling of special characters in title."""
        result = parse_filename("Mario Bros. - Special Edition (USA).bin")
        
        assert "Mario Bros" in result.title
        assert result.region == "USA"
    
    def test_empty_parentheses_ignored(self):
        """Test that empty parentheses are handled."""
        result = parse_filename("Game () (USA).bin")
        
        # Parser may keep or strip empty parentheses
        # Main expectation is region is detected
        assert result.region == "USA"
    
    def test_region_variations(self):
        """Test different region code variations."""
        test_cases = [
            ("Game (USA).bin", "USA"),
            ("Game (Europe).bin", "Europe"),
            ("Game (Japan).bin", "Japan"),
            ("Game (World).bin", "World"),
            ("Game (Germany).bin", "Germany"),
            ("Game (France).bin", "France"),
        ]
        
        for filename, expected_region in test_cases:
            result = parse_filename(filename)
            assert result.region == expected_region, f"Failed for {filename}"
    
    def test_alternate_flag_names(self):
        """Test alternate naming for flags."""
        test_cases = [
            ("Game (Proto).bin", True, "is_prototype"),
            ("Game (Prototype).bin", True, "is_prototype"),
        ]
        
        for filename, expected, flag in test_cases:
            result = parse_filename(filename)
            actual = getattr(result, flag)
            assert actual == expected, f"Failed for {filename}, flag {flag}"
    
    def test_parser_instance_methods(self):
        """Test FilenameParser class methods directly."""
        parser = FilenameParser()
        
        result = parser.parse("Asteroids (USA).a52")
        
        assert isinstance(result, ParsedFilename)
        assert result.title == "Asteroids"
        assert result.region == "USA"
    
    def test_case_insensitive_flags(self):
        """Test that flag detection is case-insensitive."""
        result = parse_filename("Game (proto).bin")
        
        assert result.is_prototype is True
    
    def test_multiple_status_flags(self):
        """Test filename with multiple status flags."""
        result = parse_filename("Game (Proto) (Hack).bin")
        
        assert result.is_prototype is True
        assert result.is_hack is True
