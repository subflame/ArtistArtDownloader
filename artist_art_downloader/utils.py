"""Pure utility functions: string normalization, filename sanitization, name matching.

All functions in this module are deterministic and have no side effects
(no network, no file I/O, no global state). They are safe to unit-test.
"""

import platform
import re
import unicodedata
from pathlib import Path
from typing import Optional

# Cache platform check for sanitize_filename (called many times)
_IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_CONJUNCTIONS = re.compile(r"\b(and|et|und|y|e)\b", re.IGNORECASE)

# Traditional -> Simplified Chinese mapping for common artist name characters.
# Apple Music uses traditional Chinese; most other sources use simplified.
_TRAD_TO_SIMP = str.maketrans({
    "\u5075": "\u4f26",  # 倫 -> 伦
    "\u50b3": "\u4f20",  # 傳 -> 传
    "\u516a": "\u4f26",  # 倫 -> 伦 (alt)
    "\u8aaa": "\u8bf4",  # 說 -> 说
    "\u8b93": "\u8ba9",  # 讓 -> 让
    "\u958b": "\u5f00",  # 開 -> 开
    "\u96fb": "\u7535",  # 電 -> 电
    "\u6975": "\u6781",  # 極 -> 极
    "\u6a23": "\u6837",  # 樣 -> 样
    "\u5718": "\u56e2",  # 團 -> 团
    "\u8ecd": "\u519b",  # 軍 -> 军
    "\u96a3": "\u90bb",  # 鄰 -> 邻
    "\u9cf3": "\u51e4",  # 鳳 -> 凤
    "\u5bee": "\u697c",  # 樓 -> 楼
    "\u8ecd": "\u519b",  # 軍 -> 军
    "\u96f2": "\u4e91",  # 雲 -> 云
    "\u98a8": "\u98ce",  # 風 -> 风
    "\u611b": "\u7231",  # 愛 -> 爱
    "\u570b": "\u56fd",  # 國 -> 国
    "\u6703": "\u4f1a",  # 會 -> 会
    "\u8aaa": "\u8bf4",  # 說 -> 说
    "\u6a13": "\u697c",  # 樓 -> 楼
    "\u7d66": "\u7ed9",  # 給 -> 给
})


def normalize_name(name: str) -> str:
    """Normalize a name for comparison: strip combining marks, lowercase, collapse whitespace.

    NFKD-decomposes accented characters (e -> e + combining accent), then removes
    the combining marks, preserving all base letters including Cyrillic, Greek, CJK, etc.
    Normalizes all conjunctions (&, and, et, und, y, e) to "and" so
    "Rock & Roll", "Rock and Roll", and "Rock et Roll" all match.
    Converts traditional Chinese to simplified for consistent comparison.

    Examples:
      "Beyonce"     -> "beyonce"
      "Arsenik"     -> "arsenik"
      "周杰倫"       -> "周杰伦" (traditional -> simplified)
      "Marie et les Garcons" -> "marie and les garcons"
    """
    # Convert traditional Chinese to simplified first
    name = name.translate(_TRAD_TO_SIMP)
    raw = name.strip().lower()
    nfkd = unicodedata.normalize("NFKD", raw)
    # Remove combining diacritical marks (Unicode category Mn) but keep all base letters
    kept = [ch for ch in nfkd if unicodedata.category(ch) != "Mn"]
    normalized = "".join(kept).strip()
    normalized = normalized.replace("&", "and")
    normalized = _CONJUNCTIONS.sub("and", normalized)
    return re.sub(r"\s+", " ", normalized)


# Suffix patterns to strip for lenient name comparison.
# Applied in order; first match wins.
_SUFFIX_PATTERNS = [
    re.compile(r"\s*\(.*\)\s*$"),          # (Remastered), (Deluxe Edition)
    re.compile(r"\s*\[.*\]\s*$"),          # [Deluxe], [Remastered 2024]
    re.compile(r"\s+(?:feat|ft)\.\s.*$", re.I),  # feat. Someone, ft. Guest
    re.compile(r"\s+featuring\s.*$", re.I),    # featuring Someone
    re.compile(r"\s*[\-\u2013\u2014]\s*(?:remaster(?:ed)?|deluxe|explicit|clean|radio\s*edit|extended|bonus\s*track|remix|acoustic|live|instrumental|special\s*edition|anniversary\s*edition|expanded)\b.*$", re.I),
    re.compile(r"\s+[\-\u2013\u2014]\s*\d{4}\s*$"),  # - 2024, - 2023
]


def _strip_suffixes(name: str) -> str:
    """Strip common suffixes from a normalized name for comparison.

    Tries each suffix pattern in order and returns the first stripped version.
    If no pattern matches, returns the original.
    """
    for pat in _SUFFIX_PATTERNS:
        stripped = pat.sub("", name).strip()
        if stripped != name:
            return stripped
    return name


def transliterate_to_latin(text: str) -> str:
    """Transliterate non-Latin scripts (Cyrillic, CJK, Kana, Hangul) to Latin ASCII.

    Uses the same transliteration maps as _slugify but returns plain text
    (no slug formatting). Used for cross-script name comparison.

    Korean syllables (U+AC00-D7AF) are decomposed to Jamo before
    transliteration so the HANGUL_MAP can match them.
    Traditional Chinese is converted to simplified first.
    """
    from .translit_maps import ALL_MULTI_SEQUENCES, ALL_TRANSLIT_MAPS
    # Convert traditional Chinese to simplified first
    text = text.translate(_TRAD_TO_SIMP)
    text = text.lower().strip()
    # Decompose ONLY Korean syllables to Jamo (not full NFD which breaks Katakana)
    decomposed = []
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7AF:  # Hangul syllable block
            sindex = cp - 0xAC00
            l = chr(0x1100 + sindex // 588)
            v = chr(0x1161 + (sindex % 588) // 28)
            t = sindex % 28
            decomposed.append(l)
            decomposed.append(v)
            if t:
                decomposed.append(chr(0x11A7 + t))
        else:
            decomposed.append(ch)
    text = "".join(decomposed)
    # Apply multi-char replacements first
    for old, new in ALL_MULTI_SEQUENCES:
        text = text.replace(old, new)
    for m in ALL_TRANSLIT_MAPS:
        text = text.translate(m)
    # NFKD decompose Latin accents, then strip combining marks
    nfkd = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def names_match_exact(api_name: str, target: str) -> bool:
    """Check if the API result name matches our target (case-insensitive, accent-insensitive).

    Tries exact match first, then progressively strips suffixes from BOTH names:
    parenthetical (Remastered), bracket [Deluxe], dashes (- Remastered),
    collaboration markers (feat./ft./featuring), and version keywords.

    Also tries cross-script comparison via transliteration (e.g. "Kobukuro" vs
    Japanese characters, or Latin API name vs Cyrillic local name).
    """
    a = normalize_name(api_name)
    t = normalize_name(target)
    if a == t:
        return True
    # Strip common suffixes from both sides
    a_stripped = _strip_suffixes(a)
    t_stripped = _strip_suffixes(t)
    if a_stripped == t_stripped:
        return True
    # Strip suffixes from API name only (API often has extra info)
    if _strip_suffixes(a) == t:
        return True
    # Cross-script comparison: transliterate both names to Latin and compare
    # This handles cases like "Kobukuro" vs "コブクロ", "Кино" vs "Kino",
    # "Ruki Vverkh" vs "Руки Вверх", etc.
    a_translit = transliterate_to_latin(api_name)
    t_translit = transliterate_to_latin(target)
    if a_translit and t_translit and a_translit == t_translit:
        return True
    # Also try with suffix stripping on transliterated versions
    a_translit_stripped = _strip_suffixes(a_translit)
    t_translit_stripped = _strip_suffixes(t_translit)
    if a_translit_stripped == t_translit_stripped:
        return True
    if _strip_suffixes(a_translit) == t_translit:
        return True
    return False


def names_match_fuzzy(api_name: str, target: str) -> bool:
    """Fuzzy cross-script name match using transliteration + substring containment.

    Handles cases where romanizations differ but share significant characters:
    - "Jay Chou" vs "zhoujielun" -> no match (different names)
    - "Кино" vs "Kino" -> "kino" in "kino" -> True
    - "Bi-2" vs "Би-2" -> "bi-2" in "bi-2" -> True
    - "Кино" vs "Chyernoje Kino" -> "kino" in "chyernoje kino" -> True

    Returns True if the transliterated shorter name is fully contained in the
    longer transliterated name (after stripping accents and normalizing).
    """
    a = transliterate_to_latin(api_name)
    t = transliterate_to_latin(target)
    if not a or not t:
        return False
    # Normalize whitespace
    a = re.sub(r"\s+", " ", a).strip()
    t = re.sub(r"\s+", " ", t).strip()
    # Check containment (shorter in longer)
    shorter, longer = (a, t) if len(a) <= len(t) else (t, a)
    if not shorter:
        return False
    # For very short names (< 4 chars), require exact match to avoid false positives
    if len(shorter) < 4:
        return shorter == longer
    return shorter in longer


def genres_compatible(local_genres: set[str], api_genre: Optional[str]) -> bool:
    """Check if an API genre is compatible with local genre tags.

    If we have no local genres or no API genre, we assume compatibility.
    Otherwise, at least one local genre must meaningfully overlap with the API genre.

    Examples:
      local={"Hip-Hop"},  api="Hip-Hop"      -> True
      local={"Hip Hop"},  api="Hip-Hop/Rap"   -> True
      local={"Rap"},      api="Classical"      -> False
      local={"Rap"},      api=""               -> True (no info to judge)
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
        # Check if one contains the other (e.g. "hiphop" ? "hiphoprap")
        if lg_norm in api_norm or api_norm in lg_norm:
            return True
        # Check for shared words (handles "hip-hop/rap" vs "hip hop")
        lg_words = set(re.split(r"[^a-z0-9]+", lg_norm)) - {""}
        if lg_words & api_words:
            return True

    return False


# ---------------------------------------------------------------------------
# Accent stripping
# ---------------------------------------------------------------------------

def strip_accents(text: str) -> str:
    """Remove combining diacritical marks from text, preserving base letters.

    Uses NFKD decomposition: 'e' -> 'e' + combining acute, then removes
    all Unicode category Mn (Non-spacing Mark) characters.

    Examples:
      "Roger Fakhr"  -> "Roger Fakhr"
      "Beyonce"      -> "Beyonce"
      "Arsenik"      -> "Arsenik"
      "?????"        -> "?????"  (Cyrillic has no combining marks, preserved)
      "Marie et les Garcons" -> "Marie et les Garcons"
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


# ---------------------------------------------------------------------------
# Search-query helpers
# ---------------------------------------------------------------------------

_AND_PATTERN = re.compile(r"\b(and|et|und|y|e)\b", re.IGNORECASE)
_AND_WORDS = ["and", "et", "und", "y", "e"]


def add_accent_variants(text: str) -> list[str]:
    """Generate accent-adding variants for API search queries.

    When the local file has 'Roger Fakhr' (no accent) but the streaming service
    stores it as 'Roger Fakhr', a plain search for 'Roger Fakhr' may return
    zero results. This function creates variants with common diacritical marks
    added, so at least one variant may match the streaming service's spelling.

    Strategy: for each word, try adding the single most common accent variant
    to EACH vowel position individually. Output is capped at 5 extra variants
    to avoid excessive API requests.

    Example:
      "Roger Fakhr"  ->  ["Roger Fakhr", "Roger Fakhr", "Roger Fakhr", ...]
      "Ultravox"      ->  ["Ultravox", "Ultravox", "Ultravox", "Ultravox"]
    """
    # Only the single most common accent per vowel to keep API load low.
    # e is by far the most common in artist names (French/Spanish/Portuguese).
    _ACCENT_MAP = {
        'a': ['a'],
        'e': ['e'],
        'i': ['i'],
        'o': ['o'],   # o covers German/Nordic (Motley, Bjork)
        'u': ['u'],   # u covers German/Turkish
        'c': ['c'],   # c covers French/Turkish (Francois)
        'n': ['n'],   # n covers Spanish (Pena)
    }

    words = text.split()
    if not words:
        return [text]

    results = [text]
    _MAX_EXTRA = 5  # hard cap on extra variants

    # For each word, try accenting EACH vowel position individually
    for word_idx, word in enumerate(words):
        for i, ch in enumerate(word):
            key = ch.lower()
            if key not in _ACCENT_MAP:
                continue
            if len(results) - 1 >= _MAX_EXTRA:
                break

            accented = _ACCENT_MAP[key][0]
            # Match case: if original is uppercase, make accented char uppercase
            acc_char = accented.upper() if ch.isupper() else accented

            new_word = word[:i] + acc_char + word[i + 1:]
            new_words = list(words)
            new_words[word_idx] = new_word
            variant = " ".join(new_words)
            if variant not in results:
                results.append(variant)
        if len(results) - 1 >= _MAX_EXTRA:
            break

    return results


def expand_and_variants(text: str) -> list[str]:
    """Generate search variants by swapping 'and'-like words with '&',
    stripping accents, AND adding accent variants.

    Supports English (and), French (et), German (und), Spanish (y), Italian (e).
    Generates:
    - Accent-stripped variant (e.g. "Roger Fakhr" -> "Roger Fakhr")
    - Accent-adding variants for short text ?3 words (e.g. "Roger Fakhr" -> "Roger Fakhr", ...)
    - &-swap variants for all the above
    - Transliterated Latin variant for non-Latin scripts (e.g. katakana -> romaji)

    Accent-adding is limited to short text (?3 words) to avoid combinatorial
    explosion on combined queries like "Album Name Artist Name" (4+ words).
    For combined queries, accent stripping and &-swap are sufficient because
    the album/track name provides enough context for the API to find results,
    and names_match_exact() handles accent-insensitive result filtering.

    Example:
      "Roger Fakhr"       -> ["Roger Fakhr", "Roger Fakhr", "Roger Fakhr", ...]
      "Roger Fakhr"       -> ["Roger Fakhr", "Roger Fakhr", ...]
      "Album Roger Fakhr" -> ["Album Roger Fakhr", "Album Roger Fakhr", ...]  (?3 words, accents applied)
      "Long Album Name Roger Fakhr" -> stripped + &-swap only (no accent adding)
    """
    variants = [text]
    # Accent-stripped variant
    stripped = strip_accents(text)
    if stripped != text and stripped not in variants:
        variants.append(stripped)
    # Accent-adding variants: only for short text (?3 words) to avoid explosion
    # For combined album+artist queries (4+ words), the album/track context
    # provides enough signal for the API, and names_match_exact handles filtering.
    word_count = len(text.split())
    if word_count <= 3:
        for v in add_accent_variants(text):
            if v not in variants:
                variants.append(v)
        # Also add accent variants of the stripped version (no-op if same)
        if stripped != text:
            for v in add_accent_variants(stripped):
                if v not in variants:
                    variants.append(v)
    # Replace any "and"-like word with "&"
    for base in list(variants):  # iterate over copy since we append
        swapped = _AND_PATTERN.sub("&", base)
        if swapped != base and swapped not in variants:
            variants.append(swapped)
    # If "&" is present, try replacing with each "and"-like word
    if "&" in text:
        for word in _AND_WORDS:
            replaced = text.replace("&", word)
            if replaced != text and replaced not in variants:
                variants.append(replaced)
    # Transliterated Latin variant for non-Latin scripts (e.g. katakana -> romaji)
    # This ensures API search queries are in Latin script which APIs understand
    if any(ord(c) > 0x7E for c in text):
        translit = transliterate_to_latin(text)
        if translit and translit not in variants:
            variants.append(translit)
    # Hard cap: never return more than 8 variants to avoid API flooding
    return variants[:8]


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
