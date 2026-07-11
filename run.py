"""Launch Artist Art Downloader."""

import sys
import os
import shutil

# Ensure project root is on path
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Clear stale __pycache__ to avoid surrogate encoding errors on Python 3.14
_pkg = os.path.join(_project_root, "artist_art_downloader")
_cache = os.path.join(_pkg, "__pycache__")
if os.path.isdir(_cache):
    shutil.rmtree(_cache, ignore_errors=True)

# Disable bytecode writing to prevent future cache issues
sys.dont_write_bytecode = True

from artist_art_downloader.main import main

if __name__ == "__main__":
    main()