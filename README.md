# Artist Art Downloader

Desktop GUI application for batch-downloading artist cover art from streaming platforms. Scans a local music library, extracts artist names from audio file tags (ID3, FLAC, Vorbis), searches Apple Music and Deezer for matching artist images, and saves them to disk.

No command-line interface. All interaction is through a Tkinter GUI.

---

## Features

### Library Scanning

- Recursively walks a directory tree via `Path.rglob()`, detecting audio files by extension: `.mp3`, `.flac`, `.ogg`, `.m4a`, `.wma`, `.aiff`, `.aif`
- Skips symlinks, permission errors, and non-audio files automatically
- Album directory detection walks up to 5 parent levels looking for a directory containing audio files
- Compilation album detection (Various Artists in multiple languages: English, Spanish, German, French, Italian, Portuguese) -- compilation tracks are skipped entirely
- Artist root determination prevents saving images above the scan root or in the root itself

### Metadata Extraction

- Reads artist, album, genre, year, and track title via TinyTag
- Prefers `albumartist` tag over `artist` tag (the latter often contains featured guests like "Eminem (feat. Dr. Dre)" which would create false artist entries)
- Falls back to filename parsing when tags are missing or corrupted
- Filename patterns handled: `"ArtistName - Song Title.mp3"`, `"01 ArtistName - Song Title.mp3"`, `"01. ArtistName - Song Title.mp3"`, `"01 - ArtistName - Song Title.mp3"`, `"ArtistName.mp3"`

### Multi-Artist Tag Handling

- Detects multiple artists in a single tag field (e.g., `"Eminem, Dr. Dre"`, `"Artist1 & Artist2"`)
- Presents a selection dialog letting the user choose which artist to search for
- Splits by: commas, ampersands, conjunctions (`and`, `et`, `und`, `y`, `e`), and collaboration markers (`feat.`, `ft.`, `featuring`)

### Artist Name Normalization

- Strips collaboration markers: `feat.`, `ft.`, `featuring`, `vs.`, `with`, `w/`, `presents`, `prod.`, `and`, `&`
- Strips comma-separated collaborators: `"Eminem, Dr. Dre"` becomes `"Eminem"`
- Strips parenthesized collaborations: `"(feat. Guest)"` becomes `""` (empty -- artist name from tag is used instead)
- Normalizes conjunctions (`and`, `et`, `und`, `y`, `e`) to a canonical form for comparison
- Accent-insensitive comparison via NFKD decomposition
- Traditional-to-simplified Chinese conversion for consistent matching
- Cross-script transliteration for comparison (Cyrillic, Japanese Kana, Korean Hangul, common Chinese characters)

### Search Strategy

Uses a 6-level fallback pipeline, from most specific to least:

1. **Album + year context search** -- searches by album name and year (top 5 albums by track count), verifying both album name and artist name match exactly
2. **Track + artist search** -- searches by track name and artist (top 5 tracks), verifying both match exactly
3. **Direct artist name search** -- searches by artist name alone with genre filtering as a soft preference
4. **Track-only fallback** -- searches by track title only (no artist constraint), requires 100% exact track title match, accepts artist if names share at least one significant word
5. **Album-only fallback** -- same logic as track-only but with album titles
6. **Candidate picker** -- if multiple artists share the same name, presents a dialog with genre context and image previews for the user to select

Each search level uses `expand_and_variants()` for bidirectional accent handling:
- Accent-stripped variants (e.g., `"Roger Fakhr"` without accent)
- Accent-adding variants for short queries (up to 5 variants, limited to queries with 3 or fewer words)
- `and`-to-`&` and `&`-to-`and` swap variants
- Hard cap of 8 variants per query to avoid API flooding

### Name Matching

Two matching strategies:

- **Exact match** (`names_match_exact`): accent-insensitive, case-insensitive comparison with progressive suffix stripping (parentheticals like `(Remastered)`, brackets like `[Deluxe]`, dashes like `- 2024`, and version keywords like `remastered`, `deluxe`, `explicit`). Also performs cross-script comparison via transliteration.
- **Fuzzy match** (`names_match_fuzzy`): transliterates both names to Latin and checks if the shorter name is fully contained in the longer name. Names shorter than 4 characters require exact match to avoid false positives.

### Genre Filtering

- Compares local genre tags against API-reported genres
- Handles compound genre strings (e.g., `"Hip-Hop/Rap"` vs `"Hip Hop"`)
- Splits on non-alphanumeric characters and checks word overlap
- Substring containment check for partial matches (e.g., `"hiphop"` in `"hiphoprap"`)
- Soft preference: if no local genres or no API genre, assumes compatibility

### Image Download

- Multi-threaded download with `ThreadPoolExecutor` (4 workers)
- Validates image format by magic bytes: JPEG (`\xff\xd8`), PNG (`\x89PNG`), WebP (`RIFF...WEBP`)
- Rejects non-image responses (HTML error pages, captchas)
- Streaming download via `iter_content()` with 8KB chunks
- Content-Length validation: rejects zero-length and files exceeding 20 MB
- Optional JPEG conversion for any source format (configurable quality, 10-100)
- Optional PNG conversion for JPEG sources
- Automatic downscaling for images exceeding 1500px on the longest side (LANCZOS resampling)
- Known Deezer placeholder URLs are rejected (patterns: `"15627e72e2e2be8e5e5e5e5e5e5e5e5e"`, `"placeholder"`, `"default"`)
- Known Apple Music logo/placeholder patterns are rejected (`"apple-music"`, `"og-image"`, `"newsroom/images"`, `"apple_logo"`)
- Apple Music og:image URLs are scaled to largest size (`3000x3000-999`)
- iTunes artwork URLs are scaled from `100x100` to `600x600`
- Deezer artist images prefer `picture_xl`, falling back to `picture_big`

### Artist Merging

- Detects similar artist names using `difflib.SequenceMatcher` (cutoff: 0.7 similarity)
- Examples: `"Big Pun"` vs `"Big Punisher"`, `"Radiohead"` vs `"Radiohead The"`
- Dialog shows each group with radio buttons to select the canonical name
- Displays album and genre context for each candidate
- Optional "Don't merge" checkbox per group
- Option to save merge choices as permanent aliases in settings

### Filename Sanitization

- Removes null bytes, invalid characters (`<>:"/\|?*`), and path traversal sequences (`..`)
- Handles Windows reserved names: `CON`, `NUL`, `PRN`, `AUX`, `COM1`-`COM9`, `LPT1`-`LPT9`
- Prevents empty or dots-only names (would resolve to current directory)
- Filename length capped at 200 characters

### Caching

- Artist image URL cache stored in `~/.config/artist_art_downloader/artist_cache.json`
- Cache entries expire after 7 days
- Thread-safe via a re-entrant lock
- Atomic config writes (tmp file + rename) to prevent corruption on crash
- Cache survives application restarts

### HTTP Client

- Reusable `requests.Session` with connection pooling (closed on exit via `atexit`)
- Rate limiting: 150ms minimum interval between requests to the same host
- User-Agent rotation across 4 different browser strings
- Exponential backoff with jitter on 429 (Too Many Requests) and 5xx server errors
- 3 retries per request; returns `None` after exhaustion
- Per-operation timeouts:
  - API search: 10s
  - Deezer artist detail: 5s
  - Apple Music page load: 10s
  - Image download: 30s

### Apple Music Integration

- iTunes Search API for artist/album/track lookup
- Apple Music artist page scraping for og:image meta tag
- Page validation: checks og:title contains the artist name (or romanized slug for non-Latin scripts)
- Handles double-encoded UTF-8 in og:title (e.g., `"GarA?ons"` becomes `"Garcons"`)

### Transliteration

- **Cyrillic** (Russian, Ukrainian, etc.): full character-by-character mapping (e.g., `"Кино"` to `"kino"`)
- **Japanese Hiragana**: full mapping including dakuten (voiced), handakuten (semi-voiced), and multi-character sequences (e.g., `"kya"`, `"sha"`, `"cha"`)
- **Japanese Katakana**: same coverage as Hiragana
- **Korean Hangul**: syllable decomposition to Jamo (manual Unicode arithmetic, not full NFD), then Jamo-to-romanization mapping including jongseong (final consonants)
- **Chinese**: common surname/artist-name characters mapped to pinyin (e.g., `"周"` to `"zhou"`, `"杰"` to `"jie"`)
- Multi-character sequences (e.g., `"kya"`, `"sha"`) are applied before single-character maps
- Traditional Chinese is converted to simplified before transliteration

### User Interface

- Tkinter GUI with ttk themed widgets
- 5 color themes: Gruvbox, Catppuccin, Light, Midnight, Dracula
- Real-time progress bar with determinate mode (percentage-based)
- Scrollable log with color-coded messages: success (green), error (red), warning (yellow), info (blue), skip (gray)
- Inline image preview thumbnails (48x48) in the log after each download
- Keyboard shortcuts: Enter to start, Escape to stop
- Window geometry saved between sessions (position and size)
- Minimizes to system tray (pystray) instead of taskbar, with Show/Quit context menu
- Settings dialog for source selection, theme, output format, JPEG quality, filename mode, separate folder, and merge dialog skip

---

## Supported Platforms

- **Apple Music**: Uses iTunes Search API (`https://itunes.apple.com/search`) and Apple Music artist page scraping (`https://music.apple.com/us/artist/`) for og:image extraction. No API key required.
- **Deezer**: Uses Deezer public API (`https://api.deezer.com/`). No API key required.

---

## Prerequisites

- Python 3.10 or later (uses `list[...]` type hints in function signatures, `str.removeprefix`)
- Windows, macOS, or Linux (tested on Windows 11)
- Internet connection for API access

### Python Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `tinytag` | >=1.10.0 | Audio metadata extraction (ID3, FLAC, Vorbis, etc.) |
| `requests` | >=2.31.0 | HTTP client for API calls and image downloads |
| `Pillow` | >=10.0.0 | Image format conversion, resizing, and format detection |
| `pystray` | >=0.19.5 | System tray icon functionality |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/subflame/ArtistArtDownloader.git
cd ArtistArtDownloader

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

### Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller ArtistArtDownloader.spec --clean
```

The executable will be written to `dist/ArtistArtDownloader.exe`. The `.spec` file excludes numpy, pandas, scipy, matplotlib, setuptools, and pkg_resources. The `pystray` module is included as a hidden import.

---

## Usage

The application has a graphical interface with no command-line arguments. All settings are configured through the GUI.

### Basic Workflow

1. Launch the application (`python run.py` or the built executable).
2. Click **Browse** and select a folder containing audio files.
3. Optionally check **Skip artists with existing artist.jpg** to avoid re-downloads.
4. Click **Start**.
5. The application scans the folder, searches for images, and downloads them.
6. Results appear in the log panel with color-coded status and inline thumbnail previews.

### Multi-Artist Tags

When the scanner encounters a tag containing multiple artists (e.g., `"Eminem, Dr. Dre"` or `"Artist1 & Artist2"`), a dialog appears listing the alternatives. Select which artist to search for, or skip the entry entirely.

### Artist Merging

If the scanner detects similar artist names (e.g., `"Big Pun"` and `"Big Punisher"`), a merge dialog appears. Select the canonical name for each group, or mark groups to keep separate. Optionally save choices as permanent aliases.

### Settings

Accessible via the **Settings** button in the top-right corner.

**Image source**
- Apple Music (recommended) -- searches iTunes Search API and scrapes og:image from Apple Music artist pages.
- Deezer -- searches the Deezer API for artist pictures.

**Theme**
- Gruvbox, Catppuccin, Light, Midnight, Dracula

**Output format**
- JPEG (.jpg) -- default, adjustable quality (10-100 via slider).
- PNG (.png) -- converts JPEG sources to PNG; saves PNG sources as-is.

**Use artist name as filename** -- saves as `"ArtistName.jpg"` instead of `"artist.jpg"`. Automatically disabled when "Save to separate folder" is active.

**Skip merge dialog** -- automatically applies saved artist aliases without prompting.

**Save to separate folder** -- all images are written to a single directory instead of alongside album folders. Filenames always use the artist name in this mode.

---

## Configuration

Settings are persisted to `~/.config/artist_art_downloader/settings.json`.

```json
{
  "theme": "gruvbox",
  "source": "apple_music",
  "skip_existing": true,
  "last_folder": "/path/to/music",
  "window_width": 720,
  "window_height": 580,
  "window_x": -1,
  "window_y": -1,
  "artist_filename": true,
  "separate_folder": "",
  "output_format": "jpeg",
  "jpeg_quality": 85,
  "artist_aliases": {
    "Big Pun": "Big Punisher"
  },
  "skip_merge_dialog": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `theme` | string | `"gruvbox"` | UI theme name |
| `source` | string | `"apple_music"` | Image source: `"apple_music"` or `"deezer"` |
| `skip_existing` | bool | `true` | Skip artists with existing image files |
| `last_folder` | string | `""` | Last browsed folder (restored on launch) |
| `window_width` | int | `720` | Window width in pixels |
| `window_height` | int | `580` | Window height in pixels |
| `window_x` | int | `-1` | Window X position (-1 = centered) |
| `window_y` | int | `-1` | Window Y position (-1 = centered) |
| `artist_filename` | bool | `true` | Use artist name as filename |
| `separate_folder` | string | `""` | Separate output folder path (empty = disabled) |
| `output_format` | string | `"jpeg"` | Output format: `"jpeg"` or `"png"` |
| `jpeg_quality` | int | `85` | JPEG quality (10-100) |
| `artist_aliases` | object | `{}` | Saved artist name merges (`"alias" -> "canonical"`) |
| `skip_merge_dialog` | bool | `true` | Auto-apply aliases without prompting |

The artist image URL cache is stored in `~/.config/artist_art_downloader/artist_cache.json` and expires after 7 days.

No environment variables or API keys are required. Both Apple Music and Deezer APIs are public.

---

## How It Works

1. **Scan phase**: `scan_folder()` walks the directory tree, reads audio tags via TinyTag, groups metadata by artist name into `ArtistContext` objects containing albums, genres, track names, and filesystem paths.
2. **Alias phase**: Saved artist aliases are applied. Similar names are detected via `difflib.SequenceMatcher` and optionally merged by the user.
3. **Multi-artist phase**: Tags with multiple artists are split and resolved via a user-selection dialog.
4. **Search phase**: For each artist, the application executes a 6-level fallback search pipeline against the selected API (album context, track context, direct name, track-only, album-only, candidate picker). Each level respects genre filtering and accent-insensitive matching.
5. **Download phase**: Found image URLs are downloaded in parallel (4 threads), validated by format detection, optionally converted, resized, and saved to disk.
6. **Cache phase**: Successfully found URLs are cached for 7 days to avoid redundant API lookups on subsequent runs.

The GUI runs the search phase on a background thread, with the main thread handling UI updates via `after()` callbacks. Dialogs (artist choice, multi-artist, merge) are shown from the background thread via `threading.Event` synchronization.

---

## Troubleshooting

### Rate Limiting (429 Too Many Requests)

The client includes automatic retry with exponential backoff (1s, 2s, 4s) plus jitter. After 3 retries, the request is abandoned. The rate limiter enforces a 150ms minimum interval between requests to the same host. If you consistently hit rate limits, reduce the `_RATE_LIMIT_DELAY` constant in `fetcher.py` (default 0.15s).

For bulk discography fetches, the Deezer pagination loop stops after 2 consecutive 429 responses or 3 consecutive network errors.

### Connection Timeouts

Timeouts are configured per operation type:
- API searches: 10s
- Deezer artist detail lookups: 5s
- Apple Music page loads: 10s
- Image downloads: 30s

Adjust these in `fetcher.py` if you are on a slow connection.

### No Images Found for an Artist

- Verify the artist name in the audio file tags.
- Check that the streaming platform has the artist (some independent artists may not be listed).
- Try switching the source between Apple Music and Deezer.
- If the artist name includes collaboration markers (`"feat."`, `"&"`, `"and"`), they are stripped before searching. Create a permanent alias in Settings to map the full name to the correct search name.
- The application tries accent-stripped and accent-adding variants automatically, but unusual romanizations may still fail.

### Corrupted or Missing Tags

If audio files have missing or unreadable tags, the application falls back to parsing the filename. Supported patterns: `"ArtistName - Song Title.mp3"`, `"01 ArtistName - Song Title.mp3"`, `"01. ArtistName - Song Title.mp3"`.

### Application Window Does Not Appear After Minimize

The application minimizes to the system tray instead of the taskbar. Look for the icon in the system tray notification area. Double-click the icon or right-click and select **Show** to restore the window.

### PyInstaller Build Fails on Python 3.14

Clear the `__pycache__` directory before building. The `run.py` launcher automatically clears stale `__pycache__` on startup to prevent surrogate encoding errors on Python 3.14. When building with PyInstaller, run with `--clean` flag.

---

## License

MIT License
