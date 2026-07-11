"""Entry point for Artist Art Downloader."""

import sys
import os


def main():
    # Ensure package root is on path when run directly
    _here = os.path.dirname(os.path.abspath(__file__))
    _pkg = os.path.dirname(_here)
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

    # When running as a PyInstaller EXE, all deps are bundled — skip check.
    # When running as a script, pip install -r requirements.txt handles it.
    if not getattr(sys, 'frozen', False):
        missing = []
        try:
            import tinytag  # noqa: F401
        except ImportError:
            missing.append("tinytag")
        try:
            import requests  # noqa: F401
        except ImportError:
            missing.append("requests")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            missing.append("Pillow")

        if missing:
            msg = (
                f"Missing dependencies: {', '.join(missing)}\n\n"
                f"Install them with:\n"
                f"  pip install {' '.join(missing)}"
            )
            print(msg)
            input("\nPress Enter to exit...")
            sys.exit(1)

    from artist_art_downloader.gui import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
