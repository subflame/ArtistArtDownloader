"""Fetch artist images from Deezer and Apple Music APIs."""

import atexit
import io
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image as _PIL_Image

from .translit_maps import ALL_MULTI_SEQUENCES, ALL_TRANSLIT_MAPS
from .utils import (
    expand_and_variants,
    genres_compatible,
    names_match_exact,
    normalize_name,
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
            # Don't retry 4xx errors (except 429 - Too Many Requests)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_retries - 1:
                    wait = (1 * (2 ** attempt)) + random.uniform(0, 0.5)
                    time.sleep(wait)
                    continue
                return None  # retries exhausted — treat as failure
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
                if names_match_exact(rname, album_name) and names_match_exact(rartist, artist_name):
                    return r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return None


def _find_artist_via_track(track_name: str, artist_name: str) -> Optional[int]:
    """Search iTunes by track+artist to find the correct artist ID.

    Uses song entity search — the results include artistId directly.
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
                if names_match_exact(rtrack, track_name) and names_match_exact(rartist, artist_name):
                    return r.get("artistId")
        except (requests.RequestException, ValueError):
            pass
    return None


def _search_deezer_by_album(artist_name: str, album_name: str, year: str) -> Optional[str]:
    """Deezer: find artist image via album search (most precise)."""
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
            if not names_match_exact(item_artist.get("name", ""), artist_name):
                continue
            artist_id = item_artist.get("id")
            if not artist_id:
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return url
    return None


def _search_deezer_by_track(artist_name: str, track_name: str) -> Optional[str]:
    """Deezer: find artist image via track search."""
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
            if not names_match_exact(item_artist.get("name", ""), artist_name):
                continue
            artist_id = item_artist.get("id")
            if not artist_id:
                continue
            detail = _get(f"https://api.deezer.com/artist/{artist_id}",
                          timeout=TIMEOUT_DEEZER_DETAIL)
            if detail and detail.ok:
                url = detail.json().get("picture_xl") or detail.json().get("picture_big")
                if url and not _is_deezer_placeholder(url):
                    return url
    return None


def _search_deezer_direct(artist_name: str, genres: set[str]) -> Optional[str]:
    """Deezer: direct artist search with genre filter."""
    resp = _get(DEEZER_SEARCH_URL, params={"q": artist_name, "limit": _DEEZER_ARTIST_LIMIT},
                timeout=TIMEOUT_SEARCH)
    if resp is None:
        return None
    first_valid_url = None
    for item in resp.json().get("data", []):
        if not names_match_exact(item.get("name", ""), artist_name):
            continue
        url = item.get("picture_xl") or item.get("picture_big")
        if not url or _is_deezer_placeholder(url):
            continue
        if first_valid_url is None:
            first_valid_url = url
        if genres:
            try:
                detail = _get(f"https://api.deezer.com/artist/{item['id']}",
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
        return url
    return first_valid_url


def fetch_artist_image_deezer(artist_name: str, album_name: str = "",
                              year: str = "", genres: Optional[set[str]] = None,
                              track_name: str = "") -> Optional[str]:
    """Search Deezer for artist image URL (picture_xl).
    Uses album+year context + genre filtering for precise matching.
    """
    if genres is None:
        genres = set()
    try:
        if album_name:
            result = _search_deezer_by_album(artist_name, album_name, year)
            if result:
                return result
        if not album_name and track_name:
            result = _search_deezer_by_track(artist_name, track_name)
            if result:
                return result
        return _search_deezer_direct(artist_name, genres)
    except (requests.RequestException, ValueError):
        return None


def fetch_artist_image_itunes(artist_name: str, album_name: str = "",
                              year: str = "", genres: Optional[set[str]] = None,
                              track_name: str = "") -> Optional[str]:
    """Search iTunes/Apple Music for artist image.
    
    Search order: album → track → name (most→least specific).
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
    if not rid:
        try:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": artist_name, "entity": "musicArtist", "limit": 10},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                raise requests.RequestException("no response")
            resp.raise_for_status()
            first_valid = None
            for r in resp.json().get("results", []):
                if not names_match_exact(r.get("artistName", ""), artist_name):
                    continue
                if first_valid is None:
                    first_valid = r
                api_genre = r.get("primaryGenreName", "")
                if genres and api_genre and not genres_compatible(genres, api_genre):
                    continue  # genre mismatch — skip, try next
                rid = r.get("artistId")
                slug = _slugify(r.get("artistName", ""))
                break
            # Genre filter exhausted first pass — accept first name match
            if not rid and first_valid:
                rid = first_valid.get("artistId")
                slug = _slugify(first_valid.get("artistName", ""))
        except (requests.RequestException, ValueError):
            pass

    if rid:
        return _fetch_og_image(rid, slug, artist_name)
    return None



def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug with transliteration for non-Latin scripts."""
    text = text.lower().strip()
    # Apply multi-char replacements first (must run before str.maketrans maps)
    for old, new in ALL_MULTI_SEQUENCES:
        text = text.replace(old, new)
    for m in ALL_TRANSLIT_MAPS:
        text = text.translate(m)
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
        urls_to_try.append(f"{APPLE_MUSIC_BASE_URL}/{slug}/{artist_id}")
    urls_to_try.append(f"{APPLE_MUSIC_BASE_URL}/id{artist_id}")

    for url in urls_to_try:
        try:
            resp = _get(url, timeout=TIMEOUT_APPLE_PAGE, headers={
                "User-Agent": random.choice(_USER_AGENTS)
            })
            if resp is None:
                continue
            resp.raise_for_status()

            # Check og:title — should contain the artist name, otherwise it's a generic page
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
                    # Fix double-encoded UTF-8 (e.g. "GarÃ§ons" → "Garçons")
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
                   jpeg_quality: int = 85) -> Optional[Path]:
    """Download image from URL, optionally convert/resize, and save to file.

    Args:
        url: Image URL to download.
        save_path: Path to save to (extension is added automatically).
        output_format: 'jpeg' or 'png'.
        jpeg_quality: JPEG quality 1–100 (used when output_format='jpeg').

    Returns:
        Actual path saved to, or None on failure.
    """
    try:
        resp = _get(url, timeout=TIMEOUT_DOWNLOAD, stream=True)
        if resp is None:
            return None
        resp.raise_for_status()

        # Validate content type
        ct = resp.headers.get("Content-Type", "")
        if not ct.startswith("image/"):
            return None

        # Validate content length (if provided)
        cl_header = resp.headers.get("Content-Length")
        if cl_header is not None:
            cl = int(cl_header)
            if cl == 0:
                return None
            if cl > 20 * 1024 * 1024:  # 20MB max
                return None

        data = resp.content
        if len(data) == 0:
            return None

        img_format = _detect_image_format(data)

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
                        return final_path if final_path.exists() else None
                except Exception:
                    pass  # fallthrough to _save_as_jpeg
            result = _save_as_jpeg(data, save_path, jpeg_quality)
            if result:
                return result
            # Fallback: save raw data as-is

        # For PNG output, convert if source is JPEG, otherwise save raw
        if output_format == "png" and img_format == "jpeg":
            result = _save_as_png(data, save_path)
            if result:
                return result
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
        return final_path if final_path.exists() else None

    except (requests.RequestException, OSError):
        return None


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
    """Search for all artists with the exact same name (case/accent-insensitive).

    Returns a list of candidates so the user can pick the right one
    when the API returns multiple artists with the same name.
    """
    candidates: list[ArtistCandidate] = []

    try:
        if source == "deezer":
            resp = _get(
                DEEZER_SEARCH_URL,
                params={"q": artist_name, "limit": limit},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                return candidates
            for item in resp.json().get("data", []):
                if not names_match_exact(item.get("name", ""), artist_name):
                    continue
                artist_id = item.get("id")
                if not artist_id:
                    continue
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
                candidates.append(ArtistCandidate(
                    artist_id=artist_id, name=item.get("name", ""),
                    genre=genre, source="deezer",
                ))
        else:
            resp = _get(
                ITUNES_SEARCH_URL,
                params={"term": artist_name, "entity": "musicArtist", "limit": limit},
                timeout=TIMEOUT_SEARCH,
            )
            if resp is None:
                return candidates
            for r in resp.json().get("results", []):
                if not names_match_exact(r.get("artistName", ""), artist_name):
                    continue
                artist_id = r.get("artistId")
                if not artist_id:
                    continue
                candidates.append(ArtistCandidate(
                    artist_id=artist_id, name=r.get("artistName", ""),
                    genre=r.get("primaryGenreName", ""), source="apple_music",
                ))
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
                       track_name: str = "") -> Optional[str]:
    """Fetch artist image using the specified source only — NO cross-source fallback.

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
