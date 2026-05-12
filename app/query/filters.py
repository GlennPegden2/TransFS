"""
Filter building for metadata queries.
"""
from typing import List, Tuple, Optional


class FilterBuilder:
    """Builds SQL WHERE clauses from filter criteria."""
    
    @staticmethod
    def build_region_filter(regions: List[str]) -> Tuple[str, List]:
        """
        Build filter for region(s).
        
        Args:
            regions: List of region codes (USA, Europe, etc.)
        
        Returns:
            (where_clause, parameters) tuple
        """
        if not regions:
            return ("", [])
        
        if len(regions) == 1:
            return ("m.region = ?", [regions[0]])
        
        placeholders = ", ".join(["?"] * len(regions))
        return (f"m.region IN ({placeholders})", regions)
    
    @staticmethod
    def build_language_filter(languages: List[str]) -> Tuple[str, List]:
        """
        Build filter for language(s).
        
        Args:
            languages: List of language codes (En, Ja, etc.)
        
        Returns:
            (where_clause, parameters) tuple
        """
        if not languages:
            return ("", [])
        
        if len(languages) == 1:
            return ("m.language = ?", [languages[0]])
        
        placeholders = ", ".join(["?"] * len(languages))
        return (f"m.language IN ({placeholders})", languages)
    
    @staticmethod
    def build_year_filter(min_year: Optional[int] = None, 
                         max_year: Optional[int] = None) -> Tuple[str, List]:
        """
        Build filter for year range.
        
        Args:
            min_year: Minimum year (inclusive)
            max_year: Maximum year (inclusive)
        
        Returns:
            (where_clause, parameters) tuple
        """
        clauses = []
        params = []
        
        if min_year is not None:
            clauses.append("m.year >= ?")
            params.append(min_year)
        
        if max_year is not None:
            clauses.append("m.year <= ?")
            params.append(max_year)
        
        if not clauses:
            return ("", [])
        
        return (" AND ".join(clauses), params)
    
    @staticmethod
    def build_genre_filter(genres: List[str]) -> Tuple[str, List]:
        """
        Build filter for genre(s).
        
        Args:
            genres: List of genres
        
        Returns:
            (where_clause, parameters) tuple
        """
        if not genres:
            return ("", [])
        
        if len(genres) == 1:
            return ("m.genre = ?", [genres[0]])
        
        placeholders = ", ".join(["?"] * len(genres))
        return (f"m.genre IN ({placeholders})", genres)
    
    @staticmethod
    def build_status_filter(is_prototype: Optional[bool] = None,
                          is_homebrew: Optional[bool] = None,
                          is_translation: Optional[bool] = None,
                          is_hack: Optional[bool] = None) -> Tuple[str, List]:
        """
        Build filter for status flags.
        
        Args:
            is_prototype: Filter prototype status
            is_homebrew: Filter homebrew status
            is_translation: Filter translation status
            is_hack: Filter hack status
        
        Returns:
            (where_clause, parameters) tuple
        """
        clauses = []
        params = []
        
        if is_prototype is not None:
            clauses.append("m.is_prototype = ?")
            params.append(1 if is_prototype else 0)
        
        if is_homebrew is not None:
            clauses.append("m.is_homebrew = ?")
            params.append(1 if is_homebrew else 0)
        
        if is_translation is not None:
            clauses.append("m.is_translation = ?")
            params.append(1 if is_translation else 0)
        
        if is_hack is not None:
            clauses.append("m.is_hack = ?")
            params.append(1 if is_hack else 0)
        
        if not clauses:
            return ("", [])
        
        return (" AND ".join(clauses), params)
    
    @staticmethod
    def combine_filters(*filters: Tuple[str, List]) -> Tuple[str, List]:
        """
        Combine multiple filters with AND.
        
        Args:
            *filters: Variable number of (where_clause, parameters) tuples
        
        Returns:
            Combined (where_clause, parameters) tuple
        """
        clauses = []
        all_params = []
        
        for clause, params in filters:
            if clause:
                clauses.append(clause)
                all_params.extend(params)
        
        if not clauses:
            return ("", [])
        
        return (" AND ".join(clauses), all_params)
