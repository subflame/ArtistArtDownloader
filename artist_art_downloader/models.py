"""Data structures for artist discography: Artist -> Albums -> Tracks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    """A single track within an album."""

    title: str
    position: int = 0
    cover_url: Optional[str] = None
    duration_secs: int = 0
    disk_number: int = 1


@dataclass
class Album:
    """An album by an artist, containing tracks and a cover URL."""

    title: str
    year: str = ""
    cover_url: Optional[str] = None
    tracks: list[Track] = field(default_factory=list)
    deezer_id: Optional[int] = None
    itunes_id: Optional[int] = None

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    @property
    def display_title(self) -> str:
        """Album title with optional year suffix for folder naming."""
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title


@dataclass
class Artist:
    """An artist with their full discography."""

    name: str
    albums: list[Album] = field(default_factory=list)
    cover_url: Optional[str] = None
    deezer_id: Optional[int] = None
    itunes_id: Optional[int] = None

    @property
    def album_count(self) -> int:
        return len(self.albums)

    @property
    def total_tracks(self) -> int:
        return sum(a.track_count for a in self.albums)