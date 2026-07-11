"""Bulk cover art downloader: fetches entire artist discographies.

Orchestrates: discography fetching -> path creation -> streaming download.
Implements resume via file-existence checks (no state file needed).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import requests

from .fetcher import (
    TIMEOUT_DOWNLOAD,
    _SESSION,
    fetch_discography,
)
from .models import Album, Artist
from .utils import (
    safe_join,
    sanitize_folder_name,
    truncate_path_parts,
)

logger = logging.getLogger(__name__)

# Chunk size for streaming downloads (8 KB)
_DOWNLOAD_CHUNK_SIZE = 8192

# Default output directory name
DEFAULT_OUTPUT_DIR = "output"


class BulkDownloadStats:
    """Tracks download statistics for a single artist run."""

    def __init__(self) -> None:
        self.albums_found: int = 0
        self.albums_skipped: int = 0
        self.albums_downloaded: int = 0
        self.albums_failed: int = 0
        self.artist_cover_downloaded: bool = False

    @property
    def total(self) -> int:
        return self.albums_downloaded + self.albums_skipped + self.albums_failed

    def summary(self) -> str:
        parts = []
        if self.albums_downloaded:
            parts.append(f"{self.albums_downloaded} downloaded")
        if self.albums_skipped:
            parts.append(f"{self.albums_skipped} skipped")
        if self.albums_failed:
            parts.append(f"{self.albums_failed} failed")
        if self.artist_cover_downloaded:
            parts.append("artist cover OK")
        return ", ".join(parts) if parts else "nothing to do"


def _album_cover_exists(album_dir: Path) -> bool:
    """Check if a valid cover already exists for this album.

    A valid cover is a file named cover.jpg, cover.png, or cover.webp
    that is larger than 1 KB (to reject empty/corrupt files).
    """
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = album_dir / f"cover{ext}"
        if candidate.exists() and candidate.stat().st_size > 1024:
            return True
    return False


def _download_cover_streaming(url: str, dest: Path, timeout: int = TIMEOUT_DOWNLOAD) -> None:
    """Download an image using stream=True + iter_content.

    Uses a fresh connection (not _SESSION) to avoid stale pooled connections.
    Writes to a .tmp file first, then atomically renames on success.
    Cleans up the .tmp file on any failure.

    Args:
        url: Image URL to download.
        dest: Destination path (e.g., album_dir / "cover.jpg").
        timeout: Request timeout in seconds.

    Raises:
        requests.RequestException: On network errors.
        OSError: On file I/O errors.
        ValueError: If URL is empty.
    """
    if not url:
        raise ValueError("Empty URL")

    temp = dest.with_suffix(dest.suffix + ".tmp")

    try:
        resp = requests.request("GET", url, stream=True, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        # Determine content type from response
        content_type = resp.headers.get("Content-Type", "")
        if "png" in content_type:
            dest = dest.with_suffix(".png")
            temp = dest.with_suffix(".png.tmp")

        with open(temp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                if chunk:  # filter out keep-alive chunks
                    f.write(chunk)

        # Atomic rename
        temp.replace(dest)

    except (requests.RequestException, OSError):
        # Clean up partial download
        temp.unlink(missing_ok=True)
        raise


def download_discography(
    artist: Artist,
    output_root: Path,
    *,
    source: str = "apple_music",
    download_artist_cover: bool = False,
    skip_existing: bool = True,
    log_fn=None,
) -> BulkDownloadStats:
    """Download all album covers for an artist's discography.

    Folder structure:
        output_root/Artist_Name/Album_Name (Year)/cover.jpg

    Resume support: if skip_existing is True (default), albums that
    already have a cover file (>1KB) are skipped instantly.

    Args:
        artist: DiscographyArtist with albums populated.
        output_root: Base output directory.
        source: "apple_music" or "deezer" (for logging only).
        download_artist_cover: Whether to save artist-level cover.
        skip_existing: Skip albums that already have covers.
        log_fn: Optional callback log_fn(message) for progress.

    Returns:
        BulkDownloadStats with download counts.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    stats = BulkDownloadStats()
    stats.albums_found = artist.album_count

    if not artist.albums:
        _log(f"  No albums found for {artist.name}")
        return stats

    # Create artist folder
    safe_artist = sanitize_folder_name(artist.name)
    artist_dir = safe_join(output_root, safe_artist)
    artist_dir.mkdir(parents=True, exist_ok=True)

    # Download artist-level cover
    if download_artist_cover and artist.cover_url:
        artist_cover_path = artist_dir / "artist.jpg"
        if not (skip_existing and artist_cover_path.exists()
                and artist_cover_path.stat().st_size > 1024):
            try:
                _download_cover_streaming(artist.cover_url, artist_cover_path)
                stats.artist_cover_downloaded = True
                _log(f"  Artist cover downloaded")
            except (requests.RequestException, OSError, ValueError) as exc:
                _log(f"  Artist cover failed: {exc}")
        elif skip_existing:
            _log(f"  Artist cover exists, skipping")
            stats.artist_cover_downloaded = True

    # Download album covers
    for i, album in enumerate(artist.albums, 1):
        # Truncate paths if needed (Windows 260-char limit)
        safe_artist_dir, safe_album_dir = truncate_path_parts(
            artist.name, album.display_title,
        )
        album_dir = safe_join(output_root, safe_artist_dir, safe_album_dir)

        # Check resume
        if skip_existing and _album_cover_exists(album_dir):
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- exists")
            stats.albums_skipped += 1
            continue

        # Create album directory
        album_dir.mkdir(parents=True, exist_ok=True)

        # Download cover
        if not album.cover_url:
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- no cover URL")
            stats.albums_failed += 1
            continue

        try:
            cover_path = album_dir / "cover.jpg"
            _download_cover_streaming(album.cover_url, cover_path)
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- downloaded")
            stats.albums_downloaded += 1
        except requests.Timeout:
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- timeout")
            stats.albums_failed += 1
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- HTTP {status}")
            stats.albums_failed += 1
        except (requests.ConnectionError, requests.RequestException) as exc:
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- network: {exc}")
            stats.albums_failed += 1
        except OSError as exc:
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- file error: {exc}")
            stats.albums_failed += 1
        except ValueError as exc:
            _log(f"  [{i}/{stats.albums_found}] {album.display_title} -- {exc}")
            stats.albums_failed += 1

    return stats


def run_bulk_download(
    artist_name: str,
    output_dir: Path | str | None = None,
    *,
    source: str = "apple_music",
    max_albums: int = 0,
    download_artist_cover: bool = False,
    skip_existing: bool = True,
    log_fn=None,
) -> BulkDownloadStats:
    """High-level entry point: fetch discography + download all covers.

    Args:
        artist_name: The artist name to search for.
        output_dir: Output directory (defaults to ./output).
        source: "apple_music" or "deezer".
        max_albums: Maximum albums to fetch (0 = all).
        download_artist_cover: Whether to save artist-level cover.
        skip_existing: Skip albums that already have covers.
        log_fn: Optional callback for progress messages.

    Returns:
        BulkDownloadStats with download counts.
    """
    if output_dir is None:
        output_dir = Path.cwd() / DEFAULT_OUTPUT_DIR
    elif isinstance(output_dir, str):
        output_dir = Path(output_dir)

    output_dir = output_dir.resolve()

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    _log(f"Fetching discography: {artist_name} (source={source})")

    # Fetch discography
    artist = fetch_discography(
        artist_name,
        source=source,
        max_albums=max_albums,
        log_fn=log_fn,
    )

    if artist is None:
        _log(f"Artist not found: {artist_name}")
        return BulkDownloadStats()

    # Download
    _log(f"Starting download: {artist.album_count} album(s)")
    stats = download_discography(
        artist,
        output_dir,
        source=source,
        download_artist_cover=download_artist_cover,
        skip_existing=skip_existing,
        log_fn=log_fn,
    )

    _log(f"Done: {stats.summary()}")
    return stats