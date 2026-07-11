# Artist Art Downloader

A desktop application that scans music libraries, reads artist metadata from audio file tags, searches for artist images on Apple Music and Deezer, and saves them to disk. Uses a Tkinter GUI — no command-line interface.

---

## About

Artist Art Downloader processes a folder of audio files, extracts artist names from ID3/FLAC/Vorbis tags, searches for matching artist images across two streaming platforms (Apple Music and Deezer), and saves the images as JPEG or PNG files alongside the album directories. The application handles collaboration markers (feat., &, and), non-Latin script transliteration, genre-based disambiguation, and HTTP rate limiting.

Supported sources:
- Apple Music (iTunes Search API + Apple Music page scraping for og:image)
- Deezer (Deezer API)

---

## Features

**Library scanning**
- Recursively walks a folder tree using `Path.rglob()`
- Detects audio files by extension: .mp3, .flac, .ogg, .m4a, .wma, .aiff, .aif
- Skips symlinks, permission errors, and non-audio files
- Album directory auto-detection (walks up to 5 parent levels looking for audio content)

**Metadata extraction**
- Reads artist, album, genre, year, and track title via TinyTag
- Falls back to filename parsing when tags are missing or corrupted
- Detects compilation albums (Various Artists) and skips them

**Artist name normalization**
- Strips collaboration markers: feat., ft., featuring, f., vs., with, w/, presents, prod., and, &
- Strips comma-separated collaborators: "Eminem, Dr. Dre" -> "Eminem"
- Strips parenthesized collabs: "(feat. Guest)" -> ""
- Normalizes conjunctions (and, et, und, y, e) for matching
- Accent-insensitive comparison via NFKD decomposition

**Image search**
- Search order by specificity: album name + year -> track name -> artist name
- Year-aware album search: tries without year first, retries with year
- Genre filtering: rejects API results whose genre doesn't overlap with local tags
- Supports "and"/"&" query variants for broader API matching
- Caches results for 7 days (JSON file in ~/.config/artist_art_downloader/)

**Multi-candidate resolution**
- When multiple artists share the same name, shows a dialog with genre context and image previews
- Preview thumbnails are fetched asynchronously in a background thread
- Selected artist ID is cached for subsequent runs

**Artist merging**
- Detects similar names via difflib SequenceMatcher (e.g. "Big Pun" vs "Big Punisher")
- Dialog to review and merge duplicate artists
- Merged album/year/genre data from both names
- User can save aliases permanently

**Image download**
- Multi-threaded download with ThreadPoolExecutor (4 workers)
- Validates Content-Type (must start with "image/") and Content-Length (max 20 MB, rejects zero-length)
- Format detection by magic bytes: JPEG, PNG, WebP
- Optional JPEG conversion for any source format
- Optional PNG conversion for JPEG sources
- Adjustable JPEG quality (10-100, default 85)
- Downscales images exceeding 1500px on the longest side (LANCZOS resampling)
- Rejects known Deezer placeholder URLs

**File management**
- Filename sanitization: removes null bytes, invalid characters (<>:"/\|?*), path traversal sequences (".."), Windows reserved names (CON, NUL, PRN, LPT1-9, COM1-9)
- Filename length capped at 200 characters
- Empty or dots-only names fall back to "unknown_artist"
- Two naming modes: artist name (e.g. "Pink Floyd.jpg") or generic "artist.jpg"
- Optional separate output folder for all images
- Skip mode: checks for existing artist.jpg/artist.png before processing

**HTTP client**
- Reusable requests.Session with connection pooling
- Rate limiting: 150ms minimum interval between requests to the same host
- User-Agent rotation across 4 different strings
- Exponential backoff with jitter on 429 (Too Many Requests) and 5xx errors
- 3 retries per request; returns None after exhaustion
- Per-operation timeouts: search 10s, Deezer detail 5s, Apple Music page 10s, download 30s
- Session closed on exit via atexit handler

**Transliteration**
- Cyrillic, Japanese hiragana/katakana, Korean hangul, and common Chinese characters mapped to Latin equivalents
- Multi-character sequences (e.g. "きゃ" -> "kya") applied before single-character maps
- Used to build Apple Music URL slugs for non-Latin artist names

**User interface**
- Tkinter GUI with ttk themed widgets
- 5 color themes: Gruvbox, Catppuccin, Light, Midnight, Dracula
- Real-time progress bar and status updates
- Scrollable log with color-coded messages (success, error, warning, info, skip)
- Inline image preview thumbnails in the log after each download
- Keyboard shortcuts: Enter to start, Escape to stop
- Window geometry saved between sessions
- Minimizes to system tray instead of taskbar (pystray)

---

## Prerequisites

- Python 3.10 or later (uses `str.removeprefix` and structural pattern matching is not used, but type hint syntax requires 3.10+)
- Windows, macOS, or Linux (tested on Windows 11)
- Internet connection for API access

---

## Installation

```bash
# Clone the repository
git clone https://github.com/subflame/nukkiapps.git
cd nukkiapps

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

To build a standalone executable:

```bash
pip install pyinstaller
pyinstaller ArtistArtDownloader.spec --clean
```

The executable will be written to `dist/ArtistArtDownloader.exe`.

---

## Usage

The application has a graphical interface — no command-line arguments. All settings are configured through the GUI.

### Basic workflow

1. Launch the application.
2. Click Browse and select a folder containing audio files.
3. Optionally check "Skip artists with existing artist.jpg" to avoid re-downloads.
4. Click Start.
5. The application scans the folder, searches for images, and downloads them.
6. Results appear in the log panel with color-coded status.

### Settings

Accessible via the Settings button in the top-right corner.

**Image source**
- Apple Music (recommended) — searches iTunes Search API and scrapes og:image from Apple Music artist pages.
- Deezer — searches the Deezer API for artist pictures.

**Theme**
- Gruvbox, Catppuccin, Light, Midnight, Dracula

**Output format**
- JPEG (.jpg) — default, adjustable quality.
- PNG (.png) — converts JPEG sources to PNG; saves PNG sources as-is.

**JPEG quality** (1-100) — shown only when JPEG format is selected.

**Save to separate folder** — all images are written to a single directory instead of alongside album folders. When enabled, filenames always use the artist name.

**Use artist name as filename** — saves as "ArtistName.jpg" instead of "artist.jpg".

**Skip merge dialog** — automatically applies saved artist aliases without prompting.

### Artist merging

If the scanner detects similar artist names (e.g. "Big Pun" and "Big Punisher"), it shows a merge dialog. You can select which name to keep and optionally save the mapping as a permanent alias.

### Multiple artist selection

If the API returns multiple artists with the same name (e.g. different artists called "Guf"), a dialog shows all candidates with genre information and an image preview. Select the correct one to proceed.

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

The artist image URL cache is stored in `~/.config/artist_art_downloader/artist_cache.json` and expires after 7 days.

No environment variables or API keys are required — both Apple Music and Deezer APIs are public.

---

## How it works

1. Scan phase: `scan_folder()` walks the directory tree, reads audio tags via TinyTag, groups metadata by artist.
2. Alias phase: saved aliases are applied, similar names are detected and optionally merged.
3. Search phase: for each artist, the application searches the selected API (album -> track -> name), respecting genre filters.
4. Download phase: found image URLs are downloaded in parallel (4 threads), validated, optionally converted, and saved to disk.

The GUI runs the search phase on a background thread, with the main thread handling UI updates via `after()` callbacks. The download phase uses `ThreadPoolExecutor` for parallel HTTP requests.

---

## Troubleshooting

**Rate limiting (429 Too Many Requests)**
The client includes automatic retry with exponential backoff (1s, 2s, 4s) plus jitter. After 3 retries, the request is abandoned. If you consistently hit rate limits, consider reducing the `_RATE_LIMIT_DELAY` constant in `fetcher.py` (default 0.15s).

**Connection timeouts**
Timeouts are configured per operation type: 10s for API searches, 5s for detail lookups, 10s for Apple Music page loads, 30s for image downloads. If you are on a slow connection, these can be adjusted in `fetcher.py`.

**No images found for an artist**
- Verify the artist name in the audio file tags.
- Check that the streaming platform has the artist (some independent artists may not be listed).
- Try switching the source between Apple Music and Deezer.
- If the artist name includes collaboration markers ("feat.", "&", "and"), they are stripped before searching. Create a permanent alias in Settings to map the full name to the correct search name.

**Corrupted or missing tags**
If audio files have missing or unreadable tags, the application falls back to parsing the filename. Supported patterns: "ArtistName - Song Title.mp3", "01 ArtistName - Song Title.mp3", "01. ArtistName - Song Title.mp3".

**Application window doesn't appear after minimize**
The application minimizes to the system tray instead of the taskbar. Look for the icon in the system tray notification area. Double-click the icon or right-click and select Show to restore the window.

---

## License

MIT License
