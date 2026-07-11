"""Main GUI for Artist Art Downloader."""

import sys
import os
import base64
import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
import pystray

from .config import Settings, THEMES, ArtistCache
from .scanner import scan_folder, artist_image_exists, get_artist_root, find_similar_artists, merge_artists
from .utils import sanitize_filename
from .fetcher import fetch_artist_image, download_image, search_artist_candidates, fetch_artist_image_by_id, fetch_candidate_preview, fetch_artist_image_by_track_only, fetch_artist_image_by_album_only

APP_VERSION = "1.0.1"


# Embedded .ico data (base64, multi-res 16/32/48/64/128/256)
_ICON_B64 = "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"


def _load_icon_photo():
    """Load embedded icon as PIL PhotoImage from in-memory base64 data."""
    from PIL import Image, ImageTk
    data = base64.b64decode(_ICON_B64)
    img = Image.open(io.BytesIO(data))
    small = img.resize((64, 64), getattr(Image, 'LANCZOS', Image.BILINEAR))
    return ImageTk.PhotoImage(small)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.cache = ArtistCache()
        self.running = False
        self._run_counter = 0  # incremented each start -- rejects stale _set_finished
        self.results: list[tuple[str, str, str]] = []

        self.title(f"Artist Art Downloader v{APP_VERSION}")
        geo = f"{self.settings.window_width}x{self.settings.window_height}"
        if self.settings.window_x >= 0 and self.settings.window_y >= 0:
            geo += f"+{self.settings.window_x}+{self.settings.window_y}"
        self.geometry(geo)
        self.minsize(600, 450)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Set window icon (embedded in code, loaded from base64 in memory)
        try:
            photo = _load_icon_photo()
            self.iconphoto(True, photo)
            self._taskbar_photo = photo  # prevent GC
        except Exception:
            pass

        self._apply_theme()
        self._build_ui()
        self._apply_theme_to_widgets()

        if self.settings.last_folder:
            self.folder_var.set(self.settings.last_folder)

        # System tray
        self._tray_icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None
        self.bind("<Unmap>", self._on_window_unmap)

        # Hotkeys
        self.bind("<Return>", lambda e: self._start())
        self.bind("<Escape>", lambda e: self._stop())

    # -- Theming -----------------------------------------------------------

    def _apply_theme(self):
        t = self.settings.get_theme()
        self.configure(bg=t["bg"])
        self.option_add("*Background", t["bg"])
        self.option_add("*Foreground", t["fg"])
        self.option_add("*Font", ("Segoe UI", 10))

    def _apply_theme_to_widgets(self):
        t = self.settings.get_theme()
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=t["bg"], foreground=t["fg"])
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"),
                         background=t["bg"], foreground=t["accent"])
        style.configure("Dim.TLabel", font=("Segoe UI", 9),
                         background=t["bg"], foreground=t["fg_dim"])
        style.configure("Success.TLabel", foreground=t["success"], background=t["bg"])
        style.configure("Error.TLabel", foreground=t["error"], background=t["bg"])
        style.configure("Warning.TLabel", foreground=t["warning"], background=t["bg"])

        style.configure("TButton", font=("Segoe UI", 10, "bold"),
                         padding=(16, 8))
        style.map("TButton",
                   background=[("active", t["accent_hover"]), ("!active", t["button_bg"])],
                   foreground=[("active", t["button_fg"]), ("!active", t["button_fg"])])

        style.configure("Small.TButton", font=("Segoe UI", 9), padding=(10, 4))
        style.map("Small.TButton",
                   background=[("active", t["bg_hover"]), ("!active", t["bg_secondary"])],
                   foreground=[("active", t["fg"]), ("!active", t["fg"])])

        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(20, 10))
        style.map("Accent.TButton",
                   background=[("active", t["accent_hover"]), ("!active", t["accent"])],
                   foreground=[("active", t["button_fg"]), ("!active", t["button_fg"])])

        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"), padding=(20, 10))
        style.map("Stop.TButton",
                   background=[("active", "#d20f39"), ("!active", t["error"])],
                   foreground=[("active", "#ffffff"), ("!active", "#ffffff")])

        style.configure("TCheckbutton", background=t["bg"], foreground=t["fg"],
                         font=("Segoe UI", 10))
        style.map("TCheckbutton",
                   background=[("active", t["bg"])],
                   indicatorcolor=[("selected", t["accent"]), ("!selected", t["entry_bg"])])

        style.configure("TRadiobutton", background=t["bg"], foreground=t["fg"],
                         font=("Segoe UI", 10))
        style.map("TRadiobutton",
                   background=[("active", t["bg"])],
                   indicatorcolor=[("selected", t["accent"]), ("!selected", t["entry_bg"])])

        style.configure("TCombobox", fieldbackground=t["entry_bg"],
                         background=t["entry_bg"], foreground=t["entry_fg"],
                         arrowcolor=t["fg"], padding=6)
        style.map("TCombobox",
                   fieldbackground=[("readonly", t["entry_bg"])],
                   foreground=[("readonly", t["entry_fg"])])

        style.configure("TEntry", fieldbackground=t["entry_bg"],
                         background=t["entry_bg"], foreground=t["entry_fg"],
                         insertcolor=t["fg"], padding=6)

        style.configure("Horizontal.TProgressbar",
                         background=t["accent"], troughcolor=t["bg_secondary"])

        style.configure("Log.TFrame", background=t["list_bg"])
        style.configure("Log.TLabel", background=t["list_bg"], foreground=t["fg"],
                         font=("Consolas", 9))

        style.configure("TSeparator", background=t["border"])

    # -- UI Construction ---------------------------------------------------

    def _build_ui(self):
        t = self.settings.get_theme()

        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="Artist Art Downloader", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Settings", style="Small.TButton",
                   command=self._open_settings).pack(side=tk.RIGHT)

        # -- Scanner mode frame --
        self.scanner_frame = ttk.Frame(main)
        self._build_scanner_ui(self.scanner_frame)
        self.scanner_frame.pack(fill=tk.X, pady=(0, 12))

        # -- Buttons, progress, log --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 12))
        self.start_btn = ttk.Button(btn_frame, text="Start", style="Accent.TButton",
                                     command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(btn_frame, text="Stop", style="Stop.TButton",
                                    command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(main, variable=self.progress_var,
                                         maximum=100, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 4))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var, style="Dim.TLabel").pack(anchor=tk.W, pady=(0, 8))

        log_frame = ttk.Frame(main, style="Log.TFrame", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=12, wrap=tk.WORD,
                                 bg=t["list_bg"], fg=t["fg"],
                                 font=("Consolas", 9), bd=0, highlightthickness=0,
                                 selectbackground=t["list_select"],
                                 state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_text.tag_configure("success", foreground=t["success"])
        self.log_text.tag_configure("error", foreground=t["error"])
        self.log_text.tag_configure("warning", foreground=t["warning"])
        self.log_text.tag_configure("info", foreground=t["accent"])
        self.log_text.tag_configure("skip", foreground=t["fg_dim"])

    # -- Actions -----------------------------------------------------------

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select music folder")
        if folder:
            self.folder_var.set(folder)
            self.settings.last_folder = folder
            self.settings.save()

    def _open_settings(self):
        SettingsDialog(self, self.settings, self._apply_settings)

    def _apply_settings(self):
        self.settings.save()
        self._apply_theme()
        self._apply_theme_to_widgets()
        self._update_text_theme()

    def _log(self, text: str, tag: str = ""):
        """Thread-safe log: if called from bg thread, schedule via after()."""
        if threading.current_thread() is threading.main_thread():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, text + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        else:
            self.after(0, self._log, text, tag)

    def _update_text_theme(self):
        t = self.settings.get_theme()
        self.log_text.configure(bg=t["list_bg"], fg=t["fg"], selectbackground=t["list_select"])
        self.log_text.tag_configure("success", foreground=t["success"])
        self.log_text.tag_configure("error", foreground=t["error"])
        self.log_text.tag_configure("warning", foreground=t["warning"])
        self.log_text.tag_configure("info", foreground=t["accent"])
        self.log_text.tag_configure("skip", foreground=t["fg_dim"])

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _show_preview_in_log(self, file_path: Path):
        """Show a small thumbnail preview in the log after download."""
        try:
            from PIL import Image, ImageTk
            import io
            img = Image.open(str(file_path))
            img.thumbnail((48, 48))
            photo = ImageTk.PhotoImage(img)
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.image_create(tk.END, image=photo)
            self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
            # Prevent GC
            if not hasattr(self, "_preview_photos"):
                self._preview_photos = []
            self._preview_photos.append(photo)
        except Exception:
            pass

    def _build_scanner_ui(self, parent):
        """Build the scanner-mode controls (folder picker, skip checkbox)."""
        folder_frame = ttk.Frame(parent)
        folder_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(folder_frame, text="Music folder:").pack(anchor=tk.W, pady=(0, 4))

        folder_row = ttk.Frame(folder_frame)
        folder_row.pack(fill=tk.X)
        self.folder_var = tk.StringVar()
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(folder_row, text="Browse", style="Small.TButton",
                   command=self._browse_folder).pack(side=tk.RIGHT)

        self.skip_var = tk.BooleanVar(value=self.settings.skip_existing)
        ttk.Checkbutton(parent, text="Skip artists with existing artist.jpg",
                         variable=self.skip_var).pack(anchor=tk.W)

    # -- Actions -------------------------------------------------------------

    def _start(self):
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Error", "Please select a valid music folder.")
            return

        # Force-stop any previous run that may be stuck (e.g. on scan_folder or HTTP)
        self.running = False
        # Process any pending after() callbacks from the old thread (like _set_finished)
        self.update_idletasks()

        self._run_counter += 1
        self.running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.progress_var.set(0)
        self.status_var.set("Scanning...")
        self._clear_log()

        thread = threading.Thread(target=self._process, args=(Path(folder),), daemon=True)
        thread.start()

    def _on_window_unmap(self, event=None):
        """Intercept window minimize -- hide to system tray instead."""
        try:
            if self.state() == 'iconic':
                self._minimize_to_tray()
        except tk.TclError:
            pass

    def _create_tray_icon(self) -> pystray.Icon:
        """Create a system tray icon with the embedded app icon."""
        from PIL import Image
        data = base64.b64decode(_ICON_B64)
        img = Image.open(io.BytesIO(data))
        small = img.resize((64, 64), getattr(Image, 'LANCZOS', Image.BILINEAR))

        def on_show(icon: pystray.Icon, item: pystray.MenuItem):
            self.after(0, self._restore_from_tray)

        def on_quit(icon: pystray.Icon, item: pystray.MenuItem):
            self.after(0, self._quit_from_tray)

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )
        return pystray.Icon(
            "ArtistArtDownloader", small,
            f"Artist Art Downloader v{APP_VERSION}", menu,
        )

    def _minimize_to_tray(self):
        """Hide window and show system tray icon.
        
        Process continues running in background.
        """
        # Guard: prevent re-entry when fallback iconify() re-triggers <Unmap>
        if getattr(self, '_minimizing_to_tray', False):
            return
        self._minimizing_to_tray = True
        try:
            self.withdraw()
            if self._tray_icon is not None:
                return
            try:
                icon = self._create_tray_icon()
                self._tray_icon = icon
                self._tray_thread = threading.Thread(target=icon.run, daemon=True)
                self._tray_thread.start()
            except Exception:
                # Fallback: normal minimize if tray fails
                self.iconify()
        finally:
            self._minimizing_to_tray = False

    def _restore_from_tray(self):
        """Restore window from system tray."""
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
            self._tray_thread = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_from_tray(self):
        """Quit app completely from system tray menu."""
        self.running = False
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
            self._tray_thread = None
        self._save_settings()
        self.destroy()

    def _stop(self):
        self.running = False
        self.status_var.set("Stopping...")

    def _on_close(self):
        self.running = False
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
            self._tray_thread = None
        self._save_settings()
        self.destroy()

    def _save_settings(self):
        """Save window geometry, settings, and cache."""
        try:
            self.settings.window_width = self.winfo_width()
            self.settings.window_height = self.winfo_height()
            self.settings.window_x = self.winfo_x()
            self.settings.window_y = self.winfo_y()
            self.settings.save()
            self.cache.save()
        except Exception:
            pass

    # -- Processing --------------------------------------------------------

    def _process(self, root: Path):
        self._log("Scanning folder for audio files...", "info")

        skip_existing = self.skip_var.get()
        sep_folder = self.settings.separate_folder
        try:
            raw_artists = scan_folder(root, skip_existing=skip_existing,
                                      separate_folder=sep_folder)
        except Exception as e:
            self._log(f"Scan error: {e}", "error")
            self._finish()
            return

        if not raw_artists:
            if skip_existing:
                self._log("All artists already have images -- nothing to download.", "success")
            else:
                self._log("No audio files with artist tags found.", "warning")
            self._finish()
            return

        # Apply saved aliases first
        if self.settings.artist_aliases:
            raw_artists = merge_artists(raw_artists, self.settings.artist_aliases)
            self._log(f"Applied {len(self.settings.artist_aliases)} saved alias(es).", "info")

        # Find similar names that aren't aliased yet
        similar_groups = find_similar_artists(raw_artists)
        if similar_groups:
            if self.settings.skip_merge_dialog:
                self._log(f"Found {len(similar_groups)} group(s) of similar artist names (skipped dialog).\n", "info")
            else:
                self._log(f"Found {len(similar_groups)} group(s) of similar artist names.\n", "warning")
                merge_map = self._prompt_merge_artists(similar_groups, raw_artists)
                if merge_map:
                    raw_artists = merge_artists(raw_artists, merge_map)
                    self._log(f"Merged {len(merge_map)} artist alias(es).\n", "success")
                else:
                    self._log("Skipped merging -- keeping original names.\n", "info")

        artists = raw_artists
        total = len(artists)
        self._log(f"Processing {total} unique artist(s).\n", "info")

        if skip_existing:
            still_have = sum(
                1 for n, c in artists.items()
                if c.album_dirs and artist_image_exists(next(iter(c.album_dirs)), root, n,
                                                        separate_folder=sep_folder)
            )
            if still_have:
                self._log(f"  [!] {still_have}/{total} artists still have images -- pre-scan missed them!", "warning")

        source = self.settings.source
        downloaded = 0
        skipped = 0
        failed = 0

        # Collect work items (search + download per artist)
        work_items = []
        for artist_name, ctx in artists.items():
            if not ctx.album_dirs:
                self._log(f"  [X] {artist_name} -- no album directories", "error")
                failed += 1
                continue
            album_dir = next(iter(ctx.album_dirs))
            artist_root = get_artist_root(album_dir, root)
            if skip_existing and artist_image_exists(album_dir, root, artist_name,
                                                      separate_folder=sep_folder):
                self._log(f"  [>>] {artist_name} -- image exists", "skip")
                skipped += 1
                continue
            work_items.append((artist_name, ctx, artist_root))

        total = len(work_items)
        if total == 0:
            self._log(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed.", "info")
            self._finish()
            return

        self._log(f"Searching {total} artist(s)...\n", "info")

        # Phase 1: Search all artists (sequential -- dialogs need main thread)
        search_results = []  # (artist_name, img_url, save_path, error_detail)
        for i, (artist_name, ctx, artist_root) in enumerate(work_items, 1):
            if not self.running:
                self._log("? Stopped by user.", "warning")
                break
            self.after(0, self.status_var.set, f"[{i}/{total}] Searching: {artist_name}")
            self.after(0, self.progress_var.set, (i / total) * 50)

            safe_name = sanitize_filename(artist_name)
            if self.settings.separate_folder:
                save_dir = Path(self.settings.separate_folder)
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / safe_name
            else:
                base_name = safe_name if self.settings.artist_filename else "artist"
                save_path = artist_root / base_name

            self._log(f"  ? {artist_name}", "info")
            self._log(f"     Save to: {save_path}.jpg/.png", "skip")
            img_url, error_detail = self._search_artist_image(artist_name, ctx, source)
            if img_url:
                self._log(f"     [ok] URL found", "success")
            else:
                self._log(f"     [X] {error_detail}", "error")
            search_results.append((artist_name, img_url, save_path, error_detail))

        # Phase 2: Download all found images in parallel
        self._log(f"\nDownloading {sum(1 for _, u, _, _ in search_results if u)} image(s)...\n", "info")

        # Counters (safe: only modified in the sequential as_completed loop below)
        _counters = [0, 0]  # [downloaded, failed]

        def _do_download(item):
            name, url, path, _ = item
            if not url:
                return name, None, _, "search failed"
            result, dl_err = download_image(url, path,
                                      output_format=self.settings.output_format,
                                      jpeg_quality=self.settings.jpeg_quality)
            return name, result, url, dl_err or ""

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_do_download, item): item for item in search_results}
            done_count = 0
            for future in as_completed(futures):
                if not self.running:
                    break
                name, result, url, err = future.result()
                done_count += 1
                self.after(0, self.status_var.set, f"[{done_count}/{len(search_results)}] Downloading: {name}")
                self.after(0, self.progress_var.set, 50 + (done_count / len(search_results)) * 50)
                if result:
                    self.after(0, self._log, f"  [ok] {name} -> {result.name}", "success")
                    self.after(0, self._log, f"     Saved to: {result.parent}", "skip")
                    self.after(0, self._show_preview_in_log, result)
                    _counters[0] += 1
                else:
                    detail = err or "download error"
                    self.after(0, self._log, f"  [X] {name} -- {detail}", "error")
                    _counters[1] += 1

        downloaded, failed = _counters[0], _counters[1]

        self._log(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed.", "info")
        self._finish()

    def _search_artist_image(self, artist_name: str, ctx, source: str) -> tuple[Optional[str], str]:
        """Search for artist image. Returns (url, error_detail)."""
        # Step 0: Check cache -- but still check for multiple candidates
        cached = self.cache.get(artist_name, source)
        if cached:
            self._log(f"     Cached URL -- checking candidates...", "skip")
            resolved = self._resolve_with_candidates(artist_name, source, cached)
            return resolved, ""

        tried = []

        # Step 1: Try top albums with album+year context (max 5)
        albums_sorted = sorted(
            ctx.album_track_counts.keys(),
            key=lambda a: ctx.album_track_counts[a],
            reverse=True,
        )[:5]
        for album_name in albums_sorted:
            year_ctx = ctx.album_years.get(album_name, "")
            self._log(
                f"  Trying album: {album_name}"
                + (f" ({year_ctx})" if year_ctx else "")
                + "...",
                "info",
            )
            img_url = fetch_artist_image(
                artist_name, source,
                album_name=album_name, year=year_ctx,
                genres=ctx.genres,
            )
            if img_url:
                self.cache.put(artist_name, source, img_url)
                return self._resolve_with_candidates(artist_name, source, img_url), ""
            tried.append(f"album:{album_name}")

        # Step 2: Try track-by-track search (up to 5 tracks)
        tracks_sample = list(ctx.track_names)[:5]
        for track_name in tracks_sample:
            self._log(f"  Trying track: {track_name}...", "info")
            img_url = fetch_artist_image(
                artist_name, source,
                genres=ctx.genres, track_name=track_name,
            )
            if img_url:
                self.cache.put(artist_name, source, img_url)
                return self._resolve_with_candidates(artist_name, source, img_url), ""
            tried.append(f"track:{track_name}")

        # Step 3: Search by artist name directly (no album context)
        self._log(f"  Searching by name: {artist_name}...", "info")
        img_url = fetch_artist_image(
            artist_name, source,
            album_name="", year="",
            genres=ctx.genres,
        )
        if img_url:
            self.cache.put(artist_name, source, img_url)
            return self._resolve_with_candidates(artist_name, source, img_url), ""
        tried.append("name")

        # Step 3.5: Track-only search -- find artist via exact track title match.
        # If the artist name differs too much (accents, spelling) but track title
        # is 100% correct, we accept a "similar" artist (shares at least one word).
        tracks_all = list(ctx.track_names)
        tracks_sample = tracks_all[:5]  # limit to 5 tracks to avoid API flooding
        if tracks_all:
            self._log(f"  Track-only fallback: searching by track title ({len(tracks_sample)}/{len(tracks_all)} tracks)...", "info")
            for track_name in tracks_sample:
                self._log(f"    track: {track_name}...", "info")
                img_url = fetch_artist_image_by_track_only(
                    track_name, artist_name, source, genres=ctx.genres,
                )
                if img_url:
                    self._log(f"  Track-only match via: {track_name}", "success")
                    self.cache.put(artist_name, source, img_url)
                    return self._resolve_with_candidates(artist_name, source, img_url), ""
            tried.append("track_only")

        # Step 3.6: Album-only search -- find artist via exact album title match.
        # Same idea as track-only: search by album name, accept similar artist.
        albums_all = sorted(
            ctx.album_track_counts.keys(),
            key=lambda a: ctx.album_track_counts[a],
            reverse=True,
        )[:5]  # limit to 5 albums to avoid API flooding
        if albums_all:
            self._log(f"  Album-only fallback: searching by album title ({len(albums_all)} albums)...", "info")
            for album_name in albums_all:
                img_url = fetch_artist_image_by_album_only(
                    album_name, artist_name, source, genres=ctx.genres,
                )
                if img_url:
                    self._log(f"  Album-only match via: {album_name}", "success")
                    self.cache.put(artist_name, source, img_url)
                    return self._resolve_with_candidates(artist_name, source, img_url), ""
            tried.append("album_only")

        # Step 4: No result from API search -- try candidate picker as last resort
        candidates = search_artist_candidates(artist_name, source)
        if len(candidates) == 1:
            url = fetch_artist_image_by_id(candidates[0])
            if url:
                self.cache.put(artist_name, source, url)
            return url, "" if url else "no image for candidate"
        elif len(candidates) > 1:
            chosen = self._prompt_artist_choice(artist_name, candidates)
            if chosen:
                url = fetch_artist_image_by_id(chosen)
                if url:
                    self.cache.put(artist_name, source, url)
                return url, "" if url else "no image for chosen candidate"
            return None, "skipped candidate selection"

        detail = "tried: " + ", ".join(tried) if tried else "no results from any search"
        return None, detail

    def _resolve_with_candidates(self, artist_name: str, source: str,
                                  current_url: str) -> Optional[str]:
        """Check if multiple candidates exist; if so, show dialog regardless of current_url."""
        candidates = search_artist_candidates(artist_name, source)
        if len(candidates) > 1:
            chosen = self._prompt_artist_choice(artist_name, candidates)
            if chosen:
                result = fetch_artist_image_by_id(chosen)
                if result:
                    return result
            # User skipped or chosen candidate has no image -> keep current URL
        return current_url

    def _prompt_merge_artists(self, groups, artists):
        """Show merge dialog (from bg thread). Blocks until user responds."""
        import threading

        self._merge_result = None
        self._merge_event = threading.Event()

        def show_dialog():
            dialog = MergeArtistsDialog(self, groups, artists)
            self.wait_window(dialog)
            self._merge_event.set()

        self.after(0, show_dialog)
        self._merge_event.wait(timeout=300)  # 5 min max
        if not self._merge_event.is_set():
            return None
        return self._merge_result

    def _prompt_artist_choice(self, artist_name, candidates):
        """Show artist choice dialog from bg thread. Blocks until user responds."""
        import threading

        self._artist_choice = None
        self._choice_event = threading.Event()

        def show_dialog():
            dialog = ArtistChoiceDialog(self, artist_name, candidates)
            self.wait_window(dialog)
            self._choice_event.set()

        self.after(0, show_dialog)
        self._choice_event.wait(timeout=300)  # 5 min max
        if not self._choice_event.is_set():
            return None
        return self._artist_choice

    def _finish(self):
        run_gen = self._run_counter
        self.after(0, lambda: self._set_finished(run_gen))

    def _set_finished(self, run_gen: int = 0):
        if run_gen != self._run_counter:
            return  # stale callback from a previous (stopped/crashed) run
        self.running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.progress_var.set(100)
        self.status_var.set("Finished")


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: App, settings: Settings, on_apply):
        super().__init__(parent)
        self.settings = settings
        self.on_apply = on_apply
        self.result = False

        t = settings.get_theme()
        self.configure(bg=t["bg"])
        self.title("Settings")
        self.geometry("480x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # -- Source --
        ttk.Label(main, text="Image source", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))
        self.source_var = tk.StringVar(value=settings.source)
        src_frame = ttk.Frame(main)
        src_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Radiobutton(src_frame, text="Apple Music (recommended)", variable=self.source_var,
                         value="apple_music").pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(src_frame, text="Deezer", variable=self.source_var,
                         value="deezer").pack(side=tk.LEFT)

        # -- Theme --
        ttk.Label(main, text="Theme", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))
        self.theme_var = tk.StringVar(value=settings.theme)
        theme_row = ttk.Frame(main)
        theme_row.pack(fill=tk.X, pady=(0, 14))
        for theme_name in THEMES:
            ttk.Radiobutton(theme_row, text=theme_name.title(), variable=self.theme_var,
                             value=theme_name).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 14))

        # -- Output --
        ttk.Label(main, text="Output", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))

        self.filename_var = tk.BooleanVar(value=settings.artist_filename)
        self.filename_cb = ttk.Checkbutton(main, text='Use artist name as filename (e.g. "Pink Floyd.jpg")',
                                            variable=self.filename_var)
        self.filename_cb.pack(anchor=tk.W)
        if settings.separate_folder:
            self.filename_cb.configure(state=tk.DISABLED)

        # -- Format selector --
        fmt_row = ttk.Frame(main)
        fmt_row.pack(fill=tk.X, pady=(4, 2))
        self.format_var = tk.StringVar(value=settings.output_format)
        ttk.Label(fmt_row, text="Format:").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(fmt_row, text="JPEG (.jpg)", variable=self.format_var,
                         value="jpeg", command=self._toggle_quality).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(fmt_row, text="PNG (.png)", variable=self.format_var,
                         value="png", command=self._toggle_quality).pack(side=tk.LEFT)

        ttk.Label(main, text="Apple Music: JPEG or PNG (varies by artist). Deezer: always JPEG.",
                   style="Dim.TLabel", wraplength=420).pack(anchor=tk.W, pady=(0, 4))

        # -- Quality slider (visible only for JPEG) --
        self.quality_frame = ttk.Frame(main)
        self.quality_var = tk.IntVar(value=settings.jpeg_quality)
        q_header = ttk.Frame(self.quality_frame)
        q_header.pack(fill=tk.X)
        ttk.Label(q_header, text="JPEG quality:").pack(side=tk.LEFT)
        self.quality_val_label = ttk.Label(q_header, text=str(settings.jpeg_quality),
                                            style="Dim.TLabel")
        self.quality_val_label.pack(side=tk.RIGHT)
        self.quality_scale = ttk.Scale(
            self.quality_frame, from_=10, to=100, variable=self.quality_var,
            orient=tk.HORIZONTAL, command=self._on_quality_change,
        )
        self.quality_scale.pack(fill=tk.X)
        ttk.Label(self.quality_frame, text="10 = small file ? 100 = best quality",
                   style="Dim.TLabel").pack(anchor=tk.W)

        # Reference widget -- the frame BELOW quality_frame, so we can pack before it
        self.merge_skip_var = tk.BooleanVar(value=settings.skip_merge_dialog)
        self.merge_cb = ttk.Checkbutton(main, text="Skip merge dialog (auto-apply saved aliases)",
                                         variable=self.merge_skip_var)
        self.merge_cb.pack(anchor=tk.W)

        self._toggle_quality()  # show/hide based on current format

        sep_frame = ttk.Frame(main)
        sep_frame.pack(fill=tk.X, pady=(8, 4))
        self.sep_var = tk.BooleanVar(value=bool(settings.separate_folder))
        ttk.Checkbutton(sep_frame, text="Save to separate folder",
                         variable=self.sep_var,
                         command=self._toggle_sep_folder).pack(anchor=tk.W, side=tk.LEFT)
        self.sep_path_var = tk.StringVar(value=settings.separate_folder)
        self.sep_entry = ttk.Entry(sep_frame, textvariable=self.sep_path_var, state=tk.NORMAL if settings.separate_folder else tk.DISABLED)
        self.sep_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4))
        self.sep_btn = ttk.Button(sep_frame, text="Browse", style="Small.TButton",
                                   command=self._browse_sep,
                                   state=tk.NORMAL if settings.separate_folder else tk.DISABLED)
        self.sep_btn.pack(side=tk.LEFT)

        # -- Buttons --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btn_frame, text="Apply", style="Accent.TButton",
                   command=self._apply).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="Cancel", style="Small.TButton",
                   command=self.destroy).pack(side=tk.RIGHT)

    def _toggle_quality(self):
        """Show quality slider only when JPEG format is selected."""
        if self.format_var.get() == "jpeg":
            # Pack BEFORE the merge checkbox, not at the end
            self.quality_frame.pack(before=self.merge_cb, fill=tk.X, pady=(4, 10))
            # Force ttk.Scale to sync its visual position with the variable
            # (pack_forget + pack can lose the visual state on Windows)
            self.after_idle(lambda: self.quality_var.set(self.quality_var.get()))
        else:
            self.quality_frame.pack_forget()

    def _on_quality_change(self, _=None):
        """Update the quality value label as slider moves."""
        self.quality_val_label.configure(text=str(self.quality_var.get()))

    def _toggle_sep_folder(self):
        sep_on = self.sep_var.get()
        state = tk.NORMAL if sep_on else tk.DISABLED
        self.sep_entry.configure(state=state)
        self.sep_btn.configure(state=state)
        # Filename option is meaningless in separate folder mode (all would collide)
        self.filename_cb.configure(state=tk.DISABLED if sep_on else tk.NORMAL)

    def _browse_sep(self):
        folder = filedialog.askdirectory(title="Select output folder for artist images")
        if folder:
            self.sep_path_var.set(folder)

    def _apply(self):
        self.settings.source = self.source_var.get()
        self.settings.theme = self.theme_var.get()
        self.settings.artist_filename = self.filename_var.get() if not self.sep_var.get() else True
        self.settings.output_format = self.format_var.get()
        self.settings.jpeg_quality = self.quality_var.get()
        self.settings.skip_merge_dialog = self.merge_skip_var.get()
        self.settings.separate_folder = self.sep_path_var.get() if self.sep_var.get() else ""
        self.on_apply()
        self.destroy()


class MergeArtistsDialog(tk.Toplevel):
    """Dialog to review and merge similar artist names found during scan."""

    def __init__(self, parent: App, groups: list[list[str]], artists):
        super().__init__(parent)
        self.groups = groups
        self.artists = artists

        # Per-group state
        self.name_vars: list[tk.StringVar] = []
        self.skip_vars: list[tk.BooleanVar] = []

        t = parent.settings.get_theme()
        self.configure(bg=t["bg"])
        self.title("Merge Duplicate Artists")
        self.geometry("640x520")
        self.minsize(520, 350)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # -- Header --
        ttk.Label(
            main,
            text=f"Found {len(groups)} group(s) of similar artist names.\n"
            "Select the main name to keep for each group.",
            style="Warning.TLabel",
            wraplength=580,
        ).pack(anchor=tk.W, pady=(0, 12))

        # -- Scrollable area for groups --
        canvas_frame = ttk.Frame(main)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        canvas = tk.Canvas(canvas_frame, bg=t["bg"], bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mw(event=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mw(event=None):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_mw)
        canvas.bind("<Leave>", _unbind_mw)

        # -- Build each group --
        for idx, group in enumerate(groups):
            group_frame = ttk.LabelFrame(scrollable, text=f"Group {idx + 1}", padding=10)
            group_frame.pack(fill=tk.X, pady=(0, 8), padx=4)

            # Default: keep the first (most common) name
            name_var = tk.StringVar(value=group[0])
            self.name_vars.append(name_var)

            for name in group:
                ctx = artists.get(name)
                radio_frame = ttk.Frame(group_frame)
                radio_frame.pack(fill=tk.X, pady=2)

                ttk.Radiobutton(
                    radio_frame, text=name, variable=name_var, value=name
                ).pack(anchor=tk.W, side=tk.LEFT)

                # Show albums/genres as context
                if ctx:
                    info_parts = []
                    album_list = sorted(ctx.albums)[:3]
                    if album_list:
                        text = ", ".join(album_list)
                        if len(ctx.albums) > 3:
                            text += f" (+{len(ctx.albums) - 3} more)"
                        info_parts.append(f"Albums: {text}")
                    genre_list = sorted(ctx.genres)[:3]
                    if genre_list:
                        text = ", ".join(genre_list)
                        if len(ctx.genres) > 3:
                            text += f" (+{len(ctx.genres) - 3} more)"
                        info_parts.append(f"Genres: {text}")
                    if info_parts:
                        ttk.Label(
                            radio_frame,
                            text=" | ".join(info_parts),
                            style="Dim.TLabel",
                            wraplength=380,
                        ).pack(anchor=tk.W, side=tk.LEFT, padx=(16, 0))

            # Skip checkbox for this group
            skip_var = tk.BooleanVar(value=False)
            self.skip_vars.append(skip_var)
            ttk.Checkbutton(
                group_frame,
                text="Don't merge this group (keep separate)",
                variable=skip_var,
            ).pack(anchor=tk.W, pady=(4, 0))

        # -- Save aliases checkbox --
        self.save_aliases_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main,
            text="Remember these choices as permanent aliases",
            variable=self.save_aliases_var,
        ).pack(anchor=tk.W, pady=(0, 12))

        # -- Buttons --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame, text="Skip All", style="Small.TButton", command=self._skip_all
        ).pack(side=tk.LEFT)
        ttk.Button(
            btn_frame, text="Cancel", style="Small.TButton", command=self._cancel
        ).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(
            btn_frame, text="Apply", style="Accent.TButton", command=self._apply
        ).pack(side=tk.RIGHT, padx=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Center on parent
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _skip_all(self):
        """Skip all merges -- keep artists as separate."""
        self.master._merge_result = {}
        self.destroy()

    def _apply(self):
        """Build merge map from user selections and save aliases if requested."""
        merge_map: dict[str, str] = {}
        for i, group in enumerate(self.groups):
            if self.skip_vars[i].get():
                continue
            canonical = self.name_vars[i].get()
            for name in group:
                if name != canonical:
                    merge_map[name] = canonical

        if merge_map and self.save_aliases_var.get():
            self.master.settings.artist_aliases.update(merge_map)
            self.master.settings.save()

        self.master._merge_result = merge_map
        self.destroy()

    def _cancel(self):
        """Cancel -- stop the whole operation."""
        self.master._merge_result = None
        self.destroy()


class ArtistChoiceDialog(tk.Toplevel):
    """Dialog when multiple API artists have the same name -- user picks one."""

    def __init__(self, parent: App, artist_name: str, candidates):
        super().__init__(parent)
        self.candidates = list(candidates)
        self._preview_request_id = 0  # incremented on each click to cancel stale threads

        t = parent.settings.get_theme()
        self.configure(bg=t["bg"])
        self.title(f"Choose artist: {artist_name}")
        self.geometry("640x420")
        self.minsize(560, 350)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text=f"Multiple artists found with the name \"{artist_name}\".\n"
            "Select the correct one:",
            style="Warning.TLabel", wraplength=600,
        ).pack(anchor=tk.W, pady=(0, 12))

        # -- Content: listbox on left, preview on right --
        content = ttk.Frame(main)
        content.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        # Left side: listbox
        list_frame = ttk.Frame(content)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 12))

        self.listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 10), bd=0,
            highlightthickness=0, selectbackground=t["list_select"],
            bg=t["entry_bg"], fg=t["entry_fg"],
        )
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for i, c in enumerate(self.candidates):
            source_name = self._source_label(c.source)
            genre_text = f" ({c.genre})" if c.genre else ""
            self.listbox.insert(tk.END, f"{c.name}{genre_text}  --  {source_name}")
        self.listbox.selection_set(0)

        def on_select(event):
            sel = self.listbox.curselection()
            if sel:
                self._show_preview(sel[0])

        self.listbox.bind("<<ListboxSelect>>", on_select)
        self.listbox.focus_set()

        # Right side: preview panel
        preview_frame = ttk.Frame(content, width=220)
        preview_frame.pack(side=tk.RIGHT, fill=tk.Y)
        preview_frame.pack_propagate(False)

        self.preview_label = ttk.Label(
            preview_frame, text="\n\n\nPreview\n\n\n",
            style="Dim.TLabel", anchor=tk.CENTER,
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # Show preview for first candidate immediately
        self.after(100, lambda: self._show_preview(0))

        # -- Buttons --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame, text="Skip", style="Small.TButton",
            command=self._skip,
        ).pack(side=tk.LEFT)
        ttk.Button(
            btn_frame, text="Cancel", style="Small.TButton",
            command=self._cancel,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(
            btn_frame, text="Select", style="Accent.TButton",
            command=self._apply,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Center on parent
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    @staticmethod
    def _source_label(source: str) -> str:
        return "Apple Music" if source == "apple_music" else "Deezer"

    def _show_preview(self, idx: int):
        """Fetch and display a thumbnail preview for the candidate at idx.
        Runs HTTP in a background thread to avoid freezing the GUI.
        """
        if idx < 0 or idx >= len(self.candidates):
            return
        candidate = self.candidates[idx]
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self.preview_label.configure(text="\n\nLoading...\n\n")

        def _fetch():
            try:
                data = fetch_candidate_preview(candidate)
                self.after(0, self._display_preview, request_id, idx, data)
            except Exception:
                self.after(0, self._display_preview, request_id, idx, None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _display_preview(self, request_id: int, idx: int, data: Optional[bytes]):
        """Display the fetched preview on the main thread (called via after())."""
        if request_id != self._preview_request_id:
            return  # stale request, user clicked another candidate

        if not data:
            self.preview_label.configure(text="\n\nNo preview\navailable\n\n")
            return

        try:
            from PIL import Image, ImageTk
            import io
            img = Image.open(io.BytesIO(data))
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=photo, text="")
            self.preview_label.image = photo
        except Exception:
            self.preview_label.configure(text="\n\nPreview\nerror\n\n")

    def _apply(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Please select an artist from the list.", parent=self)
            return
        self.master._artist_choice = self.candidates[sel[0]]
        self.destroy()

    def _skip(self):
        self.master._artist_choice = None
        self.destroy()

    def _cancel(self):
        self.master._artist_choice = None
        self.destroy()
