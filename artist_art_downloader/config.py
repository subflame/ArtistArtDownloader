"""Application configuration and settings."""

import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "artist_art_downloader"
CONFIG_FILE = CONFIG_DIR / "settings.json"
CACHE_FILE = CONFIG_DIR / "artist_cache.json"
CACHE_TTL = 7 * 24 * 3600  # 7 days

THEMES = {
    "gruvbox": {
        "bg": "#282828",
        "bg_secondary": "#3c3836",
        "bg_hover": "#504945",
        "fg": "#ebdbb2",
        "fg_dim": "#7c6f64",
        "accent": "#458588",
        "accent_hover": "#83a598",
        "success": "#98971a",
        "error": "#cc241d",
        "warning": "#d79921",
        "border": "#665c54",
        "entry_bg": "#504945",
        "entry_fg": "#ebdbb2",
        "button_bg": "#458588",
        "button_fg": "#282828",
        "list_bg": "#282828",
        "list_select": "#665c54",
        "scrollbar": "#7c6f64",
    },
    "catppuccin": {
        "bg": "#1e1e2e",
        "bg_secondary": "#181825",
        "bg_hover": "#313244",
        "fg": "#cdd6f4",
        "fg_dim": "#6c7086",
        "accent": "#89b4fa",
        "accent_hover": "#b4befe",
        "success": "#a6e3a1",
        "error": "#f38ba8",
        "warning": "#f9e2af",
        "border": "#45475a",
        "entry_bg": "#313244",
        "entry_fg": "#cdd6f4",
        "button_bg": "#89b4fa",
        "button_fg": "#1e1e2e",
        "list_bg": "#11111b",
        "list_select": "#45475a",
        "scrollbar": "#585b70",
    },
    "light": {
        "bg": "#eff1f5",
        "bg_secondary": "#e6e9ef",
        "bg_hover": "#ccd0da",
        "fg": "#4c4f69",
        "fg_dim": "#7c7f93",
        "accent": "#1e66f5",
        "accent_hover": "#209fb5",
        "success": "#40a02b",
        "error": "#d20f39",
        "warning": "#df8e1d",
        "border": "#ccd0da",
        "entry_bg": "#ccd0da",
        "entry_fg": "#4c4f69",
        "button_bg": "#1e66f5",
        "button_fg": "#ffffff",
        "list_bg": "#eff1f5",
        "list_select": "#ccd0da",
        "scrollbar": "#9ca0b0",
    },
    "midnight": {
        "bg": "#0d1117",
        "bg_secondary": "#161b22",
        "bg_hover": "#21262d",
        "fg": "#c9d1d9",
        "fg_dim": "#8b949e",
        "accent": "#58a6ff",
        "accent_hover": "#79c0ff",
        "success": "#3fb950",
        "error": "#f85149",
        "warning": "#d29922",
        "border": "#30363d",
        "entry_bg": "#21262d",
        "entry_fg": "#c9d1d9",
        "button_bg": "#58a6ff",
        "button_fg": "#0d1117",
        "list_bg": "#0d1117",
        "list_select": "#21262d",
        "scrollbar": "#484f58",
    },
    "dracula": {
        "bg": "#282a36",
        "bg_secondary": "#343746",
        "bg_hover": "#44475a",
        "fg": "#f8f8f2",
        "fg_dim": "#6272a4",
        "accent": "#bd93f9",
        "accent_hover": "#ff79c6",
        "success": "#50fa7b",
        "error": "#ff5555",
        "warning": "#f1fa8c",
        "border": "#44475a",
        "entry_bg": "#44475a",
        "entry_fg": "#f8f8f2",
        "button_bg": "#bd93f9",
        "button_fg": "#282a36",
        "list_bg": "#282a36",
        "list_select": "#44475a",
        "scrollbar": "#6272a4",
    },
}


@dataclass
class Settings:
    theme: str = "gruvbox"
    source: str = "apple_music"
    skip_existing: bool = True
    last_folder: str = ""
    window_width: int = 720
    window_height: int = 580
    window_x: int = -1
    window_y: int = -1
    artist_filename: bool = True
    separate_folder: str = ""
    output_format: str = "jpeg"  # "jpeg" or "png"
    jpeg_quality: int = 85       # 1-100, only for JPEG
    artist_aliases: dict[str, str] = field(default_factory=dict)
    skip_merge_dialog: bool = True

    def save(self) -> None:
        """Persist current settings to JSON config file.

        Creates the config directory and file if they don't exist.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from JSON config file, or return defaults.

        Silently ignores unknown fields and recovers from corrupt JSON.

        Returns:
            Settings instance with saved values (or defaults if no file).
        """
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    @staticmethod
    def _resolve_theme(name: str) -> str:
        """Resolve theme name, handling backward-compatible aliases."""
        aliases = {
            "dark": "gruvbox",  # old "dark" was renamed to gruvbox
        }
        return aliases.get(name, name)

    def get_theme(self) -> dict:
        resolved = self._resolve_theme(self.theme)
        return THEMES.get(resolved, THEMES["gruvbox"])


class ArtistCache:
    """JSON cache for artist image URLs. Avoids redundant API lookups.

    Cached entries expire after CACHE_TTL seconds (default 7 days).
    Thread-safe via a re-entrant lock.
    """

    def __init__(self) -> None:
        """Initialize empty cache, then load from disk if available."""
        self._data: dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Read cache JSON from disk, preserving existing data on error."""
        if CACHE_FILE.exists():
            try:
                self._data = json.loads(CACHE_FILE.read_text())
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def save(self) -> None:
        """Write cache data to disk as JSON."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self._data, indent=2))

    def get(self, artist_name: str, source: str) -> Optional[str]:
        """Return cached image URL if fresh enough, else None."""
        key = f"{artist_name}|{source}"
        with self._lock:
            entry = self._data.get(key)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > CACHE_TTL:
            return None
        return entry.get("url")

    def put(self, artist_name: str, source: str, img_url: str):
        key = f"{artist_name}|{source}"
        with self._lock:
            self._data[key] = {"url": img_url, "ts": time.time()}

    def clear(self):
        with self._lock:
            self._data = {}
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
