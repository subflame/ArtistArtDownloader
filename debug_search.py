"""Diagnostic script for ArtistArtDownloader search pipeline.

Run from project root:
    python debug_search.py "Roger Fakhr"
    python debug_search.py "Roger Fakhr" --source deezer
    python debug_search.py "Roger Fakhr" --album "Some Album" --track "Some Track"
    python debug_search.py "Beyonce"
    python debug_search.py "P?nico"

Shows exactly what queries are sent, what the API returns, and why
each result is accepted or rejected at each search step.
"""
import sys
import os
import json
import argparse
import time

# Ensure project root is on path
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import requests
from artist_art_downloader.utils import (
    normalize_name, names_match_exact, strip_accents,
    expand_and_variants, add_accent_variants,
    _strip_suffixes,
)
from artist_art_downloader.fetcher import _slugify, _artist_names_share_word


def _api_get(url, params=None, timeout=10):
    """Direct HTTP GET with User-Agent, returns (status_code, json_dict_or_None)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        try:
            data = resp.json()
        except Exception:
            data = None
        return resp.status_code, data
    except requests.RequestException as e:
        return None, str(e)


def diag(name: str, source: str, album: str = "", track: str = "", genres: str = ""):
    print(f"\n{'='*60}")
    print(f"  Artist: {name!r}")
    print(f"  Source: {source}")
    if album:  print(f"  Album:  {album!r}")
    if track:  print(f"  Track:  {track!r}")
    if genres: print(f"  Genres: {genres!r}")
    print(f"{'='*60}")

    genre_set = {g.strip() for g in genres.split(",") if g.strip()} if genres else set()

    # --- Normalize check ---
    norm = normalize_name(name)
    stripped = strip_accents(name)
    print(f"\n  normalize_name: {name!r} -> {norm!r}")
    print(f"  strip_accents:  {name!r} -> {stripped!r}")
    print(f"  _slugify:       {name!r} -> {_slugify(name)!r}")
    if stripped != name:
        print(f"  ** Accent variant available: {stripped!r}")
    else:
        print(f"  ** NO stripped accent variant (input has no accents)")

    # --- add_accent_variants ---
    accent_vars = add_accent_variants(name)
    if len(accent_vars) > 1:
        print(f"\n  Accent-adding variants ({len(accent_vars)} total):")
        for v in accent_vars:
            if v != name:
                print(f"    -> {v!r}")
    else:
        print(f"  ** No accent-adding variants generated (no vowel chars to accent)")

    # --- expand_and_variants ---
    if album:
        q = f"{album} {name}"
        variants = expand_and_variants(q)
        print(f"\n  Album+Artist query variants for {q!r}:")
        for v in variants:
            print(f"    -> {v!r}")
    if track:
        q = f"{track} {name}"
        variants = expand_and_variants(q)
        print(f"\n  Track+Artist query variants for {q!r}:")
        for v in variants:
            print(f"    -> {v!r}")

    # --- iTunes tests ---
    if source in ("apple_music", "itunes", "both"):
        _diag_itunes(name, album, track, genre_set)
    if source in ("deezer", "both"):
        _diag_deezer(name, album, track, genre_set)


def _print_results(label, results, key_name, check_fn, target_name):
    """Print API results and show which pass/fail the check."""
    print(f"\n  [{label}] {len(results)} results:")
    accepted = 0
    for i, r in enumerate(results):
        api_val = r.get(key_name, "")
        match = check_fn(api_val, target_name)
        symbol = "OK" if match else "NO"
        if match:
            accepted += 1
        extra = ""
        if "artistId" in r:
            extra = f"  artistId={r['artistId']}"
        elif "id" in r:
            extra = f"  id={r['id']}"
        print(f"    [{symbol}] {api_val!r}{extra}")
    print(f"  -> {accepted}/{len(results)} passed name check")
    return accepted


def _diag_itunes(name, album, track, genres):
    base_url = "https://itunes.apple.com/search"

    # Step 1: Album+Artist
    if album:
        q = f"{album} {name}"
        print(f"\n--- iTunes Album Search: term={q!r} ---")
        code, data = _api_get(base_url, {"term": q, "entity": "album", "limit": 5})
        print(f"  HTTP {code}")
        if data and "results" in data:
            _print_results("album+artist", data["results"], "collectionName",
                           lambda a, t: names_match_exact(a, t), album)
            # Also check artist names
            print(f"  Artist names in results:")
            for r in data["results"][:5]:
                an = r.get("artistName", "")
                m = names_match_exact(an, name)
                share = _artist_names_share_word(an, name)
                print(f"    {an!r}  match={m}  share_word={share}")

    # Step 2: Track+Artist
    if track:
        q = f"{track} {name}"
        print(f"\n--- iTunes Track Search: term={q!r} ---")
        code, data = _api_get(base_url, {"term": q, "entity": "song", "limit": 5})
        print(f"  HTTP {code}")
        if data and "results" in data:
            _print_results("track+artist", data["results"], "trackName",
                           lambda a, t: names_match_exact(a, t), track)

    # Step 3: Direct artist
    print(f"\n--- iTunes Direct Artist: term={name!r} ---")
    code, data = _api_get(base_url, {"term": name, "entity": "musicArtist", "limit": 10})
    print(f"  HTTP {code}")
    if data and "results" in data:
        _print_results("direct", data["results"], "artistName",
                       lambda a, t: names_match_exact(a, t), name)

    # Step 3.5: Track-only (no artist in query)
    if track:
        print(f"\n--- iTunes Track-Only: term={track!r} (no artist) ---")
        code, data = _api_get(base_url, {"term": track, "entity": "song", "limit": 5})
        print(f"  HTTP {code}")
        if data and "results" in data:
            print(f"  {len(data['results'])} results:")
            for r in data["results"]:
                tn = r.get("trackName", "")
                an = r.get("artistName", "")
                track_ok = names_match_exact(tn, track)
                share = _artist_names_share_word(an, name)
                both = track_ok and share
                sym = "OK" if both else ("~" if track_ok else "NO")
                print(f"    [{sym}] track={tn!r}  artist={an!r}  track_match={track_ok}  artist_share={share}")

    # Step 3.6: Album-only (no artist in query)
    if album:
        print(f"\n--- iTunes Album-Only: term={album!r} (no artist) ---")
        code, data = _api_get(base_url, {"term": album, "entity": "album", "limit": 5})
        print(f"  HTTP {code}")
        if data and "results" in data:
            print(f"  {len(data['results'])} results:")
            for r in data["results"]:
                cn = r.get("collectionName", "")
                an = r.get("artistName", "")
                album_ok = names_match_exact(cn, album)
                share = _artist_names_share_word(an, name)
                both = album_ok and share
                sym = "OK" if both else ("~" if album_ok else "NO")
                print(f"    [{sym}] album={cn!r}  artist={an!r}  album_match={album_ok}  artist_share={share}")

    # Stripped variant
    stripped = strip_accents(name)
    if stripped != name:
        print(f"\n--- iTunes Direct Artist (stripped): term={stripped!r} ---")
        code, data = _api_get(base_url, {"term": stripped, "entity": "musicArtist", "limit": 10})
        print(f"  HTTP {code}")
        if data and "results" in data:
            _print_results("stripped", data["results"], "artistName",
                           lambda a, t: names_match_exact(a, t), name)


def _diag_deezer(name, album, track, genres):
    # Direct artist
    print(f"\n--- Deezer Direct Artist: q={name!r} ---")
    code, data = _api_get("https://api.deezer.com/search/artist", {"q": name, "limit": 10})
    print(f"  HTTP {code}")
    if data and isinstance(data, dict) and "data" in data:
        _print_results("direct", data["data"], "name",
                       lambda a, t: names_match_exact(a, t), name)
    elif data:
        print(f"  Unexpected response: {str(data)[:200]}")

    # Stripped variant
    stripped = strip_accents(name)
    if stripped != name:
        print(f"\n--- Deezer Direct Artist (stripped): q={stripped!r} ---")
        code, data = _api_get("https://api.deezer.com/search/artist", {"q": stripped, "limit": 10})
        print(f"  HTTP {code}")
        if data and isinstance(data, dict) and "data" in data:
            _print_results("stripped", data["data"], "name",
                           lambda a, t: names_match_exact(a, t), name)

    # Track-only
    if track:
        print(f"\n--- Deezer Track-Only: q={track!r} ---")
        code, data = _api_get("https://api.deezer.com/search/track", {"q": track, "limit": 5})
        print(f"  HTTP {code}")
        if data and isinstance(data, dict) and "data" in data:
            print(f"  {len(data['data'])} results:")
            for item in data["data"]:
                tn = item.get("title", "")
                an = item.get("artist", {}).get("name", "")
                track_ok = names_match_exact(tn, track)
                share = _artist_names_share_word(an, name)
                both = track_ok and share
                sym = "OK" if both else ("~" if track_ok else "NO")
                print(f"    [{sym}] track={tn!r}  artist={an!r}  track_match={track_ok}  artist_share={share}")

    # Album-only
    if album:
        print(f"\n--- Deezer Album-Only: q={album!r} ---")
        code, data = _api_get("https://api.deezer.com/search/album", {"q": album, "limit": 5})
        print(f"  HTTP {code}")
        if data and isinstance(data, dict) and "data" in data:
            print(f"  {len(data['data'])} results:")
            for item in data["data"]:
                cn = item.get("title", "")
                an = item.get("artist", {}).get("name", "")
                album_ok = names_match_exact(cn, album)
                share = _artist_names_share_word(an, name)
                both = album_ok and share
                sym = "OK" if both else ("~" if album_ok else "NO")
                print(f"    [{sym}] album={cn!r}  artist={an!r}  album_match={album_ok}  artist_share={share}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose ArtistArtDownloader search for a specific artist")
    parser.add_argument("name", help="Artist name as it appears in your audio tags")
    parser.add_argument("--source", default="both", choices=["apple_music", "deezer", "both"])
    parser.add_argument("--album", default="", help="Album name from tags")
    parser.add_argument("--track", default="", help="Track name from tags")
    parser.add_argument("--genres", default="", help="Comma-separated genres from tags")
    args = parser.parse_args()

    diag(args.name, args.source, args.album, args.track, args.genres)
    print(f"\nDone.")