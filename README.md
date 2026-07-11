# Artist Art Downloader

A desktop tool that scans your music library, reads artist tags from audio files, finds artist images via Apple Music and Deezer APIs, and saves them alongside your albums.

---

## Features

- **Auto-scan** — recursively scans folders for MP3/FLAC/OGG/M4A files
- **Tag reading** — extracts artist, album, genre, year and track name via TinyTag
- **Smart search** — searches by album → track → name (most to least specific)
- **Collab stripping** — `"Eminem feat. Dr. Dre"`, `"Quasimoto & Madlib"`, `"Artist1, Artist2"` → first artist only
- **Two sources** — Apple Music (recommended) and Deezer, switchable in settings
- **Caching** — results cached for 7 days to avoid hammering APIs
- **5 themes** — Gruvbox, Catppuccin, Light, Midnight, Dracula
- **System tray** — minimizes to tray instead of taskbar
- **Output formats** — JPEG and PNG, adjustable JPEG quality
- **Separate folder** — save all images to a single folder
- **Artist merging** — detects similar names (`"Big Pun"` ↔ `"Big Punisher"`)
- **Transliteration** — Cyrillic, Japanese, Chinese, Korean → Latin (for URLs)
- **Multi-threaded download** — 4 parallel workers
- **Skip existing** — doesn't re-download images that already exist

---

## Installation

### Option 1: Download .exe

Grab `ArtistArtDownloader.exe` from the [releases page](https://github.com/subflame/nukkiapps/releases) — no installation needed.

### Option 2: Run from source

```bash
git clone https://github.com/subflame/nukkiapps.git
cd nukkiapps
pip install -r requirements.txt
python run.py
```

### Build .exe yourself

```bash
pip install pyinstaller
pyinstaller ArtistArtDownloader.spec --clean
```

The .exe will be in `dist/`.

---

## Usage

1. **Launch** the app (ArtistArtDownloader.exe or `python run.py`)
2. **Pick a folder** with music (Browse button)
3. **Choose source** (Apple Music / Deezer) in Settings
4. **Hit Start** — it scans the folder and starts searching
5. **Done** — images are saved as `ArtistName.jpg` next to the album folders

### Save format

By default images are saved as `{ArtistName}.jpg` (or `artist.jpg` if the option is off).

You can enable **separate folder** in settings — all images go there as `{ArtistName}.jpg/.png`.

---

## Requirements

- **Python 3.10+** (if running from source)
- **Windows / macOS / Linux**
- Dependencies: `tinytag`, `requests`, `Pillow`, `pystray`

---

## Project structure

```
artist_art_downloader/
  __init__.py          # Package version
  main.py              # Entry point (dependency check)
  config.py            # Settings, themes, cache (JSON)
  utils.py             # Name normalization, filename sanitization
  scanner.py           # Folder scanning, tag reading, artist merging
  fetcher.py           # HTTP client, Apple Music / Deezer API, downloads
  gui.py               # Tkinter GUI + system tray
  translit_maps.py     # Transliteration tables for URL slug generation

run.py                   # Launch script
ArtistArtDownloader.spec # PyInstaller config
```

---

## How it works

### Image search

The app uses **public APIs** (no keys required):
- **Deezer API** — search artists by name, filter by genre
- **iTunes Search API** — search by album/track, get artistId
- **Apple Music** — parse og:image from the artist's web page

### Artist name cleanup

Before searching, collaboration markers are stripped:
- `feat.`, `ft.`, `featuring`, `f.`
- `&`, `and` (and equivalents in other languages)
- `vs.`, `with`, `w/`, `presents`, `prod.`
- Commas (`"Eminem, Dr. Dre"` → `"Eminem"`)
- Parenthesized collabs (`"(feat. Guest)"`)

### Transliteration

Non-Latin names (Cyrillic, CJK) are transliterated when building Apple Music URLs.

---

## License

MIT
