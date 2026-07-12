"""Folder scanning and metadata reading from audio files."""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from tinytag import TinyTag

from .utils import sanitize_filename

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
    """Check if the file belongs to a Various Artists compilation."""
    aa = tag.albumartist
    if not aa:
        return False
    return aa.strip().lower() in COMPILATION_ALBUMARTISTS


@dataclass
class ArtistContext:
    # Fields derived from audio file tags
    albums: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    track_names: set[str] = field(default_factory=set)
    album_track_counts: dict[str, int] = field(default_factory=dict)
    album_years: dict[str, str] = field(default_factory=dict)
    # Fields derived from filesystem paths
    album_dirs: set[Path] = field(default_factory=set)

    def most_popular_album(self) -> Optional[str]:
        """Return the album name with the most tracks, or None."""
        if not self.album_track_counts:
            return None
        return max(self.album_track_counts, key=self.album_track_counts.get)


def scan_folder(root: Path, skip_existing: bool = False,
               separate_folder: str = "") -> dict[str, ArtistContext]:
    """Scan folder recursively and group album dirs by artist name.

    If skip_existing is True, artists whose image already exists are skipped
    with ZERO tag reads for artists with in-tree images, and ONE tag read per
    unique artist root when checking a separate output folder.

    Args:
        root: Base folder to scan.
        skip_existing: If True, skip artists with existing image files.
        separate_folder: If set, also check this folder for artist images.

    Returns:
        dict mapping artist_name -> ArtistContext(...)
    """
    artists: dict[str, ArtistContext] = {}
    # artist_root Path -> True if image was confirmed to exist
    _skipped_roots: set[Path] = set()
    _scanned_roots: set[Path] = set()

    for file_path in root.rglob("*"):
        if file_path.is_symlink():
            continue
        if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if not file_path.is_file():
            continue

        album_dir = _find_album_dir(file_path)
        if not album_dir:
            continue

        artist_root = get_artist_root(album_dir, root)

        if skip_existing and artist_root in _skipped_roots:
            continue

        if skip_existing and artist_root not in _scanned_roots:
            _scanned_roots.add(artist_root)
            # 1) Check in-tree ancestors
            if _find_image_root(album_dir, root) is not None:
                _skipped_roots.add(artist_root)
                continue
            # 2) Check separate folder -- need one probe tag to get artist name
            if separate_folder:
                probe = _read_tags(file_path)
                if probe and not probe.get("is_compilation"):
                    sep_path = Path(separate_folder)
                    safe = sanitize_filename(probe["artist"])
                    if any((sep_path / f"{safe}{ext}").exists() for ext in (".jpg", ".png")):
                        _skipped_roots.add(artist_root)
                        continue

        tags = _read_tags(file_path)
        if not tags:
            continue

        artist = tags["artist"]

        # For compilation tracks, don't include the comp folder as an album_dir
        # (it would mess up artist root detection)
        if tags.get("is_compilation"):
            if artist not in artists:
                continue
            # Artist already exists with proper album dirs -- just collect metadata
            ctx = artists[artist]
            if tags.get("album"):
                ctx.albums.add(tags["album"])
            if tags.get("genre"):
                ctx.genres.add(tags["genre"])
            continue

        if artist not in artists:
            artists[artist] = ArtistContext()

        ctx = artists[artist]
        # Process tag fields first
        if tags.get("title"):
            ctx.track_names.add(tags["title"])
        if tags.get("genre"):
            ctx.genres.add(tags["genre"])
        if tags.get("album"):
            album_name = tags["album"]
            ctx.albums.add(album_name)
            ctx.album_track_counts[album_name] = ctx.album_track_counts.get(album_name, 0) + 1
            # Keep the first year we see for this album
            if album_name not in ctx.album_years and tags.get("year"):
                ctx.album_years[album_name] = tags["year"]
        # Then process filesystem paths
        ctx.album_dirs.add(album_dir)

    return artists


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
    # Strip guest/producer/conjunction markers (feat, and, vs, with, etc.)
    # \b ensures 'f' only matches as a standalone word, not as prefix of "F. Merzbow"
    artist = re.sub(
        r'(?:^|[\s\(\[\{])(feat|ft|featuring|vs|with|w|presents?|prod|and)\b[\s\.:\(\[\{/].*$',
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

    Handles:
      "Eminem, Dr. Dre"              -> ["Eminem", "Dr. Dre"]
      "Quasimoto & Madlib"           -> ["Quasimoto", "Madlib"]
      "Artist1 and Artist2"          -> ["Artist1", "Artist2"]
      "Eminem feat. Dr. Dre"         -> ["Eminem", "Dr. Dre"]
      "Artist"                       -> ["Artist"]
    """
    # First try comma split (most common multi-artist delimiter)
    if ',' in artist:
        parts = [a.strip() for a in artist.split(',') if a.strip()]
        if len(parts) > 1:
            return parts

    # Try & split
    if '&' in artist:
        parts = [a.strip() for a in artist.split('&') if a.strip()]
        if len(parts) > 1:
            return parts

    # Try " and " split (case-insensitive, word boundary)
    m = re.split(r'\s+(?:and|et|und|y|e)\s+', artist, flags=re.IGNORECASE)
    if len(m) > 1:
        return [a.strip() for a in m if a.strip()]

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

    # Use albumartist first (main artist of the album), fall back to artist tag.
    # The artist tag often contains featured guests like "Eminem (feat. Dr. Dre)"
    # which would create unnecessary duplicates.
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


def _normalize_name(name: str) -> str:
    """Lowercase, expand punctuation to spaces, strip non-alnum, collapse whitespace."""
    n = name.lower()
    n = n.replace("/", " ").replace("-", " ").replace("&", " and ")
    n = re.sub(r"[^a-z0-9\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _compact(name: str) -> str:
    """Strip ALL non-alphanumeric characters.  Catches pure-punctuation differences
    like 'AC/DC' vs 'ACDC', 'Jay-Z' vs 'Jay Z'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


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
            result[name] = ArtistContext(
                album_dirs=existing.album_dirs | ctx.album_dirs,
                albums=existing.albums | ctx.albums,
                genres=existing.genres | ctx.genres,
                track_names=existing.track_names | ctx.track_names,
                album_track_counts=merged_counts,
                album_years={**existing.album_years, **ctx.album_years},
            )
        else:
            result[name] = ArtistContext(
                album_dirs=set(ctx.album_dirs),
                albums=set(ctx.albums),
                genres=set(ctx.genres),
                track_names=set(ctx.track_names),
                album_track_counts=dict(ctx.album_track_counts),
                album_years=dict(ctx.album_years),
            )

    for name, ctx in artists.items():
        if name in aliases:
            canonical = merge_map[name]
            _merge_into(canonical, ctx)
        else:
            _merge_into(name, ctx)

    return result
