"""Box set detection utilities for identifying movie/TV collections."""

import re

# Patterns that indicate a box set rather than an individual movie
BOX_SET_PATTERNS: list[str] = [
    # Collection patterns
    r"\b\d+[-–]?Movie\s+Collection\b",  # "4-Movie Collection", "4 Movie Collection"
    r"\b\d+[-–]?Film\s+Collection\b",  # "5-Film Collection"
    r"\bCollection\b.*\(\d+\s*disc\)",  # "Collection (5 disc)"
    # Complete series/collection
    r"\bComplete\s+Series\b",
    r"\bComplete\s+Collection\b",
    r"\bThe\s+Complete\s+Collection\b",
    r"\bComplete\s+Seasons?\b",
    r"\bComplete\s+Box\b",
    # Season ranges (TV box sets)
    r"\bSeason\s+\d+\s*[-–]\s*\d+\b",  # "Season 1-6", "Season 1 - 6"
    r"\bSeasons?\s+\d+\s*[-–&]\s*\d+\b",  # "Seasons 1 & 2", "Seasons 1-3"
    r"\bS\d+\s*[-–]\s*S?\d+\b",  # "S1-S6", "S1-6"
    # Finnish patterns
    r"\b[Kk]aude[t]?\s+\d+\s*[-–]\s*\d+\b",  # "kaudet 1-3", "Kaudet 1-5"
    r"\b[Kk]ausi\s+\d+\s*[-–]\s*\d+\b",  # "kausi 1-3"
    r"\bComplete\s+Box\s+[Kk]ausi\b",  # "Complete Box Kausi 1-5"
    # High disc counts (strong indicator of box set)
    r"\(\s*[5-9]\s*disc\s*\)",  # (5 disc) to (9 disc)
    r"\(\s*[1-9]\d+\s*disc\s*\)",  # (10+ disc)
    # Named sets
    r"\bTrilogy\b",
    r"\bQuadrilogy\b",
    r"\bPentalogy\b",
    r"\bAnthology\b",
    r"\bSaga\s+Collection\b",
    r"\bBox\s*Set\b",
    # Specific patterns
    r"\b\d+\s*Movies?\s+in\s+\d+\b",  # "10 Movies in 1"
    r"\b\d+[-–]Pack\b",  # "6-Pack"
]

# Compiled patterns for performance
_COMPILED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern, re.IGNORECASE) for pattern in BOX_SET_PATTERNS
]


def is_box_set(title: str) -> bool:
    """Detect if a title represents a box set.

    Args:
        title: The product title to check

    Returns:
        True if the title matches box set patterns, False otherwise
    """
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(title):
            return True
    return False
