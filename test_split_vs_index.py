# -*- coding: utf-8 -*-
"""Test split_artists() against real artist names from index.txt."""
import sys, io, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ====== CURRENT split_artists() ======
def split_artists(artist: str) -> list[str]:
    # & split — only when surrounded by spaces
    if ' & ' in artist:
        parts = [a.strip() for a in artist.split(' & ') if a.strip()]
        if len(parts) > 1:
            return parts
    # feat./ft. split
    m = re.split(r'\s+(?:feat\.?|ft\.?|featuring)\s+', artist, flags=re.IGNORECASE)
    if len(m) > 1:
        return [a.strip() for a in m if a.strip()]
    return [artist]

def _strip_collaboration_markers(artist: str) -> str:
    artist = re.sub(
        r'(?:^|[\s\(\[\{])(feat|ft|featuring|vs|with|w|presents?|prod)\b[\s\.:\(\[\{/].*$',
        '', artist, flags=re.IGNORECASE).strip()
    artist = re.sub(r'[\s\(\[\{]*&[\s\.:\(\[\{/].*$', '', artist, flags=re.IGNORECASE).strip()
    artist = re.sub(r',\s+.*$', '', artist).strip()
    artist = re.sub(r'[\s\(\[\{]+$', '', artist).strip()
    return artist

def extract_artist(stem: str) -> str | None:
    stem = re.sub(r'^\d+[\s\._\-]+', '', stem)
    parts = stem.split(' - ')
    artist = parts[0].strip()
    cleaned = _strip_collaboration_markers(artist)
    if cleaned:
        artist = cleaned
    return artist if artist else None

# Parse index.txt
with open('index.txt', 'rb') as f:
    raw = f.read()
if raw[:2] == b'\xff\xfe':
    text = raw.decode('utf-16-le', errors='replace')
else:
    text = raw.decode('utf-16-le', errors='replace')

lines = text.split('\n')
AUDIO_EXTS = {'.mp3', '.flac', '.ogg', '.m4a', '.wma', '.aiff', '.aif'}
audio_lines = [s.strip() for s in lines if re.search(r'\.([a-zA-Z0-9]+)$', s.strip()) and '.' + re.search(r'\.([a-zA-Z0-9]+)$', s.strip()).group(1).lower() in AUDIO_EXTS]

print(f"Total audio files in index.txt: {len(audio_lines)}")
print()

# Collect unique artist names
artist_names = {}
for line in audio_lines:
    stem = Path(line).stem
    artist = extract_artist(stem)
    if artist and artist.lower() not in (
        'various artists', 'various', 'va',
        'varios artistas', 'verschiedene kunstler',
        'verschiedene interpret(en)', 'artistes varies',
        'artisti vari', 'artistas varios',
    ):
        if artist not in artist_names:
            artist_names[artist] = []
        if len(artist_names[artist]) < 3:
            artist_names[artist].append(stem)

print(f"Unique artist names (from filename): {len(artist_names)}")
print()

# Test split_artists
results = []
for artist in sorted(artist_names.keys(), key=str.lower):
    parts = split_artists(artist)
    if len(parts) > 1:
        rule = "запятая" if ',' in artist else (" & " if ' & ' in artist else "feat/ft")
        ex = artist_names[artist][0][:60]
        results.append((rule, artist, parts, ex))

# Print by type
for rule_label, rule_code in [("ЗАПЯТАЯ", "запятая"), (" & (с пробелами)", " & "), ("FEAT/FT", "feat/ft")]:
    filtered = [r for r in results if r[0] == rule_code]
    if not filtered:
        continue
    print(f"--- {rule_label} ({len(filtered)} имён) ---")
    print()
    for _, artist, parts, example in filtered:
        parts_str = " → ".join(parts[:3])
        if len(parts) > 3:
            parts_str += f" ... (+{len(parts)-3})"
        print(f"  <<{artist}>>")
        print(f"    -> {parts_str}")
    print()

print(f"ИТОГО: {len(results)} имён будут разделены")
by_type = {}
for r, _, _, _ in results:
    by_type[r] = by_type.get(r, 0) + 1
for k, v in by_type.items():
    print(f"  {k}: {v}")
print(f"  Не разделены: {len(artist_names) - len(results)}")
