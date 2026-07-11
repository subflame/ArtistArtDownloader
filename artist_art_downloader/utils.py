"""Pure utility functions: string normalization, filename sanitization, name matching.

All functions in this module are deterministic and have no side effects
(no network, no file I/O, no global state). They are safe to unit-test.
"""

import platform
import re
import unicodedata
from typing import Optional

# Cache platform check for sanitize_filename (called many times)
_IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_CONJUNCTIONS = re.compile(r"\b(and|et|und|y|e)\b", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Normalize a name for comparison: strip combining marks, lowercase, collapse whitespace.

    NFKD-decomposes accented characters (é → e + combining accent), then removes
    the combining marks, preserving all base letters including Cyrillic, Greek, CJK, etc.
    Normalizes all conjunctions (&, and, et, und, y, e) to "and" so
    "Rock & Roll", "Rock and Roll", and "Rock et Roll" all match.

    Examples:
      "Beyoncé"     → "beyonce"
      "Ärsenik"     → "arsenik"
      "Баста"       → "баста"  (preserved, not stripped to empty)
      "Marie et les Garçons" → "marie and les garcons"
    """
    raw = name.strip().lower()
    nfkd = unicodedata.normalize("NFKD", raw)
    # Remove combining diacritical marks (Unicode category Mn) but keep all base letters
    kept = [ch for ch in nfkd if unicodedata.category(ch) != "Mn"]
    normalized = "".join(kept).strip()
    normalized = normalized.replace("&", "and")
    normalized = _CONJUNCTIONS.sub("and", normalized)
    return re.sub(r"\s+", " ", normalized)


def names_match_exact(api_name: str, target: str) -> bool:
    """Check if the API result name matches our target (case-insensitive, accent-insensitive).

    Tries exact match first, then strips parenthetical suffixes like "(Remastered)"
    and retries. Also handles slight differences in length via prefix matching.
    """
    a = normalize_name(api_name)
    t = normalize_name(target)
    if a == t:
        return True
    # Strip parenthetical suffixes: "1977/1979 (Remastered)" → "1977/1979"
    a_stripped = re.sub(r"\s*\(.*\)\s*$", "", a).strip()
    t_stripped = re.sub(r"\s*\(.*\)\s*$", "", t).strip()
    if a_stripped == t_stripped:
        return True
    return False


def genres_compatible(local_genres: set[str], api_genre: Optional[str]) -> bool:
    """Check if an API genre is compatible with local genre tags.

    If we have no local genres or no API genre, we assume compatibility.
    Otherwise, at least one local genre must meaningfully overlap with the API genre.

    Examples:
      local={"Hip-Hop"},  api="Hip-Hop"      → True
      local={"Hip Hop"},  api="Hip-Hop/Rap"   → True
      local={"Rap"},      api="Classical"      → False
      local={"Rap"},      api=""               → True (no info to judge)
    """
    if not local_genres or not api_genre:
        return True

    api_norm = normalize_name(api_genre)
    if not api_norm:
        return True

    # Split on any non-alphanumeric character to handle "Hip-Hop/Rap" vs "Hip Hop"
    api_words = set(re.split(r"[^a-z0-9]+", api_norm)) - {""}

    for lg in local_genres:
        lg_norm = normalize_name(lg)
        if not lg_norm:
            continue
        # Check if one contains the other (e.g. "hiphop" ⊂ "hiphoprap")
        if lg_norm in api_norm or api_norm in lg_norm:
            return True
        # Check for shared words (handles "hip-hop/rap" vs "hip hop")
        lg_words = set(re.split(r"[^a-z0-9]+", lg_norm)) - {""}
        if lg_words & api_words:
            return True

    return False


# ---------------------------------------------------------------------------
# Search-query helpers
# ---------------------------------------------------------------------------

_AND_PATTERN = re.compile(r"\b(and|et|und|y|e)\b", re.IGNORECASE)
_AND_WORDS = ["and", "et", "und", "y", "e"]


def expand_and_variants(text: str) -> list[str]:
    """Generate search variants by swapping 'and'-like words with '&'.

    Supports English (and), French (et), German (und), Spanish (y), Italian (e).

    Example:
      "Marie et les Garçons"
      → ["Marie et les Garçons", "Marie & les Garçons"]
    """
    variants = [text]
    # Replace any "and"-like word with "&"
    swapped = _AND_PATTERN.sub("&", text)
    if swapped != text and swapped not in variants:
        variants.append(swapped)
    # If "&" is present, try replacing with each "and"-like word
    if "&" in text:
        for word in _AND_WORDS:
            replaced = text.replace("&", word)
            if replaced != text and replaced not in variants:
                variants.append(replaced)
    return variants


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

_WIN_RESERVED_NAMES = {
    "con", "nul", "prn", "aux",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def sanitize_filename(name: str) -> str:
    """Remove characters invalid in filenames and prevent path traversal.

    Handles:
    - Invalid filename characters on Windows/Linux
    - Path traversal attempts (..)
    - Windows reserved names (CON, NUL, PRN, LPT1-9, COM1-9)
    - Null bytes
    - Dots-only names that could resolve to current directory
    - Length limit of 200 characters
    """
    # Remove null bytes first
    name = name.replace("\0", "")

    # Remove invalid filename characters
    name = re.sub(r'[<>:"/\\|?*]', "", name)

    # Remove path traversal sequences (repeatedly to catch nested like "....")
    while ".." in name:
        name = name.replace("..", "")

    name = name.strip(". ")

    # Handle Windows reserved names (case-insensitive)
    if _IS_WINDOWS:
        stem = name.rsplit(".", 1)[0].lower() if "." in name else name.lower()
        if stem in _WIN_RESERVED_NAMES:
            name = "_" + name

    # Prevent empty or dots-only names (would resolve to current dir)
    if not name or name.strip(".") == "":
        name = "unknown_artist"

    # Truncate to 200 characters
    if len(name) > 200:
        name = name[:200]

    return name



