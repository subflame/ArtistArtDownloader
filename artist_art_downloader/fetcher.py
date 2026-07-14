"""Fetch artist images from Deezer and Apple Music APIs."""

import atexit
import io
import random
import re
import threading
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
# Image processing limits

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
_MAX_RETRIES = 3

# Image processing limits
_MAX_IMAGE_DIMENSION = 1500  # max width/height in px for downloaded images

# Perceptual hash constants (dHash: 8x8 produces 64-bit hash)
_HASH_SIZE = 8
_PLACEHOLDER_MIN_BITS = 4  # minimum set bits in hash to consider non-uniform

# Session-level hash tracker to detect duplicate images across artists
# Maps hash_int -> artist_name for logging/reference
_session_image_hashes: dict[int, str] = {}
_session_hash_lock = threading.Lock()

# Rating system weights for image selection
_RATING_RESOLUTION_WEIGHT = 50.0   # max score for resolution
_RATING_FORMAT_BONUS = 10.0        # PNG bonus
_RATING_SOURCE_PRIORITY = {        # higher = more trusted source
    "deezer_album": 30,
    "itunes_album": 30,
    "deezer_track": 25,
    "itunes_track": 25,
    "deezer_direct": 20,
    "itunes_direct": 20,
    "deezer_track_only": 15,
    "itunes_track_only": 15,
    "deezer_album_only": 15,
    "itunes_album_only": 15,
    "musicbrainz": 35,
}

# Common placeholder indicators in Deezer URLs
DEEZER_PLACEHOLDER_PATTERNS = (
    "15627e72e2e2be8e5f4a5e5e5e5e5e5e",
    "placeholder",
    "default",
)

# Reusable session with connection pooling
_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=10, pool_maxsize=20, max_retries=0,
))
_SESSION.mount("http://", requests.adapters.HTTPAdapter(
    pool_connections=10, pool_maxsize=20, max_retries=0,
))
atexit.register(_SESSION.close)

# Rate limiting: track last request time per host
_last_request_time: dict[str, float] = {}
_RATE_LIMIT_DELAY = 0.5  # seconds between requests to same host
_RATE_LIMIT_COOLDOWN = 30  # seconds to wait after hitting a 429
_last_429_time: dict[str, float] = {}  # host -> time of last 429


def _rate_limit(url: str):
    """Ensure minimum delay between requests to the same host.

    If the host recently returned a 429, enforce a longer cooldown.
    """
    host = urlparse(url).netloc
    now = time.time()

    # Check if host is in 429 cooldown
    cooldown_until = _last_429_time.get(host, 0.0) + _RATE_LIMIT_COOLDOWN
    if now < cooldown_until:
        wait = cooldown_until - now
        time.sleep(wait)

    # Normal per-host rate limit
    last = _last_request_time.get(host, 0.0)
    elapsed = time.time() - last
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_request_time[host] = time.time()


def _is_deezer_placeholder(url: str) -> bool:
    """Check if a Deezer URL is a placeholder/default image."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in DEEZER_PLACEHOLDER_PATTERNS)


def _compute_dhash(data: bytes) -> int:
    """Compute difference hash (dHash) of image data.

    Returns a 64-bit integer hash. Similar images produce similar hashes
    (low Hamming distance). Used to detect placeholder and duplicate images.

    dHash algorithm:
    1. Convert to grayscale
    2. Resize to (HASH_SIZE+1) x HASH_SIZE (9x8)
    3. Compare adjacent pixels per row: set bit if left > right
    4. Return 64-bit hash

    Returns 0 on any error (malformed data, etc.).
    """
    try:
        img = _PIL_Image.open(io.BytesIO(data))
        img = img.convert("L")  # grayscale
        img = img.resize((_HASH_SIZE + 1, _HASH_SIZE), _PIL_Image.LANCZOS)
        pixels = list(img.getdata())
        hash_val = 0
        bit = 0
        for y in range(_HASH_SIZE):
            row_start = y * (_HASH_SIZE + 1)
            for x in range(_HASH_SIZE):
                if pixels[row_start + x] > pixels[row_start + x + 1]:
                    hash_val |= (1 << bit)
                bit += 1
        return hash_val
    except Exception:
        return 0


def _hamming_distance(h1: int, h2: int) -> int:
    """Compute Hamming distance between two perceptual hashes.

    The number of differing bits in two 64-bit hashes.
    Distance of 0 = identical images, > 20 = very different.
    """
    return (h1 ^ h2).bit_count()


def _is_uniform_image(data: bytes, min_bits: int = _PLACEHOLDER_MIN_BITS) -> bool:
    """Check if an image is too uniform (solid color / gradient placeholder).

    Computes the dHash and checks if the number of set bits is below
    a threshold. Very few set bits means most adjacent pixels are
    equal, indicating a solid color or gradient image.

    This catches Deezer-style placeholders, Apple Music og:image logos,
    and other blank/default images that evade URL-based filtering.

    Args:
        data: Raw image bytes.
        min_bits: Minimum number of set bits required. Lower = more strict.
                  Default 4 catches most solid-color placeholders.

    Returns:
        True if the image appears to be a uniform placeholder.
    """
    h = _compute_dhash(data)
    if h == 0:
        return True  # completely uniform (all pixels identical)
    return h.bit_count() < min_bits


def _is_duplicate_image(data: bytes, artist_name: str) -> bool:
    """Check if this image is a duplicate of one already downloaded this session.

    Uses session-level hash tracking to detect when different artists get
    the same image (e.g., a generic placeholder, or same album collage).

    Args:
        data: Raw image bytes.
        artist_name: Name of the current artist (for logging context).

    Returns:
        True if an identical or near-identical image was already downloaded
        for a *different* artist this session.
    """
    h = _compute_dhash(data)
    if h == 0:
        return False  # already caught by _is_uniform_image

    with _session_hash_lock:
        for existing_hash, existing_name in _session_image_hashes.items():
            if existing_name == artist_name:
                continue  # same artist, expected match
            distance = _hamming_distance(h, existing_hash)
            if distance <= 2:
                return True  # perceptually identical
    return False


def _track_image_hash(data: bytes, artist_name: str) -> None:
    """Record image hash for session-level duplicate tracking.

    Called after a successful download to remember this image's hash.
    """
    h = _compute_dhash(data)
    if h:
        with _session_hash_lock:
            _session_image_hashes[h] = artist_name


def _reset_session_hashes() -> None:
    """Clear the session-level hash tracker.

    Called at the start of each new scan/download run.
    """
    with _session_hash_lock:
        _session_image_hashes.clear()


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
                # Record 429 for global cooldown
                if resp.status_code == 429:
                    host = urlparse(url).netloc
                    _last_429_time[host] = time.time()
                if attempt < max_retries - 1:
                    wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                    time.sleep(wait)
                    continue
                return None
            # Non-retryable 4xx (400, 403, 404, etc.) — return immediately
            return resp
        except requests.ConnectionError:
            # Connection-level error (DNS, refused, reset) — retry
            if attempt < max_retries - 1:
                wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            return None
        except requests.Timeout:
            # Timeout — retry
            if attempt < max_retries - 1:
                wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            return None
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

    Exact match only — no lenient/word-sharing fallback.
    """
    base = f"{album_name} {artist_name}"
    queries = expand_and_variants(base)
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
            for r in resp.json().get("results", []):
                rname = r.get("collectionName", "")
                rartist = r.get("artistName", "")
                if not names_match_exact(rname, album_name):
                    continue
                if names_match_exact(rartist, artist_name):
                    return r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return None


def _find_artist_via_track(track_name: str, artist_name: str) -> Optional[int]:
    """Search iTunes by track+artist to find the correct artist ID.

    Exact match only — no lenient/word-sharing fallback.
    """
    base = f"{track_name} {artist_name}"
    queries = expand_and_variants(base)

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
                if names_match_exact(rartist, artist_name):
                    return r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return None


def _search_deezer_by_album(artist_name: str, album_name: str, year: str) -> tuple[Optional[str], Optional[int]]:
    """Deezer: find artist image via album search (most precise).

    Returns (image_url, artist_id) on success, (None, None) on failure.
    Exact match only — no lenient/word-sharing fallback.
    """
    album_queries = expand_and_variants(f"{album_name} {artist_name}")
    if year:
        for v in expand_and_variants(f"{album_name} {artist_name} {year}"):
            if v not in album_queries:
                album_queries.append(v)

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
            if not names_match_exact(api_name, artist_name):
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return (url, artist_id)

    return (None, None)


def _search_deezer_by_track(artist_name: str, track_name: str) -> Optional[str]:
    """Deezer: find artist image via track search.

    Exact match only — no lenient/word-sharing fallback.
    """
    track_queries = expand_and_variants(f"{track_name} {artist_name}")

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
            if not names_match_exact(api_name, artist_name):
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return url

    return None


def _search_deezer_direct(artist_name: str, genres: set[str]) -> Optional[str]:
    """Deezer: direct artist search with genre filter.

    Tries the original name, accent-stripped, and accent-adding variants
    via expand_and_variants() to handle cases like:
    - Local 'Roger Fakhr' vs streaming 'Roger Fakhr' (missing accent)
    - Local 'Roger Fakhr' vs streaming 'Roger Fakhr' (extra accent)
    - Local 'Hamid El Shaeri' vs streaming 'Hamid Al-Shaeri' (transliteration)

    Exact match only — no lenient/word-sharing fallback.
    """
    name_variants = expand_and_variants(artist_name)

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
            if not names_match_exact(item_name, artist_name):
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

    return None


def _verify_by_album_tracks(artist_id: int, source: str,
                             album_tracks: Optional[dict[str, set[str]]],
                             searched_album: str = "") -> bool:
    """Verify artist identity by comparing API track names with local tracks.

    Fetches the artist's albums from the API, then for each album that
    matches a local album name (via names_match_exact), fetches its tracks
    and counts matches across all matched albums.

    Additionally checks that the searched_album (if provided) actually
    exists in the artist's API discography. If no local albums match
    AND the searched album is not found in the API listing, the artist
    is rejected (likely wrong match).

    Threshold is adaptive:
    - Singles/EPs (< 3 local tracks total across matched albums):
      requires ALL local tracks to match API tracks.
    - Full albums (3+ tracks): requires at least 3 matching tracks.

    Uses min(len(local_tracks), len(api_tracks)) as the cap per album
    to account for API response limits (not all tracks may be returned).

    Returns True on any API error (don't reject artist on network issues)
    or if album_tracks is empty/None (no data to verify).
    """
    if not album_tracks:
        return True

    total_matches = 0
    total_possible = 0  # honest cap: min(local, api) per album
    local_album_names = set(album_tracks.keys())
    found_searched = not bool(searched_album)  # True if nothing to check

    try:
        if source == "deezer":
            albums_resp = _get(
                f"https://api.deezer.com/artist/{artist_id}/albums",
                params={"limit": 50},
                timeout=TIMEOUT_SEARCH,
            )
            if albums_resp is None or not albums_resp.ok:
                return True

            for album in albums_resp.json().get("data", []):
                api_album_name = album.get("title", "")

                # Check if searched album exists in API listing
                if not found_searched and names_match_exact(api_album_name, searched_album):
                    found_searched = True

                local_tracks = _find_matching_album_tracks(
                    api_album_name, album_tracks, local_album_names
                )
                if not local_tracks:
                    continue

                album_id = album.get("id")
                if not album_id:
                    continue

                tracks_resp = _get(
                    f"https://api.deezer.com/album/{album_id}/tracks",
                    params={"limit": 50},
                    timeout=TIMEOUT_SEARCH,
                )
                if tracks_resp is None or not tracks_resp.ok:
                    continue

                api_track_names = {
                    t.get("title", "") for t in tracks_resp.json().get("data", [])
                }
                if not api_track_names:
                    continue

                matches = sum(
                    1 for lt in local_tracks
                    if any(names_match_exact(at, lt) for at in api_track_names)
                )
                total_matches += matches
                total_possible += min(len(local_tracks), len(api_track_names))

        else:  # apple_music
            lookup_resp = _get(
                "https://itunes.apple.com/lookup",
                params={"id": artist_id, "entity": "album", "limit": 50},
                timeout=TIMEOUT_SEARCH,
            )
            if lookup_resp is None or not lookup_resp.ok:
                return True

            for item in lookup_resp.json().get("results", []):
                if item.get("wrapperType") != "collection":
                    continue
                api_album_name = item.get("collectionName", "")

                # Check if searched album exists in API listing
                if not found_searched and names_match_exact(api_album_name, searched_album):
                    found_searched = True

                local_tracks = _find_matching_album_tracks(
                    api_album_name, album_tracks, local_album_names
                )
                if not local_tracks:
                    continue

                collection_id = item.get("collectionId")
                if not collection_id:
                    continue

                tracks_resp = _get(
                    "https://itunes.apple.com/lookup",
                    params={"id": collection_id, "entity": "song", "limit": 50},
                    timeout=TIMEOUT_SEARCH,
                )
                if tracks_resp is None or not tracks_resp.ok:
                    continue

                api_track_names = {
                    t.get("trackName", "")
                    for t in tracks_resp.json().get("results", [])
                    if t.get("wrapperType") == "track"
                }
                if not api_track_names:
                    continue

                matches = sum(
                    1 for lt in local_tracks
                    if any(names_match_exact(at, lt) for at in api_track_names)
                )
                total_matches += matches
                total_possible += min(len(local_tracks), len(api_track_names))

    except (requests.RequestException, ValueError):
        return True  # Don't reject on API errors

    if total_possible == 0:
        # No local albums matched the API listing.
        # Reject only if searched_album is also not found — likely wrong artist.
        return found_searched

    # Adaptive threshold: singles/EPs (total < 3) require all to match,
    # full albums require at least 3 matching tracks
    threshold = min(3, total_possible)
    return total_matches >= threshold


def _find_matching_album_tracks(
    api_album_name: str,
    album_tracks: dict[str, set[str]],
    local_album_names: set[str],
) -> Optional[set[str]]:
    """Find local track set for an API album name using exact name matching."""
    for local_name in local_album_names:
        if names_match_exact(api_album_name, local_name):
            return album_tracks[local_name]
    return None


def fetch_artist_image_deezer(artist_name: str, album_name: str = "",
                              year: str = "", genres: Optional[set[str]] = None,
                              track_name: str = "",
                              album_tracks: Optional[dict[str, set[str]]] = None) -> Optional[str]:
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
            url, api_artist_id = _search_deezer_by_album(artist_name, album_name, year)
            if url and api_artist_id:
                if not album_tracks or _verify_by_album_tracks(api_artist_id, "deezer", album_tracks, searched_album=album_name):
                    return url
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
                              track_name: str = "",
                              album_tracks: Optional[dict[str, set[str]]] = None) -> Optional[str]:
    """Search iTunes/Apple Music for artist image.
    
    Search order: album -> track -> name (most->least specific).
    Each level respects genre filtering as a soft preference.
    After finding an artist via album search, verifies by comparing
    API track listing against local album_tracks.
    """
    if genres is None:
        genres = set()
    rid = None
    slug = None

    # Strategy 1: find artist via album search (most precise)
    if album_name:
        artist_id = _find_artist_via_album(album_name, artist_name, year)
        if artist_id:
            if not album_tracks or _verify_by_album_tracks(artist_id, "apple_music", album_tracks, searched_album=album_name):
                rid = artist_id
                slug = _slugify(artist_name)

    # Strategy 2: find artist via track search
    if not rid and track_name:
        artist_id = _find_artist_via_track(track_name, artist_name)
        if artist_id:
            rid = artist_id
            slug = _slugify(artist_name)

    # Strategy 3: direct artist search (exact match only)
    if not rid:
        search_terms = expand_and_variants(artist_name)

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
                for r in resp.json().get("results", []):
                    rname = r.get("artistName", "")
                    if not names_match_exact(rname, artist_name):
                        continue
                    api_genre = r.get("primaryGenreName", "")
                    if genres and api_genre and not genres_compatible(genres, api_genre):
                        continue
                    rid = r.get("artistId")
                    slug = _slugify(r.get("artistName", ""))
                    break
            except (requests.RequestException, ValueError):
                pass
            if rid:
                break

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
                   jpeg_quality: int = 85,
                   artist_name: str = "") -> tuple[Optional[Path], str]:
    """Download image from URL, optionally convert/resize, and save to file.

    Validates image content using perceptual hashing to reject placeholder
    and duplicate images before saving.

    Args:
        url: Image URL to download.
        save_path: Path to save to (extension is added automatically).
        output_format: 'jpeg' or 'png'.
        jpeg_quality: JPEG quality 1-100 (used when output_format='jpeg').
        artist_name: Artist name for session-level duplicate tracking.
                     If empty, duplicate check is skipped.

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
            _rate_limit(url)
            try:
                resp = requests.request("GET", url, timeout=TIMEOUT_DOWNLOAD,
                                        stream=True,
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
            if cl > 50 * 1024 * 1024:  # 50MB max
                return None, f"file too large: {cl} bytes"

        # Stream download to avoid loading entire response into memory
        chunks = []
        total_size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                chunks.append(chunk)
                total_size += len(chunk)
                if total_size > 50 * 1024 * 1024:  # 50MB safety limit
                    return None, "file too large (stream exceeded 50MB)"
        data = b"".join(chunks)
        if len(data) == 0:
            return None, "empty response body"

        img_format = _detect_image_format(data)

        # Reject non-image responses (HTML error pages, captchas, etc.)
        if img_format == "unknown":
            return None, "response is not a valid image"

        # Perceptual hash check: reject uniform/placeholder images
        if _is_uniform_image(data):
            return None, "image appears to be a placeholder (uniform/solid content)"

        # Check for session-level duplicates (different artist, same image)
        if artist_name and _is_duplicate_image(data, artist_name):
            return None, "image is a duplicate of another artist's image"

        # Track this image's hash for future duplicate detection
        if artist_name:
            _track_image_hash(data, artist_name)

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
    Exact match only — no lenient/word-sharing fallback.
    """
    candidates: list[ArtistCandidate] = []
    seen_ids: set[int] = set()

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
                    artist_id = item.get("id")
                    if not artist_id or artist_id in seen_ids:
                        continue
                    if not names_match_exact(api_name, artist_name):
                        continue
                    seen_ids.add(artist_id)
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
                    candidates.append(candidate)
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
                    artist_id = r.get("artistId")
                    if not artist_id or artist_id in seen_ids:
                        continue
                    if not names_match_exact(api_name, artist_name):
                        continue
                    seen_ids.add(artist_id)
                    candidate = ArtistCandidate(
                        artist_id=artist_id, name=api_name,
                        genre=r.get("primaryGenreName", ""), source="apple_music",
                    )
                    candidates.append(candidate)
                    if len(candidates) >= limit:
                        break
                if len(candidates) >= limit:
                    break
    except (requests.RequestException, ValueError):
        pass

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
                       track_name: str = "",
                       album_tracks: Optional[dict[str, set[str]]] = None) -> Optional[str]:
    """Fetch artist image using the specified source only -- NO cross-source fallback.

    If the selected source doesn't have this artist, we return None so the
    caller can prompt the user or try other strategies. Cross-source fallback
    caused issues like downloading Apple Music logos when Deezer was selected.

    Uses album+year+genre+track context for maximum precision:
    - Album/year makes the search specific (like navigating from a track)
    - Track name provides fallback when album search fails
    - Genre filtering rejects wrong-artist matches (e.g. "Guf" rapper vs orchestra)
    - album_tracks provides track-level verification after album match

    Args:
        artist_name: Name of the artist to search for.
        source: Primary source ('deezer' or 'apple_music').
        album_name: Album name for contextual search.
        year: Release year for more precise matching.
        genres: Local genre tags for disambiguation (filters out wrong genres).
        track_name: Track name for track-level fallback search.
        album_tracks: Dict of {album_name: set(track_names)} for verification.

    Returns:
        Image URL if found with exact match, None otherwise.
    """
    if genres is None:
        genres = set()
    if source == "deezer":
        return fetch_artist_image_deezer(artist_name, album_name, year, genres, track_name, album_tracks)
    else:
        return fetch_artist_image_itunes(artist_name, album_name, year, genres, track_name, album_tracks)


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



