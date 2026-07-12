"""Analyze index.txt against scanner.py for potential issues."""

import sys
import re

# Read index.txt
with open('index.txt', 'rb') as f:
    raw = f.read()

# Decode UTF-16
if raw[:2] == b'\xff\xfe':
    text = raw.decode('utf-16-le', errors='replace')
elif raw[:2] == b'\xfe\xff':
    text = raw.decode('utf-16-be', errors='replace')
else:
    text = raw.decode('utf-16-le', errors='replace')

lines = text.split('\n')
print(f"Total lines in index.txt: {len(lines)}", flush=True)
print(f"Total chars: {len(text)}", flush=True)

# ====== ANALYSIS 1: Count audio files by extension ======
AUDIO_EXTS = {'.mp3', '.flac', '.ogg', '.m4a', '.wma', '.aiff', '.aif'}
audio_lines = []
other_exts = set()
for line in lines:
    s = line.strip()
    m = re.search(r'\.([a-zA-Z0-9]+)$', s)
    if m:
        ext = '.' + m.group(1).lower()
        if ext in AUDIO_EXTS:
            audio_lines.append(s)
        else:
            other_exts.add(ext)

print(f"\n{'='*60}", flush=True)
print(f"AUDIO FILES FOUND IN INDEX: {len(audio_lines)}", flush=True)
print(f"{'='*60}", flush=True)

# Count per extension
ext_counts = {}
for fn in audio_lines:
    ext = '.' + fn.rsplit('.', 1)[-1].lower()
    ext_counts[ext] = ext_counts.get(ext, 0) + 1
print(f"\nExtensions breakdown:", flush=True)
for ext, count in sorted(ext_counts.items()):
    print(f"  {ext}: {count}", flush=True)

# ====== ANALYSIS 2: Check filename patterns ======
issues = {
    'non_ascii_chars': 0,
    'ellipsis_chars': 0,
    'question_marks': 0,
    'quotes_in_name': 0,
    'multiple_dots': 0,
    'path_too_long_200': 0,
}

for fn in audio_lines:
    base = fn
    # Remove path prefix if present
    if '\\' in base:
        base = base.rsplit('\\', 1)[-1]
    basename = base.rsplit('.', 1)[0] if '.' in base else base

    if any(ord(c) > 127 for c in basename):
        issues['non_ascii_chars'] += 1
    if chr(0x2026) in basename or '...' in basename.replace(chr(0x2026), ''):
        issues['ellipsis_chars'] += 1
    if '?' in basename:
        issues['question_marks'] += 1
    if any(c in basename for c in '"\u201c\u201d\u201e'):
        issues['quotes_in_name'] += 1
    if basename.count('.') >= 1:
        issues['multiple_dots'] += 1
    if len(base) > 200:
        issues['path_too_long_200'] += 1

print(f"\n{'='*60}", flush=True)
print(f"FILENAME ANALYSIS", flush=True)
print(f"{'='*60}", flush=True)
for k, v in issues.items():
    print(f"  {k}: {v}", flush=True)

# ====== ANALYSIS 3: Look for specific problematic patterns ======
print(f"\n{'='*60}", flush=True)
print(f"SPECIFIC PATTERN CHECKS", flush=True)
print(f"{'='*60}", flush=True)

# Find patterns with dots that could confuse extension detection
dot_confusion = []
for fn in audio_lines:
    base = fn
    if '\\' in base:
        base = base.rsplit('\\', 1)[-1]
    # Check for names ending in a word with dot before extension
    # e.g., "Vertebr. by Vertebr..m4a" - note the double dot
    if '..' in base:
        dot_confusion.append(base)

print(f"\n  Files with double dots (potential confusion): {len(dot_confusion)}")
if dot_confusion:
    for f in dot_confusion[:10]:
        print(f"    {repr(f)}", flush=True)

# ====== ANALYSIS 4: Save a broader sample for manual inspection ======
with open('index_broad_sample.txt', 'w', encoding='utf-8') as f:
    f.write(text[:50000])
print(f"\n  Broad sample saved to index_broad_sample.txt", flush=True)

# ====== ANALYSIS 5: Count unique artists and albums in index ======
genre_artist_album_tracks = []
for line in audio_lines[:5000]:
    genre_artist_album_tracks.append(line)

print(f"\n{'='*60}", flush=True)
print(f"SUMMARY", flush=True)
print(f"{'='*60}", flush=True)
print(f"  Audio tracks in index.txt: {len(audio_lines)}", flush=True)
print(f"  Non-audio file types found: {sorted(other_exts)[:30]}", flush=True)
print(f"  User claims: 19847 tracks in player", flush=True)
discrepancy = 19847 - len(audio_lines)
print(f"  Discrepancy: {discrepancy} tracks (may be in formats not captured)", flush=True)

print(f"\nDone!", flush=True)
