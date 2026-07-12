"""Test the scanner changes: _is_compilation detection and compilation skip."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ----------------------------------------------------------------------
#  Tests: _is_compilation — pattern matching
# ----------------------------------------------------------------------

def test_is_compilation():
    """Verify _is_compilation catches Various Artists variants and rejects regular names."""
    from unittest.mock import MagicMock
    from artist_art_downloader.scanner import _is_compilation

    cases = [
        # (albumartist, expected_is_compilation)
        # Should be detected as compilation
        ("Various Artists",      True),
        ("various",              True),
        ("VA",                   True),
        ("V.A.",                 True),
        ("v.a.",                 True),
        ("V A",                  True),
        ("VA - Compilation",     True),
        ("VA Compilation",       True),
        ("VA/Various",           True),
        ("VA: The Best Of",      True),
        ("Varios Artistas",      True),
        ("Verschiedene Kunstler", True),
        # Should NOT be detected as compilation
        ("Vangelis",             False),
        ("Van Halen",            False),
        ("Variations",           False),
        ("Vaya Con Dios",        False),
        ("Pink Floyd",           False),
        ("Valentine",            False),
        ("",                     False),
        (None,                   False),
    ]
    passed = 0
    failed = 0
    for albumartist, expected in cases:
        mock_tag = MagicMock()
        mock_tag.albumartist = albumartist
        result = _is_compilation(mock_tag)
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {'OK' if result == expected else 'FAIL'}  _is_compilation({albumartist!r:30s}) -> {result}  (expected {expected})")

    print(f"\n  _is_compilation: {passed}/{passed + failed} passed")
    return failed == 0


# ----------------------------------------------------------------------
#  Mock test: _read_tags with compilation
# ----------------------------------------------------------------------

def test_read_tags_compilation():
    """Verify that _read_tags returns None for compilation albums."""
    from unittest.mock import patch, MagicMock
    from artist_art_downloader.scanner import _read_tags

    mock_tag = MagicMock()
    mock_tag.albumartist = "Various Artists"
    mock_tag.artist = "Some Artist"
    mock_tag.album = "Greatest Hits"
    mock_tag.title = "My Song [Remix]"
    mock_tag.genre = "Pop"
    mock_tag.year = 2020

    with patch("artist_art_downloader.scanner.TinyTag.get", return_value=mock_tag):
        result = _read_tags(Path("dummy.mp3"))

    assert result is None, f"Expected None for compilation, got {result!r}"
    print("  OK  _read_tags returns None for compilation (Various Artists)")
    return True


# ----------------------------------------------------------------------
#  Run
# ----------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  Scanner Changes -- Tests")
    print("=" * 55)

    ok = True

    print()
    ok = test_is_compilation() and ok

    print()
    try:
        ok = test_read_tags_compilation() and ok
    except ImportError as e:
        print(f"  SKIP mock test (missing dependency: {e})")

    print()
    if ok:
        print("All tests passed!")
    else:
        print("Some tests failed.")
        sys.exit(1)
