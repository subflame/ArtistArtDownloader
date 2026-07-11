"""Fetch artist images from Deezer and Apple Music APIs."""

import atexit
import io
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from PIL import Image as _PIL_Image

from .translit_maps import ALL_MULTI_SEQUENCES, ALL_TRANSLIT_MAPS
from .utils import (
    expand_and_variants,
    genres_compatible,
    names_match_exact,
    normalize_name,
    strip_accents,
)

DEEZER_SEARCH_URL = "https://api.deezer.com/search/artist"
DEEZER_ALBUM_SEARCH_URL = "https://api.deezer.com/search/album"
DEEZER_TRACK_SEARCH_URL = "https://api.deezer.com/search/track"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
APPLE_MUSIC_BASE_URL = "https://music.apple.com/us/artist"

# Per-type timeouts
TIMEOUT_SEARCH = 10
TIMEOUT_DEEZER_DETAIL = 5
TIMEOUT_APPLE_PAGE = 10
TIMEOUT_DOWNLOAD = 30

# Search limits (named constants instead of magic numbers)
_DEEZER_ARTIST_LIMIT = 10
_DEEZER_ALBUM_LIMIT = 10
_DEEZER_TRACK_LIMIT = 10
_ITUNES_ARTIST_LIMIT = 10
_ITUNES_ALBUM_LIMIT = 25
_ITUNES_TRACK_LIMIT = 25
_MAX_SEARCH_CANDIDATES = 8
_MAX_RETRIES = 3
_MAX_ALBUM_SEARCH = 5
_MAX_TRACK_SEARCH = 5

# Discography pagination
_DEEZER_ALBUM_PAGE_SIZE = 25
_ITUNES_LOOKUP_LIMIT = 200
_429_MAX_BACKOFF = 16  # seconds -- stop after this

# Image processing limits
_MAX_IMAGE_DIMENSION = 1500  # max width/height in px for downloaded images

# Common placeholder indicators in Deezer URLs
DEEZER_PLACEHOLDER_PATTERNS = (
    "15627e72e2e2be8e5f4a5e5e5e5e5e5e",
    "placeholder",
    "default",
)

# Reusable session with connection pooling
_SESSION = requests.Session()
atexit.register(_SESSION.close)

# Rate limiting: track last request time per host
_last_request_time: dict[str, float] = {}
_RATE_LIMIT_DELAY = 0.15  # seconds between requests to same host


def _rate_limit(url: str):
    """Ensure minimum delay between requests to the same host."""
    host = urlparse(url).netloc
    last = _last_request_time.get(host, 0.0)
    elapsed = time.time() - last
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time[host] = time.time()


def _is_deezer_placeholder(url: str) -> bool:
    """Check if a Deezer URL is a placeholder/default image."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in DEEZER_PLACEHOLDER_PATTERNS)


def _request_with_retry(method: str, url: str, max_retries: int = 3,
                        timeout: int = TIMEOUT_SEARCH, **kwargs) -> Optional[requests.Response]:
    """HTTP request with exponential backoff + jitter, retry on 429 and 5xx."""
    # Apply rate limiting
    _rate_limit(url)

    # Set random User-Agent header if not already set
    headers = kwargs.get("headers", {})
    if "User-Agent" not in headers:
        headers = dict(headers)
        headers["User-Agent"] = random.choice(_USER_AGENTS)
    kwargs["headers"] = headers

    for attempt in range(max_retries):
        try:
            resp = _SESSION.request(method, url, timeout=timeout, **kwargs)
            # Successful response — return immediately
            if resp.status_code < 400:
                return resp
            # Retry on 429 (Too Many Requests) and 5xx (server errors)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_retries - 1:
                    wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                    time.sleep(wait)
                    continue
                return resp
            # Non-retryable 4xx (400, 403, 404, etc.) — return immediately
            return resp
        except requests.RequestException:
            if attempt < max_retries - 1:
                wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            return None
    return None


def _get(url: str, **kwargs) -> Optional[requests.Response]:
    """Convenience GET wrapper with retry."""
    return _request_with_retry("GET", url, **kwargs)


def _find_artist_via_album(album_name: str, artist_name: str, year: str) -> Optional[int]:
    """Search iTunes by album+artist to find the correct artist ID.

    Searches WITHOUT year first (since the tag year might not match Apple Music),
    then retries WITH year if nothing found. Uses a larger result set (25) to
    handle slight formatting differences in album names.

    Single-pass: collects exact and lenient (word-sharing) artist matches,
    returns exact match first, falls back to lenient if no exact match.
    """
    base = f"{album_name} {artist_name}"
    queries = expand_and_variants(base)
    if year:
        for v in expand_and_variants(f"{album_name} {artist_name} {year}"):
            if v not in queries:
                queries.append(v)

    lenient_id = None
    for query in queries:
        try:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": query, "entity": "album", "limit": 25},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                continue
            for r in resp.json().get("results", []):
                rname = r.get("collectionName", "")
                rartist = r.get("artistName", "")
                if not names_match_exact(rname, album_name):
                    continue
                is_exact = names_match_exact(rartist, artist_name)
                if is_exact:
                    return r.get("artistId")
                # Collect lenient fallback
                if lenient_id is None and _artist_names_share_word(rartist, artist_name):
                    lenient_id = r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return lenient_id


def _find_artist_via_track(track_name: str, artist_name: str) -> Optional[int]:
    """Search iTunes by track+artist to find the correct artist ID.

    Uses song entity search -- the results include artistId directly.
    Single-pass: exact artist match first, lenient (word-sharing) as fallback.
    """
    base = f"{track_name} {artist_name}"
    queries = expand_and_variants(base)

    lenient_id = None
    for query in queries:
        try:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": query, "entity": "song", "limit": 25},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                continue
            for r in resp.json().get("results", []):
                rtrack = r.get("trackName", "")
                rartist = r.get("artistName", "")
                if not names_match_exact(rtrack, track_name):
                    continue
                is_exact = names_match_exact(rartist, artist_name)
                if is_exact:
                    return r.get("artistId")
                # Collect lenient fallback
                if lenient_id is None and _artist_names_share_word(rartist, artist_name):
                    lenient_id = r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return lenient_id


def _search_deezer_by_album(artist_name: str, album_name: str, year: str) -> Optional[str]:
    """Deezer: find artist image via album search (most precise).

    Single-pass: collects exact and lenient (word-sharing) artist matches,
    returns exact match first, falls back to lenient if no exact match.
    """
    album_queries = expand_and_variants(f"{album_name} {artist_name}")
    if year:
        for v in expand_and_variants(f"{album_name} {artist_name} {year}"):
            if v not in album_queries:
                album_queries.append(v)

    lenient_url = None
    seen_ids: set[int] = set()

    for query in album_queries:
        resp = _get(DEEZER_ALBUM_SEARCH_URL, params={"q": query, "limit": _DEEZER_ALBUM_LIMIT},
                    timeout=TIMEOUT_SEARCH)
        if resp is None or not resp.ok:
            continue
        for item in resp.json().get("data", []):
            if not names_match_exact(item.get("title", ""), album_name):
                continue
            item_artist = item.get("artist", {})
            api_name = item_artist.get("name", "")
            artist_id = item_artist.get("id")
            if not artist_id:
                continue

            is_exact = names_match_exact(api_name, artist_name)

            # Collect lenient fallback (no duplicates)
            if not is_exact and artist_id not in seen_ids:
                if _artist_names_share_word(api_name, artist_name):
                    seen_ids.add(artist_id)
                    if lenient_url is None:
                        detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                                      timeout=TIMEOUT_DEEZER_DETAIL)
                        if detail and detail.ok:
                            url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                            if url and not _is_deezer_placeholder(url):
                                lenient_url = url

            if not is_exact:
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return url

    return lenient_url


def _search_deezer_by_track(artist_name: str, track_name: str) -> Optional[str]:
    """Deezer: find artist image via track search.

    Single-pass: collects exact and lenient (word-sharing) artist matches,
    returns exact match first, falls back to lenient if no exact match.
    """
    track_queries = expand_and_variants(f"{track_name} {artist_name}")

    lenient_url = None
    seen_ids: set[int] = set()

    for query in track_queries:
        resp = _get(DEEZER_TRACK_SEARCH_URL, params={"q": query, "limit": _DEEZER_TRACK_LIMIT},
                    timeout=TIMEOUT_SEARCH)
        if resp is None or not resp.ok:
            continue
        for item in resp.json().get("data", []):
            if not names_match_exact(item.get("title", ""), track_name):
                continue
            item_artist = item.get("artist", {})
            api_name = item_artist.get("name", "")
            artist_id = item_artist.get("id")
            if not artist_id:
                continue

            is_exact = names_match_exact(api_name, artist_name)

            # Collect lenient fallback (no duplicates)
            if not is_exact and artist_id not in seen_ids:
                if _artist_names_share_word(api_name, artist_name):
                    seen_ids.add(artist_id)
                    if lenient_url is None:
                        detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                                      timeout=TIMEOUT_DEEZER_DETAIL)
                        if detail and detail.ok:
                            url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                            if url and not _is_deezer_placeholder(url):
                                lenient_url = url

            if not is_exact:
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return url

    return lenient_url


def _search_deezer_direct(artist_name: str, genres: set[str]) -> Optional[str]:
    """Deezer: direct artist search with genre filter.

    Tries the original name, accent-stripped, and accent-adding variants
    via expand_and_variants() to handle cases like:
    - Local 'Roger Fakhr' vs streaming 'Roger Fakhr' (missing accent)
    - Local 'Roger Fakhr' vs streaming 'Roger Fakhr' (extra accent)
    - Local 'Hamid El Shaeri' vs streaming 'Hamid Al-Shaeri' (transliteration)

    Two-pass strategy:
    1. Exact match (names_match_exact) -- preferred
    2. Lenient match (shares at least one word) -- fallback for transliteration diffs
    """
    # Use expand_and_variants for full bidirectional accent handling
    name_variants = expand_and_variants(artist_name)

    lenient_fallback_url = None  # best word-sharing match
    seen_lenient_ids: set[int] = set()

    for name_variant in name_variants:
        resp = _get(DEEZER_SEARCH_URL, params={"q": name_variant, "limit": _DEEZER_ARTIST_LIMIT},
                    timeout=TIMEOUT_SEARCH)
        if resp is None or not resp.ok:
            continue
        for item in resp.json().get("data", []):
            item_name = item.get("name", "")
            item_id = item.get("id")
            url = item.get("picture_xl") or item.get("picture_big")
            if not url or _is_deezer_placeholder(url):
                continue

            is_exact = names_match_exact(item_name, artist_name)

            # Collect lenient fallback (word-sharing) if not exact
            if not is_exact and item_id and item_id not in seen_lenient_ids:
                if _artist_names_share_word(item_name, artist_name):
                    seen_lenient_ids.add(item_id)
                    if lenient_fallback_url is None:
                        lenient_fallback_url = url

            if not is_exact:
                continue
            if genres:
                try:
                    detail = _get(f"https://api.deezer.com/artist/{item_id}",
                                  timeout=TIMEOUT_DEEZER_DETAIL)
                    if detail and detail.ok:
                        gid = detail.json().get("genre_id")
                        if gid:
                            genre_resp = _get(f"https://api.deezer.com/genre/{gid}",
                                              timeout=TIMEOUT_DEEZER_DETAIL)
                            if genre_resp and genre_resp.ok:
                                gname = genre_resp.json().get("name", "")
                                if genres_compatible(genres, gname):
                                    return url
                                continue
                except Exception:
                    pass
            else:
                # No genre filter -- accept first exact match
                return url

    # No exact match -- return lenient word-sharing fallback if available
    return lenient_fallback_url


def fetch_artist_image_deezer(artist_name: str, album_name: str = "",
                              year: str = "", genres: Optional[set[str]] = None,
                              track_name: str = "") -> Optional[str]:
    """Search Deezer for artist image URL (picture_xl).
    Uses album+year context + genre filtering for precise matching.
    
    Search order:
    1. Album+artist search (most precise)
    2. Track+artist search (if track provided)
    3. Direct artist name search with genre filter
    """
    if genres is None:
        genres = set()
    try:
        # Step 1: Try album+artist search
        if album_name:
            result = _search_deezer_by_album(artist_name, album_name, year)
            if result:
                return result
        # Step 2: Try track+artist search (even if album was provided but failed)
        if track_name:
            result = _search_deezer_by_track(artist_name, track_name)
            if result:
                return result
        # Step 3: Direct artist name search (last resort within Deezer)
        return _search_deezer_direct(artist_name, genres)
    except (requests.RequestException, ValueError):
        return None


def fetch_artist_image_itunes(artist_name: str, album_name: str = "",
                              year: str = "", genres: Optional[set[str]] = None,
                              track_name: str = "") -> Optional[str]:
    """Search iTunes/Apple Music for artist image.
    
    Search order: album -> track -> name (most->least specific).
    Each level respects genre filtering as a soft preference.
    """
    if genres is None:
        genres = set()
    rid = None
    slug = None

    # Strategy 1: find artist via album search (most precise)
    if album_name:
        artist_id = _find_artist_via_album(album_name, artist_name, year)
        if artist_id:
            rid = artist_id
            slug = _slugify(artist_name)

    # Strategy 2: find artist via track search
    if not rid and track_name:
        artist_id = _find_artist_via_track(track_name, artist_name)
        if artist_id:
            rid = artist_id
            slug = _slugify(artist_name)

    # Strategy 3: direct artist search (with soft genre filter)
    # Tries original name, accent-stripped, and accent-adding variants
    if not rid:
        # Use expand_and_variants for full bidirectional accent handling
        search_terms = expand_and_variants(artist_name)

        # Lenient fallback: if no exact match found, try word-sharing match
        lenient_fallback = None  # (rid, slug) from best word-sharing result

        for term in search_terms:
            try:
                resp = _get(
                    ITUNES_SEARCH_URL,
                    params={"term": term, "entity": "musicArtist", "limit": 10},
                    timeout=TIMEOUT_SEARCH,
                )
                if resp is None:
                    raise requests.RequestException("no response")
                resp.raise_for_status()
                first_valid = None
                for r in resp.json().get("results", []):
                    rname = r.get("artistName", "")
                    is_exact = names_match_exact(rname, artist_name)

                    # Collect lenient fallback (word-sharing) if not exact
                    if not is_exact and lenient_fallback is None:
                        if _artist_names_share_word(rname, artist_name):
                            lenient_fallback = (r.get("artistId"), _slugify(rname))

                    if not is_exact:
                        continue
                    if first_valid is None:
                        first_valid = r
                    api_genre = r.get("primaryGenreName", "")
                    if genres and api_genre and not genres_compatible(genres, api_genre):
                        continue  # genre mismatch -- skip, try next
                    rid = r.get("artistId")
                    slug = _slugify(r.get("artistName", ""))
                    break
                # Genre filter exhausted first pass -- accept first name match
                if not rid and first_valid:
                    rid = first_valid.get("artistId")
                    slug = _slugify(first_valid.get("artistName", ""))
            except (requests.RequestException, ValueError):
                pass
            if rid:
                break

        # No exact match -- try lenient word-sharing fallback
        if not rid and lenient_fallback:
            rid, slug = lenient_fallback

    if rid:
        return _fetch_og_image(rid, slug, artist_name)
    return None



def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug with transliteration for non-Latin scripts.

    Transliterates CJK/Cyrillic/Kana/Hangul to ASCII BEFORE stripping combining
    marks, so that voicing marks (e.g. ブ->bu, が->ga) are not lost during
    NFKD decomposition.

    Korean syllables (U+AC00-D7AF) are decomposed to Jamo (NFD) before
    transliteration so the HANGUL_MAP can match them.
    """
    import unicodedata
    text = text.lower().strip()
    # Decompose ONLY Korean syllables to Jamo (not full NFD which breaks Katakana dakuten)
    decomposed = []
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7AF:  # Hangul syllable block
            # Manual Jamo decomposition
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
    # Apply multi-char replacements first (must run before str.maketrans maps)
    for old, new in ALL_MULTI_SEQUENCES:
        text = text.replace(old, new)
    for m in ALL_TRANSLIT_MAPS:
        text = text.translate(m)
    # NFKD decompose Latin accents (ä -> a + combining diaeresis, etc.)
    # then strip combining marks
    nfkd = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


# Known Apple Music logo/image patterns in og:image URLs (not artist photos)
APPLE_LOGO_PATTERNS = (
    "apple-music",
    "og-image",
    "newsroom/images",
    "apple_logo",
)


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _fetch_og_image(artist_id: int, slug: Optional[str] = None, artist_name: str = "") -> Optional[str]:
    """Fetch og:image meta tag from Apple Music artist page.

    Validates that the page is actually about this artist by checking og:title.
    Filters out Apple Music logo/default images (e.g. when artist page doesn't exist).
    """
    urls_to_try = []
    if slug:
        # URL-encode the slug for the path segment (handles any residual non-ASCII)
        encoded_slug = quote(slug, safe="-")
        urls_to_try.append(f"{APPLE_MUSIC_BASE_URL}/{encoded_slug}/{artist_id}")
    urls_to_try.append(f"{APPLE_MUSIC_BASE_URL}/id{artist_id}")

    for url in urls_to_try:
        try:
            resp = _get(url, timeout=TIMEOUT_APPLE_PAGE, headers={
                "User-Agent": random.choice(_USER_AGENTS)
            })
            if resp is None:
                continue
            resp.raise_for_status()

            # Check og:title -- should contain the artist name, otherwise it's a generic page
            if artist_name:
                title_match = re.search(
                    r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
                    resp.text,
                )
                if not title_match:
                    title_match = re.search(
                        r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"',
                        resp.text,
                    )
                if title_match:
                    page_title = title_match.group(1)
                    # Fix double-encoded UTF-8 (e.g. "GarA?ons" -> "Garcons")
                    try:
                        page_title = page_title.encode("latin-1").decode("utf-8")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        pass
                    # If og:title doesn't contain the artist name, this is a generic/404 page
                    norm_title = normalize_name(page_title)
                    norm_artist = normalize_name(artist_name)
                    # Also check slug (romanized) for non-latin scripts (Cyrillic, CJK, etc.)
                    norm_slug = normalize_name(slug) if slug else ""
                    if (norm_artist not in norm_title
                            and (not norm_slug or norm_slug not in norm_title)):
                        continue  # try next URL

            # Extract og:image
            match = re.search(
                r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                resp.text,
            )
            if not match:
                match = re.search(
                    r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
                    resp.text,
                )
            if match:
                img_url = match.group(1)
                # Reject known Apple Music logo/placeholder URLs
                img_lower = img_url.lower()
                if any(p in img_lower for p in APPLE_LOGO_PATTERNS):
                    continue
                # Scale to largest size
                img_url = re.sub(r"/\d+x\d+\w+\.", "/3000x3000-999.", img_url)
                return img_url
        except requests.RequestException:
            continue

    return None


def _detect_image_format(data: bytes) -> str:
    """Detect image format from magic bytes, returns 'jpeg', 'png', or 'webp'."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "unknown"


def _append_ext(p: Path, ext: str) -> Path:
    """Append filename extension (e.g. '.jpg') to a path.

    Works like path.with_name(path.name + ext) but preserves parent.
    """
    return p.parent / (p.name + ext)


def _resize_if_needed(img: _PIL_Image.Image) -> _PIL_Image.Image:
    """Downscale image if it exceeds MAX_IMAGE_DIMENSION (1500px)."""
    if max(img.size) > _MAX_IMAGE_DIMENSION:
        ratio = _MAX_IMAGE_DIMENSION / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        return img.resize(new_size, _PIL_Image.LANCZOS)
    return img


def _save_as_jpeg(data: bytes, save_path: Path,
                  jpeg_quality: int) -> Optional[Path]:
    """Convert image data to JPEG with optional resize and save."""
    try:
        img = _PIL_Image.open(io.BytesIO(data))
        img = _resize_if_needed(img)
        img = img.convert("RGB")
        final_path = _append_ext(save_path, ".jpg")
        img.save(final_path, "JPEG", quality=jpeg_quality, subsampling=0)
        return final_path if final_path.exists() else None
    except Exception:
        return None


def _save_as_png(data: bytes, save_path: Path) -> Optional[Path]:
    """Convert image data to PNG with optional resize and save."""
    try:
        img = _PIL_Image.open(io.BytesIO(data))
        img = _resize_if_needed(img)
        img = img.convert("RGBA")
        final_path = _append_ext(save_path, ".png")
        img.save(final_path, "PNG")
        return final_path if final_path.exists() else None
    except Exception:
        return None


def download_image(url: str, save_path: Path, output_format: str = "jpeg",
                   jpeg_quality: int = 85) -> tuple[Optional[Path], str]:
    """Download image from URL, optionally convert/resize, and save to file.

    Args:
        url: Image URL to download.
        save_path: Path to save to (extension is added automatically).
        output_format: 'jpeg' or 'png'.
        jpeg_quality: JPEG quality 1-100 (used when output_format='jpeg').

    Returns:
        Tuple of (actual_path or None, error_detail_string).
        On success: (Path, "").
        On failure: (None, "reason why it failed").
    """
    try:
        # Use a fresh connection for image download (bypasses _SESSION pool
        # which may be polluted by failed API search requests).
        # This matches the original working behavior that used requests.request().
        resp = None
        for _attempt in range(3):
            try:
                resp = requests.request("GET", url, timeout=TIMEOUT_DOWNLOAD,
                                        headers={"User-Agent": random.choice(_USER_AGENTS)})
                break
            except requests.RequestException:
                if _attempt < 2:
                    time.sleep(1 * (2 ** _attempt))
                    continue
        if resp is None:
            return None, "network error after retries"

        # Validate content length (if provided)
        cl_header = resp.headers.get("Content-Length")
        if cl_header is not None:
            try:
                cl = int(cl_header)
            except (ValueError, TypeError):
                cl = 0
            if cl == 0:
                return None, "content-length is 0"
            if cl > 20 * 1024 * 1024:  # 20MB max
                return None, f"file too large: {cl} bytes"

        # Stream download to avoid loading entire response into memory
        chunks = []
        total_size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                chunks.append(chunk)
                total_size += len(chunk)
                if total_size > 20 * 1024 * 1024:  # 20MB safety limit
                    return None, "file too large (stream exceeded 20MB)"
        data = b"".join(chunks)
        if len(data) == 0:
            return None, "empty response body"

        img_format = _detect_image_format(data)

        # Reject non-image responses (HTML error pages, captchas, etc.)
        if img_format == "unknown":
            return None, "response is not a valid image"

        # Try JPEG conversion first (handles all formats -> JPEG)
        if output_format == "jpeg":
            # Optimization: if source is already JPEG and doesn't need resize,
            # save raw bytes directly to avoid double lossy compression
            if img_format == "jpeg":
                try:
                    img = _PIL_Image.open(io.BytesIO(data))
                    if max(img.size) <= _MAX_IMAGE_DIMENSION:
                        final_path = _append_ext(save_path, ".jpg")
                        final_path.write_bytes(data)
                        if final_path.exists():
                            return final_path, ""
                except Exception:
                    pass  # fallthrough to _save_as_jpeg
            result = _save_as_jpeg(data, save_path, jpeg_quality)
            if result:
                return result, ""
            # Fallback: save raw data as-is

        # For PNG output, convert if source is JPEG, otherwise save raw
        if output_format == "png" and img_format == "jpeg":
            result = _save_as_png(data, save_path)
            if result:
                return result, ""
            # Fallback: save raw data as-is

        # Save raw bytes as-is with correct extension
        if img_format == "png":
            ext = ".png"
        elif img_format == "webp":
            ext = ".webp"
        else:
            ext = ".jpg"
        final_path = _append_ext(save_path, ext)
        final_path.write_bytes(data)
        if final_path.exists():
            return final_path, ""
        return None, "failed to write file to disk"

    except requests.RequestException as e:
        return None, f"network error: {e}"
    except OSError as e:
        return None, f"file error: {e}"
    except Exception as e:
        return None, f"unexpected error: {e}"


def fetch_album_image_deezer(album_name: str, artist_name: str, year: str = "") -> Optional[str]:
    """Search Deezer for album cover image (cover_xl).
    Only returns result if BOTH album name AND artist match EXACTLY.
    """
    album_queries = expand_and_variants(f"{album_name} {artist_name}")
    if year:
        for v in expand_and_variants(f"{album_name} {artist_name} {year}"):
            if v not in album_queries:
                album_queries.append(v)

    for query in album_queries:
        try:
            resp = _get(
                DEEZER_ALBUM_SEARCH_URL,
                params={"q": query, "limit": 10},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                continue
            resp.raise_for_status()
            for item in resp.json().get("data", []):
                cover = item.get("cover_xl") or item.get("cover_big")
                if not cover or _is_deezer_placeholder(cover):
                    continue
                item_album = item.get("title", "")
                item_artist = item.get("artist", {}).get("name", "")
                if names_match_exact(item_album, album_name) and names_match_exact(item_artist, artist_name):
                    return cover
        except (requests.RequestException, ValueError):
            pass

    return None


def fetch_album_image_itunes(album_name: str, artist_name: str, year: str = "") -> Optional[str]:
    """Search iTunes for album artwork.

    Tries both "and" and "&" variants for broader matching.
    Searches WITHOUT year first (the tag year might not match Apple Music),
    then retries WITH year if nothing found. Uses a larger result set (25) to
    handle slight formatting differences in album names.
    Only returns result if BOTH album name AND artist match EXACTLY.
    """
    queries = expand_and_variants(f"{album_name} {artist_name}")
    if year:
        for v in expand_and_variants(f"{album_name} {artist_name} {year}"):
            if v not in queries:
                queries.append(v)

    for query in queries:
        try:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": query, "entity": "album", "limit": 25},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                continue
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                rname = r.get("collectionName", "")
                rartist = r.get("artistName", "")
                if names_match_exact(rname, album_name) and names_match_exact(rartist, artist_name):
                    artwork = r.get("artworkUrl100")
                    if artwork:
                        # Scale artwork URL to largest size
                        return artwork.replace("100x100", "600x600")
        except (requests.RequestException, ValueError):
            pass

    return None


def fetch_album_image(album_name: str, artist_name: str, source: str = "apple_music",
                      year: str = "") -> Optional[str]:
    """Fetch album cover image using specified source with fallback.

    Args:
        album_name: Name of the album to search for.
        artist_name: Name of the artist (for disambiguation).
        source: Primary source ('deezer' or 'apple_music').
        year: Optional release year for more precise matching.

    Returns:
        Image URL if found, None otherwise.
    """
    if source == "deezer":
        url = fetch_album_image_deezer(album_name, artist_name, year)
        if url:
            return url
        return fetch_album_image_itunes(album_name, artist_name, year)
    else:
        url = fetch_album_image_itunes(album_name, artist_name, year)
        if url:
            return url
        return fetch_album_image_deezer(album_name, artist_name, year)


@dataclass
class ArtistCandidate:
    """A single artist match from an API search."""
    artist_id: int
    name: str
    genre: str
    source: str  # "apple_music" or "deezer"


def search_artist_candidates(artist_name: str, source: str = "apple_music",
                             limit: int = 8) -> list[ArtistCandidate]:
    """Search for artists matching the given name.

    Returns a list of candidates so the user can pick the right one.
    Uses expand_and_variants() for full bidirectional accent handling.
    Includes lenient (word-sharing) matches when no exact matches are found.
    """
    candidates: list[ArtistCandidate] = []
    lenient_candidates: list[ArtistCandidate] = []
    seen_ids: set[int] = set()

    # Use expand_and_variants for full bidirectional accent handling
    search_terms = expand_and_variants(artist_name)

    try:
        if source == "deezer":
            for term in search_terms:
                resp = _get(
                    DEEZER_SEARCH_URL,
                    params={"q": term, "limit": limit},
                    timeout=TIMEOUT_SEARCH,
                )
                if resp is None:
                    continue
                for item in resp.json().get("data", []):
                    api_name = item.get("name", "")
                    is_exact = names_match_exact(api_name, artist_name)
                    artist_id = item.get("id")
                    if not artist_id or artist_id in seen_ids:
                        continue
                    seen_ids.add(artist_id)
                    # Fetch genre from artist detail
                    genre = ""
                    try:
                        detail = _get(
                            f"https://api.deezer.com/artist/{artist_id}",
                            timeout=TIMEOUT_DEEZER_DETAIL,
                        )
                        if detail is not None and detail.ok:
                            gid = detail.json().get("genre_id")
                            if gid:
                                gr = _get(
                                    f"https://api.deezer.com/genre/{gid}",
                                    timeout=TIMEOUT_DEEZER_DETAIL,
                                )
                                if gr is not None and gr.ok:
                                    genre = gr.json().get("name", "")
                    except Exception:
                        pass
                    candidate = ArtistCandidate(
                        artist_id=artist_id, name=api_name,
                        genre=genre, source="deezer",
                    )
                    if is_exact:
                        candidates.append(candidate)
                    elif _artist_names_share_word(api_name, artist_name):
                        lenient_candidates.append(candidate)
                    if len(candidates) >= limit:
                        break
                if len(candidates) >= limit:
                    break
        else:
            for term in search_terms:
                resp = _get(
                    ITUNES_SEARCH_URL,
                    params={"term": term, "entity": "musicArtist", "limit": limit},
                    timeout=TIMEOUT_SEARCH,
                )
                if resp is None:
                    continue
                for r in resp.json().get("results", []):
                    api_name = r.get("artistName", "")
                    is_exact = names_match_exact(api_name, artist_name)
                    artist_id = r.get("artistId")
                    if not artist_id or artist_id in seen_ids:
                        continue
                    seen_ids.add(artist_id)
                    candidate = ArtistCandidate(
                        artist_id=artist_id, name=api_name,
                        genre=r.get("primaryGenreName", ""), source="apple_music",
                    )
                    if is_exact:
                        candidates.append(candidate)
                    elif _artist_names_share_word(api_name, artist_name):
                        lenient_candidates.append(candidate)
                    if len(candidates) >= limit:
                        break
                if len(candidates) >= limit:
                    break
    except (requests.RequestException, ValueError):
        pass

    # If no exact matches, include lenient (word-sharing) candidates
    if not candidates and lenient_candidates:
        candidates = lenient_candidates[:limit]

    return candidates


def fetch_artist_image_by_id(candidate: ArtistCandidate) -> Optional[str]:
    """Fetch artist image URL for a specific candidate (by artist ID)."""
    if candidate.source == "deezer":
        try:
            detail = _get(
                f"https://api.deezer.com/artist/{candidate.artist_id}",
                timeout=TIMEOUT_DEEZER_DETAIL,
            )
            if detail is None or not detail.ok:
                return None
            detail_data = detail.json()
            url = detail_data.get("picture_xl") or detail_data.get("picture_big")
            if url and not _is_deezer_placeholder(url):
                return url
        except (requests.RequestException, ValueError):
            pass
        return None
    else:
        return _fetch_og_image(candidate.artist_id, _slugify(candidate.name), candidate.name)


def fetch_candidate_preview(candidate: ArtistCandidate) -> Optional[bytes]:
    """Fetch and return raw image bytes for a candidate's preview thumbnail."""
    url = fetch_artist_image_by_id(candidate)
    if not url:
        return None
    try:
        resp = _get(url, timeout=TIMEOUT_DOWNLOAD)
        if resp is None:
            return None
        resp.raise_for_status()
        return resp.content
    except (requests.RequestException, OSError):
        return None


def fetch_artist_image(artist_name: str, source: str = "apple_music",
                       album_name: str = "", year: str = "",
                       genres: Optional[set[str]] = None,
                       track_name: str = "") -> Optional[str]:
    """Fetch artist image using the specified source only -- NO cross-source fallback.

    If the selected source doesn't have this artist, we return None so the
    caller can prompt the user or try other strategies. Cross-source fallback
    caused issues like downloading Apple Music logos when Deezer was selected.

    Uses album+year+genre+track context for maximum precision:
    - Album/year makes the search specific (like navigating from a track)
    - Track name provides fallback when album search fails
    - Genre filtering rejects wrong-artist matches (e.g. "Guf" rapper vs orchestra)

    Args:
        artist_name: Name of the artist to search for.
        source: Primary source ('deezer' or 'apple_music').
        album_name: Album name for contextual search.
        year: Release year for more precise matching.
        genres: Local genre tags for disambiguation (filters out wrong genres).
        track_name: Track name for track-level fallback search.

    Returns:
        Image URL if found with exact match, None otherwise.
    """
    if genres is None:
        genres = set()
    if source == "deezer":
        return fetch_artist_image_deezer(artist_name, album_name, year, genres, track_name)
    else:
        return fetch_artist_image_itunes(artist_name, album_name, year, genres, track_name)


def _artist_names_share_word(name1: str, name2: str) -> bool:
    """Check if two artist names share at least one significant word (2+ chars) after normalization.

    This is a looser check than names_match_exact -- it allows partial matches
    so that 'Roger Fakhr' can match 'Roger Fakhr' or even 'Fakhr' when the
    track title is an exact match and we just need a plausible artist link.

    Also checks cross-script containment via transliteration (e.g. "Kino"
    contained in transliterated "Кино", or "Bi-2" in "Би-2").
    """
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    words1 = {w for w in re.split(r"\s+", n1) if len(w) >= 2}
    words2 = {w for w in re.split(r"\s+", n2) if len(w) >= 2}
    if words1 & words2:
        return True
    # Cross-script check: transliterate and compare
    from .utils import transliterate_to_latin
    t1 = transliterate_to_latin(name1)
    t2 = transliterate_to_latin(name2)
    if t1 and t2:
        # Check if shorter transliterated name is contained in longer
        shorter, longer = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
        if shorter and len(shorter) >= 2 and shorter in longer:
            return True
        # Also check word overlap on transliterated versions
        tw1 = {w for w in re.split(r"\s+", t1) if len(w) >= 2}
        tw2 = {w for w in re.split(r"\s+", t2) if len(w) >= 2}
        if tw1 & tw2:
            return True
    return False


def fetch_artist_image_by_track_only(track_name: str, artist_name_hint: str,
                                      source: str = "apple_music",
                                      genres: Optional[set[str]] = None) -> Optional[str]:
    """Last-resort search: find artist image by track name alone.

    Search strategy:
    - Search by track name only (no artist constraint in query)
    - Require 100% exact track title match (accent-insensitive)
    - Accept artist if names share at least one significant word
    - Genre filtering as soft preference

    Use case: audio tags say 'Roger Fakhr' but streaming has 'Roger Fakhr'
    and even accent-stripped search fails. A track-level search finds the
    song by title, and we take the artist from that result.
    """
    if genres is None:
        genres = set()

    if source == "deezer":
        return _track_only_deezer(track_name, artist_name_hint, genres)
    else:
        return _track_only_itunes(track_name, artist_name_hint, genres)


def _track_only_deezer(track_name: str, artist_name_hint: str,
                        genres: set[str]) -> Optional[str]:
    """Deezer: search by track name only, match track 100%, accept similar artist.

    Only uses original + accent-stripped query (2 variants max) because
    names_match_exact() already handles accent-insensitive result filtering.
    """
    stripped = strip_accents(track_name)
    queries = [track_name]
    if stripped != track_name:
        queries.append(stripped)
    for query in queries:
        try:
            resp = _get(DEEZER_TRACK_SEARCH_URL,
                        params={"q": query, "limit": _DEEZER_TRACK_LIMIT},
                        timeout=TIMEOUT_SEARCH)
            if resp is None or not resp.ok:
                continue
            for item in resp.json().get("data", []):
                # Track title MUST match 100%
                if not names_match_exact(item.get("title", ""), track_name):
                    continue
                api_artist = item.get("artist", {})
                api_artist_name = api_artist.get("name", "")
                # Artist must share at least one word with our hint
                if not _artist_names_share_word(api_artist_name, artist_name_hint):
                    continue
                # Genre soft filter
                if genres:
                    try:
                        artist_id = api_artist.get("id")
                        if artist_id:
                            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                                          timeout=TIMEOUT_DEEZER_DETAIL)
                            if detail and detail.ok:
                                gid = detail.json().get("genre_id")
                                if gid:
                                    gr = _get(f"https://api.deezer.com/genre/{gid}",
                                              timeout=TIMEOUT_DEEZER_DETAIL)
                                    if gr and gr.ok:
                                        gname = gr.json().get("name", "")
                                        if not genres_compatible(genres, gname):
                                            continue
                    except Exception:
                        pass
                # Got a match -- fetch artist image
                artist_id = api_artist.get("id")
                if not artist_id:
                    continue
                try:
                    detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                                  timeout=TIMEOUT_DEEZER_DETAIL)
                    if detail and detail.ok:
                        url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                        if url and not _is_deezer_placeholder(url):
                            return url
                except Exception:
                    pass
        except (requests.RequestException, ValueError):
            pass
    return None


def _track_only_itunes(track_name: str, artist_name_hint: str,
                        genres: set[str]) -> Optional[str]:
    """iTunes: search by track name only, match track 100%, accept similar artist.

    Only uses original + accent-stripped query (2 variants max) because
    names_match_exact() already handles accent-insensitive result filtering.
    """
    stripped = strip_accents(track_name)
    queries = [track_name]
    if stripped != track_name:
        queries.append(stripped)
    for query in queries:
        try:
            resp = _get(ITUNES_SEARCH_URL,
                        params={"term": query, "entity": "song", "limit": _ITUNES_TRACK_LIMIT},
                        timeout=TIMEOUT_SEARCH)
            if resp is None:
                continue
            for r in resp.json().get("results", []):
                # Track title MUST match 100%
                if not names_match_exact(r.get("trackName", ""), track_name):
                    continue
                api_artist_name = r.get("artistName", "")
                # Artist must share at least one word with our hint
                if not _artist_names_share_word(api_artist_name, artist_name_hint):
                    continue
                # Genre soft filter
                api_genre = r.get("primaryGenreName", "")
                if genres and api_genre and not genres_compatible(genres, api_genre):
                    continue
                artist_id = r.get("artistId")
                if not artist_id:
                    continue
                slug = _slugify(api_artist_name)
                url = _fetch_og_image(artist_id, slug, api_artist_name)
                if url:
                    return url
        except (requests.RequestException, ValueError):
            pass
    return None


def fetch_artist_image_by_album_only(album_name: str, artist_name_hint: str,
                                      source: str = "apple_music",
                                      genres: Optional[set[str]] = None) -> Optional[str]:
    """Last-resort search: find artist image by album name only.

    Search strategy:
    - Search by album name only (no artist constraint in query)
    - Require 100% exact album title match (accent-insensitive)
    - Accept artist if names share at least one significant word
    - Genre filtering as soft preference
    """
    if genres is None:
        genres = set()

    if source == "deezer":
        return _album_only_deezer(album_name, artist_name_hint, genres)
    else:
        return _album_only_itunes(album_name, artist_name_hint, genres)


def _album_only_deezer(album_name: str, artist_name_hint: str,
                        genres: set[str]) -> Optional[str]:
    """Deezer: search by album name only, match album 100%, accept similar artist.

    Only uses original + accent-stripped query (2 variants max) because
    names_match_exact() already handles accent-insensitive result filtering.
    """
    stripped = strip_accents(album_name)
    queries = [album_name]
    if stripped != album_name:
        queries.append(stripped)
    for query in queries:
        try:
            resp = _get(DEEZER_ALBUM_SEARCH_URL,
                        params={"q": query, "limit": _DEEZER_ALBUM_LIMIT},
                        timeout=TIMEOUT_SEARCH)
            if resp is None or not resp.ok:
                continue
            for item in resp.json().get("data", []):
                if not names_match_exact(item.get("title", ""), album_name):
                    continue
                api_artist = item.get("artist", {})
                api_artist_name = api_artist.get("name", "")
                if not _artist_names_share_word(api_artist_name, artist_name_hint):
                    continue
                artist_id = api_artist.get("id")
                if not artist_id:
                    continue
                try:
                    detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                                  timeout=TIMEOUT_DEEZER_DETAIL)
                    if detail and detail.ok:
                        url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                        if url and not _is_deezer_placeholder(url):
                            return url
                except Exception:
                    pass
        except (requests.RequestException, ValueError):
            pass
    return None


def _album_only_itunes(album_name: str, artist_name_hint: str,
                        genres: set[str]) -> Optional[str]:
    """iTunes: search by album name only, match album 100%, accept similar artist.

    Only uses original + accent-stripped query (2 variants max) because
    names_match_exact() already handles accent-insensitive result filtering.
    """
    stripped = strip_accents(album_name)
    queries = [album_name]
    if stripped != album_name:
        queries.append(stripped)
    for query in queries:
        try:
            resp = _get(ITUNES_SEARCH_URL,
                        params={"term": query, "entity": "album", "limit": _ITUNES_ALBUM_LIMIT},
                        timeout=TIMEOUT_SEARCH)
            if resp is None:
                continue
            for r in resp.json().get("results", []):
                if not names_match_exact(r.get("collectionName", ""), album_name):
                    continue
                api_artist_name = r.get("artistName", "")
                if not _artist_names_share_word(api_artist_name, artist_name_hint):
                    continue
                api_genre = r.get("primaryGenreName", "")
                if genres and api_genre and not genres_compatible(genres, api_genre):
                    continue
                artist_id = r.get("artistId")
                if not artist_id:
                    continue
                slug = _slugify(api_artist_name)
                url = _fetch_og_image(artist_id, slug, api_artist_name)
                if url:
                    return url
        except (requests.RequestException, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# Discography fetching (bulk mode: Artist -> Albums -> Tracks -> Covers)
# ---------------------------------------------------------------------------

from .models import Album, Artist as DiscographyArtist


def _resolve_artist_id_deezer(artist_name: str) -> Optional[int]:
    """Search Deezer for an artist by name and return the best-matching ID.

    Uses expand_and_variants for bidirectional accent handling.
    Returns the ID of the first exact (accent-insensitive) match, or None.
    """
    search_terms = expand_and_variants(artist_name)
    for term in search_terms:
        try:
            resp = _get(
                DEEZER_SEARCH_URL,
                params={"q": term, "limit": _DEEZER_ARTIST_LIMIT},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None or not resp.ok:
                continue
            for item in resp.json().get("data", []):
                if names_match_exact(item.get("name", ""), artist_name):
                    return item.get("id")
        except (requests.RequestException, ValueError):
            pass
    return None


def _resolve_artist_id_itunes(artist_name: str) -> Optional[int]:
    """Search iTunes for an artist by name and return the best-matching ID.

    Uses expand_and_variants for bidirectional accent handling.
    Returns the ID of the first exact (accent-insensitive) match, or None.
    """
    search_terms = expand_and_variants(artist_name)
    for term in search_terms:
        try:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": term, "entity": "musicArtist", "limit": _ITUNES_ARTIST_LIMIT},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                continue
            for r in resp.json().get("results", []):
                if names_match_exact(r.get("artistName", ""), artist_name):
                    return r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return None


def fetch_discography_deezer(
    artist_name: str,
    max_albums: int = 0,
    log_fn=None,
) -> Optional[DiscographyArtist]:
    """Fetch full discography from Deezer for the given artist name.

    Args:
        artist_name: The artist name to search for.
        max_albums: Maximum albums to fetch (0 = all).
        log_fn: Optional callback log_fn(message) for progress messages.

    Returns:
        DiscographyArtist with albums populated, or None if artist not found.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    # Step 1: Resolve artist ID
    _log(f"  Searching Deezer for: {artist_name}")
    artist_id = _resolve_artist_id_deezer(artist_name)
    if artist_id is None:
        _log("  Artist not found on Deezer")
        return None

    # Step 2: Fetch artist info (for artist-level cover)
    artist_cover = None
    try:
        detail = _get(
            f"https://api.deezer.com/artist/{artist_id}",
            timeout=TIMEOUT_DEEZER_DETAIL,
        )
        if detail and detail.ok:
            artist_cover = (
                detail.json().get("picture_xl")
                or detail.json().get("picture_big")
            )
    except (requests.RequestException, ValueError):
        pass

    # Step 3: Fetch albums with pagination
    albums: list[Album] = []
    index = 0
    consecutive_429 = 0
    consecutive_errors = 0

    while True:
        if max_albums and len(albums) >= max_albums:
            break
        if consecutive_429 >= 2:
            _log("  Deezer rate-limited (429), stopping album fetch")
            break
        if consecutive_errors >= 3:
            _log("  Too many network errors, stopping album fetch")
            break

        try:
            resp = _get(
                f"https://api.deezer.com/artist/{artist_id}/albums",
                params={"limit": _DEEZER_ALBUM_PAGE_SIZE, "index": index},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                consecutive_errors += 1
                break
            if resp.status_code == 429:
                consecutive_429 += 1
                wait = min(2 ** consecutive_429, _429_MAX_BACKOFF)
                _log(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if not resp.ok:
                consecutive_errors += 1
                continue

            data = resp.json().get("data", [])
            if not data:
                break

            total = resp.json().get("total", 0)
            for item in data:
                if max_albums and len(albums) >= max_albums:
                    break

                title = item.get("title", "").strip()
                if not title:
                    continue

                cover = item.get("cover_xl") or item.get("cover_big")
                if cover and _is_deezer_placeholder(cover):
                    cover = None

                release_date = item.get("release_date", "")
                year = release_date[:4] if len(release_date) >= 4 else ""

                albums.append(Album(
                    title=title,
                    year=year,
                    cover_url=cover,
                    deezer_id=item.get("id"),
                ))

            if len(albums) >= total or len(data) < _DEEZER_ALBUM_PAGE_SIZE:
                break
            index += _DEEZER_ALBUM_PAGE_SIZE

        except (requests.RequestException, ValueError) as exc:
            consecutive_errors += 1
            _log(f"  Error fetching albums: {exc}")
            continue

    _log(f"  Found {len(albums)} album(s) on Deezer")
    return DiscographyArtist(
        name=artist_name,
        albums=albums,
        cover_url=artist_cover,
        deezer_id=artist_id,
    )


def fetch_discography_itunes(
    artist_name: str,
    max_albums: int = 0,
    log_fn=None,
) -> Optional[DiscographyArtist]:
    """Fetch full discography from iTunes/Apple Music for the given artist name.

    Args:
        artist_name: The artist name to search for.
        max_albums: Maximum albums to fetch (0 = all).
        log_fn: Optional callback log_fn(message) for progress messages.

    Returns:
        DiscographyArtist with albums populated, or None if artist not found.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    # Step 1: Resolve artist ID
    _log(f"  Searching iTunes for: {artist_name}")
    artist_id = _resolve_artist_id_itunes(artist_name)
    if artist_id is None:
        _log("  Artist not found on iTunes")
        return None

    # Step 2: Fetch artist cover via Apple Music OG image
    artist_cover = None
    slug = _slugify(artist_name)
    try:
        artist_cover = _fetch_og_image(artist_id, slug, artist_name)
    except (requests.RequestException, ValueError):
        pass

    # Step 3: Fetch all albums via search (single call, up to 200)
    albums: list[Album] = []
    try:
        resp = _get(
            ITUNES_SEARCH_URL,
            params={
                "term": artist_name,
                "entity": "album",
                "limit": _ITUNES_LOOKUP_LIMIT,
            },
            timeout=TIMEOUT_SEARCH,
        )
        if resp is None or not resp.ok:
            _log("  Failed to fetch albums from iTunes")
            return DiscographyArtist(
                name=artist_name, cover_url=artist_cover, itunes_id=artist_id,
            )

        for r in resp.json().get("results", []):
            if max_albums and len(albums) >= max_albums:
                break

            rartist = r.get("artistName", "")
            if not names_match_exact(rartist, artist_name):
                continue

            title = r.get("collectionName", "").strip()
            if not title:
                continue

            artwork = r.get("artworkUrl100", "")
            cover = None
            if artwork:
                cover = re.sub(r"/\d+x\d+\w*\.", "/600x600bb.", artwork)

            release_date = r.get("releaseDate", "")
            year = ""
            if release_date and len(release_date) >= 4:
                year = release_date[:4]

            albums.append(Album(
                title=title,
                year=year,
                cover_url=cover or None,
                itunes_id=r.get("collectionId"),
            ))

    except (requests.RequestException, ValueError) as exc:
        _log(f"  Error fetching albums: {exc}")

    _log(f"  Found {len(albums)} album(s) on iTunes")
    return DiscographyArtist(
        name=artist_name,
        albums=albums,
        cover_url=artist_cover,
        itunes_id=artist_id,
    )


def fetch_discography(
    artist_name: str,
    source: str = "apple_music",
    max_albums: int = 0,
    log_fn=None,
) -> Optional[DiscographyArtist]:
    """Fetch full discography from the specified source.

    Args:
        artist_name: The artist name to search for.
        source: "apple_music" or "deezer".
        max_albums: Maximum albums to fetch (0 = all).
        log_fn: Optional callback for progress messages.

    Returns:
        DiscographyArtist, or None if artist not found.
    """
    if source == "deezer":
        return fetch_discography_deezer(artist_name, max_albums, log_fn)
    return fetch_discography_itunes(artist_name, max_albums, log_fn)
