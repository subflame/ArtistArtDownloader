"""Folder scanning and metadata reading from audio files."""

from __future__ import annotations

import json
import time
import hashlib
import re
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from tinytag import TinyTag

from .utils import sanitize_filename, transliterate_to_latin
from .config import SCAN_CACHE_FILE

SCAN_CACHE_VERSION = 1
_SCAN_CACHE_LOCK = threading.Lock()

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wma", ".aiff", ".aif"}

# Max parent directories to walk up when searching for an album folder
_MAX_ALBUM_DEPTH = 5

# albumartist values that signal a compilation release
COMPILATION_ALBUMARTISTS = {
    "various artists", "various", "va",
    "varios artistas",
    "verschiedene kunstler", "verschiedene interpret(en)",
    "artistes varies",
    "artisti vari",
    "artistas varios",
}


def _is_compilation(tag) -> bool:
    """Check if the file belongs to a Various Artists compilation.

    Returns True if albumartist matches any pattern:
    - Exact match against COMPILATION_ALBUMARTISTS set (multilingual exact names)
    - Starts with 'va' (case-insensitive, whole word or followed by punctuation)
    - Contains 'various' as a whole word (case-insensitive)
    """
    aa = tag.albumartist
    if not aa:
        return False
    aa_lower = aa.strip().lower()

    # Exact match against known multilingual names
    if aa_lower in COMPILATION_ALBUMARTISTS:
        return True

    # Starts with 'va' followed by a non-word char (boundary)
    # Catches: 'VA - ...', 'VA Compilation', 'VA/', 'VA:', etc.
    if re.match(r'^va\W', aa_lower):
        return True

    # Handles forms with dots/spaces: 'V.A.', 'v.a.', 'V A'
    if re.match(r'^v[\.\s]a', aa_lower):
        return True

    # Contains 'various' as a whole word
    # Catches: 'Various Artists', 'The Various', etc.
    if re.search(r'\bvarious\b', aa_lower):
        return True

    return False


# ---------------------------------------------------------------------------
# Scan cache (hash-verified, mtime+size fast-path)
# ---------------------------------------------------------------------------

def _load_scan_cache(cache_path: Path, scan_path: Path) -> Optional[dict]:
    """Load cached scan data if valid (same path, same version)."""
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("version") != SCAN_CACHE_VERSION:
            return None
        if data.get("scan_path") != str(scan_path):
            return None
        return data.get("files", {})
    except Exception:
        return None


def _save_scan_cache(cache_path: Path, scan_path: Path,
                     cached_data: dict[str, dict]) -> None:
    """Atomically write scan cache to disk (tmp + replace)."""
    payload = {
        "version": SCAN_CACHE_VERSION,
        "scan_path": str(scan_path),
        "created_at": time.time(),
        "files": cached_data,
    }
    tmp = cache_path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(cache_path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _compute_fingerprint(file_path: Path) -> str:
    """SHA-256 of (file_size || first 16KB) — fast content fingerprint."""
    try:
        stat = file_path.stat()
        size = stat.st_size
        h = hashlib.sha256()
        h.update(size.to_bytes(8, "big"))
        with file_path.open("rb") as f:
            chunk = f.read(16384)
            if chunk:
                h.update(chunk)
        return h.hexdigest()[:16]
    except (IOError, OSError):
        return ""


def _build_artist_contexts(
    file_data: dict[str, dict],
) -> dict[str, ArtistContext]:
    """Build ArtistContext dict from per-file tag data.

    ``file_data`` maps file_path -> {tags, album_dir, artist}.
    This is a pure aggregation step — no I/O.
    """
    artists: dict[str, ArtistContext] = {}
    for file_path_str, entry in file_data.items():
        artist = entry.get("artist", "")
        if not artist:
            continue

        # Re-derive album_dir from path (it was cached as str, may be stale)
        album_dir_s = entry.get("album_dir", "")
        if album_dir_s:
            album_dir = Path(album_dir_s)
        else:
            fpath = Path(file_path_str)
            album_dir = _find_album_dir(fpath)
            if not album_dir:
                continue

        is_comp = entry.get("tags", {}).get("is_compilation", False)

        if is_comp:
            if artist not in artists:
                artists[artist] = ArtistContext()
            ctx = artists[artist]
            album_name = entry.get("tags", {}).get("album")
            if album_name:
                ctx.albums.add(album_name)
            title = entry.get("tags", {}).get("title")
            if title:
                ctx.track_names.add(title)
            genre = entry.get("tags", {}).get("genre")
            if genre:
                ctx.genres.add(genre)
            ctx.album_dirs.add(album_dir)
            continue

        if artist not in artists:
            artists[artist] = ArtistContext()

        ctx = artists[artist]
        title = entry.get("tags", {}).get("title")
        if title:
            ctx.track_names.add(title)
        genre = entry.get("tags", {}).get("genre")
        if genre:
            ctx.genres.add(genre)
        album_name = entry.get("tags", {}).get("album")
        if album_name:
            ctx.albums.add(album_name)
            ctx.album_track_counts[album_name] = ctx.album_track_counts.get(album_name, 0) + 1
            if title:
                ctx.album_tracks.setdefault(album_name, set()).add(title)
            if album_name not in ctx.album_years:
                year = entry.get("tags", {}).get("year")
                if year:
                    ctx.album_years[album_name] = year
        ctx.album_dirs.add(album_dir)

    return artists


@dataclass
class ArtistContext:
    # Fields derived from audio file tags
    albums: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    track_names: set[str] = field(default_factory=set)
    album_track_counts: dict[str, int] = field(default_factory=dict)
    album_years: dict[str, str] = field(default_factory=dict)
    album_tracks: dict[str, set[str]] = field(default_factory=dict)
    # Fields derived from filesystem paths
    album_dirs: set[Path] = field(default_factory=set)

    def most_popular_album(self) -> Optional[str]:
        """Return the album name with the most tracks, or None."""
        if not self.album_track_counts:
            return None
        return max(self.album_track_counts, key=self.album_track_counts.get)


def scan_folder(root: Path, skip_existing: bool = False,
               separate_folder: str = "",
               cache_path: Optional[Path] = None,
               progress_cb: Optional[callable] = None) -> dict[str, ArtistContext]:
    """Scan folder recursively and group album dirs by artist name.

    Uses a hash-verified scan cache (mtime+size fast-path, sha256 fallback)
    to avoid re-reading unchanged audio file tags. Cache is auto-detected
    from ``SCAN_CACHE_FILE`` if *cache_path* is not provided.

    If skip_existing is True, artists whose image already exists are skipped
    with ZERO tag reads for artists with in-tree images, and ONE tag read per
    unique artist root when checking a separate output folder.

    Args:
        root: Base folder to scan.
        skip_existing: If True, skip artists with existing image files.
        separate_folder: If set, also check this folder for artist images.
        cache_path: Override scan cache path (default: SCAN_CACHE_FILE).

    Returns:
        dict mapping artist_name -> ArtistContext(...)
    """
    if cache_path is None:
        cache_path = SCAN_CACHE_FILE

    # --- Phase 1: collect file paths ---------------------------------------
    audio_files: list[Path] = []
    for fp in root.rglob("*"):
        if fp.is_symlink():
            continue
        if fp.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if not fp.is_file():
            continue
        audio_files.append(fp)

    # --- Phase 2: load / initialise scan cache -----------------------------
    with _SCAN_CACHE_LOCK:
        old_cache = _load_scan_cache(cache_path, root) or {}
        new_cache: dict[str, dict] = {}
        # file_path_str -> {tags, album_dir, artist}
        file_data: dict[str, dict] = {}

        _skipped_roots: set[Path] = set()
        _scanned_roots: set[Path] = set()

        for fp in audio_files:
            fp_str = str(fp)
            album_dir = _find_album_dir(fp)

            if not album_dir:
                continue

            artist_root = get_artist_root(album_dir, root)

            # skip_existing fast-path: if we already know root is skipped, skip
            if skip_existing and artist_root in _skipped_roots:
                continue

            # skip_existing probe: check image existence for this root once
            if skip_existing and artist_root not in _scanned_roots:
                _scanned_roots.add(artist_root)
                if _find_image_root(album_dir, root) is not None:
                    _skipped_roots.add(artist_root)
                    continue
                if separate_folder:
                    # Need one probe tag to get artist name for separate folder check
                    probe_tags = _read_tags(fp)
                    if probe_tags and not probe_tags.get("is_compilation"):
                        sep_path = Path(separate_folder)
                        safe = sanitize_filename(probe_tags["artist"])
                        if any((sep_path / f"{safe}{ext}").exists() for ext in (".jpg", ".png")):
                            _skipped_roots.add(artist_root)
                            continue
                        # If not skipped, cache the probe tag result
                        new_cache[fp_str] = _make_cache_entry(fp, album_dir, probe_tags, old_cache)
                        file_data[fp_str] = _make_file_data(fp, album_dir, probe_tags)
                        continue
                    # probe failed (no tags) -- still try to read tags below
                    # (skip_existing without separate folder match = read as usual)

            # --- Check cache for this file ----------------------------------
            cached = old_cache.get(fp_str)
            if cached:
                try:
                    cur_stat = fp.stat()
                    cur_mtime = cur_stat.st_mtime_ns if hasattr(cur_stat, 'st_mtime_ns') else int(cur_stat.st_mtime * 1_000_000_000)
                    cached_mtime = cached.get("mtime_ns", 0)
                    cached_size = cached.get("size", -1)
                    if cur_mtime == cached_mtime and cur_stat.st_size == cached_size:
                        # Fast-path: mtime+size match → trust cached tags
                        new_cache[fp_str] = cached
                        file_data[fp_str] = _make_file_data(fp, album_dir, cached.get("tags", {}))
                        if progress_cb:
                            progress_cb()
                        continue
                    # Mtime/size mismatch — verify with fingerprint
                    fp_current = _compute_fingerprint(fp)
                    if fp_current and fp_current == cached.get("fp", ""):
                        # False alarm — content actually matches
                        new_cache[fp_str] = {
                            "mtime_ns": cur_mtime,
                            "size": cur_stat.st_size,
                            "fp": fp_current,
                            "tags": cached["tags"],
                            "album_dir": str(album_dir),
                        }
                        file_data[fp_str] = _make_file_data(fp, album_dir, cached["tags"])
                        if progress_cb:
                            progress_cb()
                        continue
                except (IOError, OSError):
                    pass  # fall through to fresh read

            # --- Cache miss: read tags fresh --------------------------------
            tags = _read_tags(fp)
            if not tags:
                continue

            entry = _make_cache_entry(fp, album_dir, tags, old_cache)
            new_cache[fp_str] = entry
            file_data[fp_str] = _make_file_data(fp, album_dir, tags)

            if progress_cb:
                progress_cb()

        # --- Phase 3: build artist contexts from collected data -------------
        artists = _build_artist_contexts(file_data)

        # --- Phase 4: persist cache -----------------------------------------
        _save_scan_cache(cache_path, root, new_cache)

    return artists


# ---------------------------------------------------------------------------
# Cache helpers — unpack / pack per-file entries
# ---------------------------------------------------------------------------

def _make_cache_entry(fp: Path, album_dir: Path,
                      tags: dict, old_cache: dict) -> dict:
    """Create or update a cache entry for one file."""
    fp_str = str(fp)
    old = old_cache.get(fp_str, {})
    # Preserve fingerprint from old entry if content hash unchanged
    fp_hash = _compute_fingerprint(fp) or old.get("fp", "")
    try:
        stat = fp.stat()
        mtime = stat.st_mtime_ns if hasattr(stat, 'st_mtime_ns') else int(stat.st_mtime * 1_000_000_000)
        size = stat.st_size
    except (IOError, OSError):
        mtime = old.get("mtime_ns", 0)
        size = old.get("size", 0)
    return {
        "mtime_ns": mtime,
        "size": size,
        "fp": fp_hash,
        "tags": {
            "artist": tags.get("artist", ""),
            "album": tags.get("album", ""),
            "title": tags.get("title", ""),
            "genre": tags.get("genre", ""),
            "year": tags.get("year", ""),
            "is_compilation": tags.get("is_compilation", False),
        },
        "album_dir": str(album_dir),
    }


def _make_file_data(fp: Path, album_dir: Path, tags: dict) -> dict:
    """Create a flat ``file_data`` entry from a tags dict (cached or fresh)."""
    return {
        "artist": tags.get("artist", ""),
        "album_dir": str(album_dir),
        "tags": {
            "album": tags.get("album", ""),
            "title": tags.get("title", ""),
            "genre": tags.get("genre", ""),
            "year": tags.get("year", ""),
            "is_compilation": tags.get("is_compilation", False),
        },
    }


def _strip_collaboration_markers(artist: str) -> str:
    """Remove collaboration markers from an artist name.

    Strips feat/ft/vs/with/and/&/comma and everything after them,
    plus any trailing opening brackets left behind by markers.

    Examples:
      "Quasimoto & Madlib"            -> "Quasimoto"
      "Artist1 and Artist2"           -> "Artist1"
      "Eminem, Dr. Dre"              -> "Eminem"
      "Eminem feat. Dr. Dre"          -> "Eminem"
      "Artist Name (feat. Guest)"     -> "Artist Name"
    """
    # Strip guest/producer markers (feat, vs, with, etc.)
    # NOTE: 'and' is intentionally excluded — it appears in many legitimate
    # band names (e.g. "Martha and the Vandellas", "And You Will Know Us...")
    # and is NOT a reliable collaboration marker. Multi-artist splitting
    # via 'and' is handled separately by split_artists().
    # \b ensures 'f' only matches as a standalone word, not as prefix of "F. Merzbow"
    artist = re.sub(
        r'(?:^|[\s\(\[\{])(feat|ft|featuring|vs|with|w|presents?|prod)\b[\s\.:\(\[\{/].*$',
        '',
        artist,
        flags=re.IGNORECASE,
    ).strip()

    # Strip & (ampersand) conjunctions: "Artist1 & Artist2" -> "Artist1"
    # & is a non-word character
    artist = re.sub(
        r'[\s\(\[\{]*&[\s\.:\(\[\{/].*$',
        '',
        artist,
        flags=re.IGNORECASE,
    ).strip()

    # Strip comma-separated collaborators: "Artist1, Artist2" -> "Artist1"
    # Comma must be followed by whitespace to avoid matching "Radiohead, The"
    # (still splits it, but "Radiohead" is a valid searchable name)
    artist = re.sub(
        r',\s+.*$',
        '',
        artist,
    ).strip()

    # Strip any trailing opening brackets left by markers like (feat, (& Artist)
    artist = re.sub(r'[\s\(\[\{]+$', '', artist).strip()

    return artist


def split_artists(artist: str) -> list[str]:
    """Split a multi-artist tag string into individual artist names.

    Only splits on unambiguous separators.
    Comma-splitting is NOT done here — it's already handled earlier
    by _strip_collaboration_markers(), so doing it again would only
    cause false positives on numbers (10,000 Days, 1,2,3,4).

    &/and/et/etc. split is NOT used — too many false positives
    with band names (Bruce Springsteen and The E Street Band,
    Marie et les Garçons, M&M).

    feat.:  "Eminem feat. Dr. Dre"   -> ["Eminem", "Dr. Dre"]
    """
    # Try & split — only when surrounded by spaces to avoid
    # "M&M" and HTML entities like "Lil&apos;"
    if ' & ' in artist:
        parts = [a.strip() for a in artist.split(' & ') if a.strip()]
        if len(parts) > 1:
            return parts

    # Try feat./ft. split
    m = re.split(r'\s+(?:feat\.?|ft\.?|featuring)\s+', artist, flags=re.IGNORECASE)
    if len(m) > 1:
        return [a.strip() for a in m if a.strip()]

    return [artist]


def _parse_artist_from_filename(file_path: Path) -> Optional[str]:
    """Extract artist name from filename when tags are missing.

    Handles patterns like:
      "ArtistName - Song Title.mp3"              -> "ArtistName"
      "01 ArtistName - Song Title.mp3"           -> "ArtistName"
      "01. ArtistName - Song Title.mp3"          -> "ArtistName"
      "01 - ArtistName - Song Title.mp3"         -> "ArtistName"
      "ArtistName.mp3"                            -> "ArtistName"
      "Eminem feat. Dr. Dre - Song.mp3"          -> "Eminem"
      "Artist Name (feat. Guest) - Title.mp3"    -> "Artist Name"
      "Artist ft. Guest - Title.mp3"             -> "Artist"
      "Artist featuring Guest - Title.mp3"       -> "Artist"
      "Quasimoto & Madlib - Title.mp3"          -> "Quasimoto"
      "Artist1 and Artist2 - Title.mp3"         -> "Artist1"
    """
    stem = file_path.stem.strip()
    if not stem:
        return None

    # Strip leading track numbers: "01 ", "01. ", "01 - ", "01-"
    stem = re.sub(r'^\d+[\s\._\-]+', '', stem)

    # Split on " - " (space-dash-space -- common separator)
    parts = stem.split(' - ')
    artist = parts[0].strip()

    # Strip collaboration markers (feat, &, and, vs, with, etc.)
    cleaned = _strip_collaboration_markers(artist)
    # Only use cleaned result if it's non-empty (avoids stripping artist names
    # that start with collaboration-like letters, e.g. "F. Merzbow")
    if cleaned:
        artist = cleaned

    return artist if artist else None


def _read_tags(file_path: Path) -> Optional[dict]:
    """Extract artist, album, and genre from audio file tags.

    Falls back to parsing the filename if tags are missing or empty.
    """
    try:
        tag = TinyTag.get(str(file_path))
    except Exception:
        # TinyTag failed entirely -- try filename fallback
        artist = _parse_artist_from_filename(file_path)
        if artist:
            # Still check compilation names, even from filename
            if artist.lower() in COMPILATION_ALBUMARTISTS:
                return None
            return {"artist": artist, "is_compilation": False}
        return None

    is_comp = _is_compilation(tag)

    # Compilation (Various Artists) → skip entirely.
    # Track artist names from compilations are unreliable — often embedded
    # in brackets inside the track title, or from many different artists
    # under one "Various" umbrella that we shouldn't process.
    if is_comp:
        return None

    artist = tag.albumartist
    if not artist:
        artist = tag.artist

    if not artist:
        # No artist tag at all -- try filename fallback
        artist = _parse_artist_from_filename(file_path)
        if not artist:
            return None
    else:
        artist = artist.strip()
        # Strip collaboration markers from tag-level names too
        # (e.g. "Quasimoto & Madlib" -> "Quasimoto")
        cleaned = _strip_collaboration_markers(artist)
        if cleaned:
            artist = cleaned

    # Never treat "Various Artists" itself as an artist to fetch images for
    if artist.lower() in COMPILATION_ALBUMARTISTS:
        return None

    result = {"artist": artist, "is_compilation": is_comp}
    if tag.album:
        result["album"] = tag.album.strip()
    if tag.title:
        result["title"] = tag.title.strip()
    if tag.genre:
        result["genre"] = tag.genre.strip()
    if tag.year:
        result["year"] = str(tag.year).strip()
    return result


def _find_album_dir(file_path: Path) -> Optional[Path]:
    """Find the album directory from a file path.

    Heuristic: walk up from the file until we find a directory that
    contains audio files (that's the album folder).
    """
    current = file_path.parent
    for _ in range(_MAX_ALBUM_DEPTH):
        try:
            has_audio = any(
                f.suffix.lower() in AUDIO_EXTENSIONS
                for f in current.iterdir()
                if f.is_file()
            )
        except PermissionError:
            return file_path.parent
        if has_audio:
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    return file_path.parent


def artist_image_exists(album_dir: Path, root: Path, artist_name: str = "",
                        separate_folder: str = "") -> bool:
    """Check if an artist image already exists in the artist's root folder.

    Walks up from album_dir to root, checking each ancestor for:
      - artist.jpg / artist.png
      - {dirname}.jpg / {dirname}.png
      - {artist_name}.jpg / {artist_name}.png (if artist_name provided)

    If separate_folder is set, also checks there using artist_name.
    """
    # Check in-tree ancestors
    for parent in album_dir.parents:
        if parent == root or root not in parent.parents:
            break
        candidates = [
            parent / "artist.jpg",
            parent / "artist.png",
            parent / f"{parent.name}.jpg",
            parent / f"{parent.name}.png",
        ]
        if artist_name:
            safe = sanitize_filename(artist_name)
            candidates.insert(0, parent / f"{safe}.jpg")
            candidates.insert(1, parent / f"{safe}.png")
        if any(c.exists() for c in candidates):
            return True
    # Check separate folder (images saved as {ArtistName}.jpg/png)
    if separate_folder and artist_name:
        sep = Path(separate_folder)
        safe = sanitize_filename(artist_name)
        if any((sep / f"{safe}{ext}").exists() for ext in (".jpg", ".png")):
            return True
    return False


def _find_image_root(album_dir: Path, root: Path) -> Optional[Path]:
    """Walk up from album_dir towards root, looking for artist image files.

    At each ancestor level checks for:
      - artist.jpg / artist.png
      - {dirname}.jpg / {dirname}.png

    Returns the first ancestor containing a match, or None.
    """
    for parent in album_dir.parents:
        if parent == root or root not in parent.parents:
            break
        name_stem = parent.name
        for candidate in (
            parent / "artist.jpg",
            parent / "artist.png",
            parent / f"{name_stem}.jpg",
            parent / f"{name_stem}.png",
        ):
            if candidate.exists():
                return parent
    return None


def get_artist_root(album_dir: Path, root: Path) -> Path:
    """Determine the artist root folder relative to the base root.

    For standard Artist/Album structure this is album_dir.parent.
    Guards against saving above the root folder or in root itself.
    """
    parent = album_dir.parent
    try:
        parent.relative_to(root)
    except ValueError:
        # parent is outside root -> save inside album dir
        return album_dir

    if parent == root:
        # parent IS the root -> save inside album dir
        return album_dir

    return parent


_STOP_WORDS = frozenset({"the", "a", "an", "and", "&", "n", "n'"})


@lru_cache(maxsize=None)
def _normalize_name(name: str) -> str:
    """Lowercase, NFKD-decompose accents, transliterate non-Latin scripts,
    expand punctuation to spaces, strip non-alnum, collapse whitespace."""
    n = unicodedata.normalize("NFKD", name.lower())
    n = transliterate_to_latin(n)
    n = n.replace("/", " ").replace("-", " ").replace("&", " and ")
    n = re.sub(r"[^a-z0-9\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _compact(name: str) -> str:
    """Strip ALL non-alphanumeric characters.  Catches pure-punctuation differences
    like 'AC/DC' vs 'ACDC', 'Jay-Z' vs 'Jay Z'."""
    return re.sub(r"[^a-z0-9]", "", transliterate_to_latin(name.lower()))


def _filter_words(name: str) -> list[str]:
    """Normalized tokens with articles / conjunctions removed."""
    return [w for w in _normalize_name(name).split()
            if w not in _STOP_WORDS]


def are_artists_same(name1: str, name2: str) -> bool:
    """Decide whether two artist names refer to the same artist.

    Multi-step validation pipeline (order matters):

    1. NORMALIZED STRING EQUALITY
       After lowercasing, expanding punctuation to spaces, and stripping
       non-alphanumeric chars, if the strings are identical the names are
       the same artist.  Handles: "The Roots" == "Roots" (article stripped).

    2. COMPACT FORM EQUALITY
       Strip *all* non-alphanumeric characters.  Catches cases where the
       only difference is punctuation or whitespace:
       "AC/DC" == "ACDC", "Jay-Z" == "Jay Z", "Guns N' Roses" == "Guns and Roses".

    3. LENGTH RATIO CHECK
       If the shorter normalized string is < 50 % of the longer, reject
       immediately.  Prevents short names like "Tool" from matching longer
       names like "Kool" that only share a few characters.

    4. TOKENIZATION + STOP-WORD REMOVAL
       Split into words, discard articles ("the","a","an") and conjunctions
       ("and","&","n'").  Compare the remaining *significant* words.

    5. WORD-LEVEL COMPARISON
       - If both word lists are identical after filtering → same artist.
       - If one list is a strict subset of the other → reject (extra words
         mean extra meaning, e.g. "rush" in "ed rush").
       - If both have unique words, check that each unique word in the
         shorter list is a prefix of the corresponding word in the longer
         list (handles abbreviated forms like "pun" / "punisher").
         Prefix matching is only allowed when the two words have *different*
         lengths — same-length words must match exactly (prevents
         "Tool" / "Kool" false positives).
    """
    # --- Step 1: normalized string equality ---
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)
    if n1 == n2:
        return True

    # --- Step 2: compact form equality (punctuation-only diffs) ---
    c1 = _compact(name1)
    c2 = _compact(name2)
    if c1 == c2:
        return True

    # --- Tokenize ---
    w1 = _filter_words(name1)
    w2 = _filter_words(name2)

    # Both reduced to nothing (only stop words) → can't compare
    if not w1 or not w2:
        return False

    # --- Step 3: length ratio check ---
    len_ratio = min(len(n1), len(n2)) / max(len(n1), len(n2))
    if len_ratio < 0.5:
        return False

    # Align so f1 is the shorter / equal-length word list
    f1, f2 = (w1, w2) if len(w1) <= len(w2) else (w2, w1)

    # Unique words in each list (preserves order for prefix matching)
    fw1 = [w for w in f1 if w not in f2]
    fw2 = [w for w in f2 if w not in f1]

    # --- Step 5a: all words match → same artist ---
    if not fw1 and not fw2:
        return True

    # --- Step 5b: one side is a strict subset → extra words = different ---
    if not fw1 or not fw2:
        return False

    # --- Step 5c: both have unique words → prefix matching ---
    if len(fw1) != len(fw2):
        return False

    # Require at least one shared word between full normalized names
    # to prevent short unique words like "sly" from matching longer unrelated
    # names like "slyder" via prefix matching.
    full1_words = set(_normalize_name(name1).split())
    full2_words = set(_normalize_name(name2).split())
    if not (full1_words & full2_words):
        return False

    for a, b in zip(fw1, fw2):
        if a == b:
            continue
        # Prefix match: shorter word is a prefix of the longer word.
        # Only allowed when lengths differ (same-length must be exact).
        if len(a) != len(b) and b.startswith(a):
            continue
        return False

    return True


def find_similar_artists(artists: dict[str, ArtistContext]) -> list[list[str]]:
    """Find groups of artist names that refer to the same artist.

    Uses ``are_artists_same`` for multi-step validation (normalized string
    comparison, compact form check, length ratio, tokenization, and
    prefix matching).

    Each artist name appears in at most one group.

    Args:
        artists: Artist dict from scan_folder.

    Returns:
        List of groups, each group is a list of 2+ similar artist names.
    """
    names = list(artists.keys())
    if len(names) < 2:
        return []

    assigned: set[str] = set()
    groups: list[list[str]] = []

    for name in names:
        if name in assigned:
            continue
        similar: list[str] = []
        for other in names:
            if other == name or other in assigned:
                continue
            if are_artists_same(name, other):
                similar.append(other)
        if similar:
            group = [name] + similar
            groups.append(group)
            for g in group:
                assigned.add(g)

    return groups


def merge_artists(artists: dict[str, ArtistContext], merge_map: dict[str, str]) -> dict[str, ArtistContext]:
    """Merge artist contexts using a mapping of alias -> canonical name.

    Aliases are merged into their canonical entry, combining album_dirs,
    albums, and genres from all aliases.

    Args:
        artists: Original artist dict from scan_folder.
        merge_map: {alias_name: canonical_name} -- each alias will be merged
                   into the canonical entry. A name mapped to itself is kept.

    Returns:
        New dict with aliases merged into canonical entries.
    """
    result: dict[str, ArtistContext] = {}
    aliases = set(merge_map.keys())

    def _merge_into(name: str, ctx: ArtistContext) -> None:
        if name in result:
            existing = result[name]
            merged_counts: dict[str, int] = {}
            for k in set(existing.album_track_counts) | set(ctx.album_track_counts):
                merged_counts[k] = existing.album_track_counts.get(k, 0) + ctx.album_track_counts.get(k, 0)
            merged_tracks: dict[str, set[str]] = {}
            for k in set(existing.album_tracks) | set(ctx.album_tracks):
                merged_tracks[k] = existing.album_tracks.get(k, set()) | ctx.album_tracks.get(k, set())
            result[name] = ArtistContext(
                album_dirs=existing.album_dirs | ctx.album_dirs,
                albums=existing.albums | ctx.albums,
                genres=existing.genres | ctx.genres,
                track_names=existing.track_names | ctx.track_names,
                album_track_counts=merged_counts,
                album_years={**existing.album_years, **ctx.album_years},
                album_tracks=merged_tracks,
            )
        else:
            result[name] = ArtistContext(
                album_dirs=set(ctx.album_dirs),
                albums=set(ctx.albums),
                genres=set(ctx.genres),
                track_names=set(ctx.track_names),
                album_track_counts=dict(ctx.album_track_counts),
                album_years=dict(ctx.album_years),
                album_tracks={k: set(v) for k, v in ctx.album_tracks.items()},
            )

    for name, ctx in artists.items():
        if name in aliases:
            canonical = merge_map[name]
            _merge_into(canonical, ctx)
        else:
            _merge_into(name, ctx)

    return result
