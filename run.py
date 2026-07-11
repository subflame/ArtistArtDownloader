"""Launch Artist Art Downloader."""

import sys
import os

# Ensure project root is on path
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from artist_art_downloader.main import main

if __name__ == "__main__":
    main()
