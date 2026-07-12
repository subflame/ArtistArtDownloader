"""Main GUI for Artist Art Downloader — Experimental UX/UI version."""

import sys
import os
import base64
import io
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
import pystray

from .config import Settings, THEMES, ArtistCache, CONFIG_DIR
from .scanner import scan_folder, artist_image_exists, get_artist_root, find_similar_artists, merge_artists, split_artists
from .utils import sanitize_filename
from .fetcher import fetch_artist_image, download_image, search_artist_candidates, fetch_artist_image_by_id, fetch_candidate_preview, fetch_artist_image_by_track_only, fetch_artist_image_by_album_only
from . import __version__ as APP_VERSION

_SESSION_FILE = CONFIG_DIR / "session.json"
_SESSION_FILE = CONFIG_DIR / "session.json"

# Try to import tkinterdnd2 for drag-and-drop support
try:
    import tkinterdnd2 as tkdnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

# Embedded .ico data (base64, multi-res 16/32/48/64/128/256)
_ICON_B64 = "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAE3klEQVR4nO3dPYtcVRzA4bu6QkTwO2gs1EYUw5Ii+BJFk0Bsg2/phI3YWLiwWAfS2IimSGU6ESwsjCCpUoRgavUDmC9gEAPZJRKrgASJs+vcOb/nqcIWk5PZmR//O2fuyTQBAAAAAAAAAAAAq2tt2QuouHzl6p1lr2HVHD1y2Otznz20338BMF8CAGECAGECAGECAGECAGECAGECAGECAGF7/k2rF4+9P+tvvJ3b3lz2Epi5rbPnpzm7funinr1vTQAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQtr7sBUDpW3xzYwKAMAGAMAGAMJ8BMLRbf/y+b4994LHHp1VnAoAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwAYAwx4IztBGO7t5PJgAIEwAIEwAI8xkAQzm3vbnwY2yF/otxEwCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCE5c4ELJ33Bv/GBABhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhsz8S7Kfvv1r2EmAhh46fnubKBABhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhAgBhsz8TcFHXrl1b9hJYcRsbG9OoTAAQJgAQJgAQJgAQJgAQJgAQNvw24MhbOLAoEwCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCECQCEDX8zkDMBWdTGwDeUmQAgTAAgTAAgTAAgTAAgTAAgbPhtwJG3cGBRJgAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIG/5mIGcCsqiNgW8oMwFAmABAmABAmABAmABAmABA2PDbgCNv4cCiTAAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQJgAQNvzNQM4EZFEbA99QZgKAMAGAMAGAMAGAMAGAMAGAsOG3AUfewoFFmQAgTAAgTAAgTAAgTAAgTAAgTAAgTAAgTAAgTAAgTAAgTAAgbPibgZwJyKI2Br6hzAQAYQIAYQIAYQIAYQIAYQIAYcNvA468hQOLMgFAmABAmABAmABAmABAmABAmABAmABAmABAmABAmABAmABAmABA2OzvBjx0/PSylwDDMgFAmABAmABAmABA2Ow/BIS7zm1vLu2J2Dp7fthfggkAwgQAwgQAwnwGwMo6+ebr03c//Hjfnx1/7eXp6Weenaa1tWnn9u3pxMm3pjeOnVjSaudJABjW+voj02eff/n3n2/d+nP6dOuT6cCBR6eXXnl12UubDZcAJNx9439w5sPp22++XvZSZkUAyHjy4FPTjRu/LXsZs+ISgJW1s3N7+vijM//42f3s7u5O6w97yd/Ls8EQ1/j3fgh4P7/+8vP0xMGD/8PKVodLABJu3rw5XTj/xXTq7XeXvZSxJ4Drly6u7fVjwrS9eec/XyKsrU27OzvTqXfem557/oUHfjKvD/yaHvYfxlguX7n6wAHYK0ePHB72feISAMIEAAAAAAAAAAAAAAAAAAAAAKbZ+QuKQHEj8yLFNQAAAABJRU5ErkJggg=="

_LOG_PLACEHOLDER = "Drag a music folder here, or click Browse to select one.\nThen press Start to begin."


def _load_icon_photo():
    """Load embedded icon as PIL PhotoImage from in-memory base64 data."""
    from PIL import Image, ImageTk
    data = base64.b64decode(_ICON_B64)
    img = Image.open(io.BytesIO(data))
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    small = img.resize((64, 64), Image.LANCZOS)
    return ImageTk.PhotoImage(small)


# ---------------------------------------------------------------------------
# Prompt dialog helper — eliminates duplication in _prompt_*
# ---------------------------------------------------------------------------

def _prompt_dialog(parent, dialog_class, *args):
    """Show a modal dialog from a background thread. Blocks until user responds.

    Returns the dialog's result attribute, or None if the dialog was closed.
    """
    result = None
    event = threading.Event()

    def show():
        nonlocal result
        dlg = dialog_class(parent, *args)
        parent.wait_window(dlg)
        result = getattr(dlg, '_dialog_result', None)
        event.set()

    parent.after(0, show)
    while not event.wait(timeout=0.5):
        if not parent.running:
            return None
    return result


class App(tk.Tk if not HAS_DND else tkdnd.Tk):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.cache = ArtistCache()
        self.running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._run_counter = 0
        self.results: list[tuple[str, str, str]] = []
        self._failed_items: list[tuple[str, str, Path, str]] = []
        self._retry_names: set[str] = set()
        self._session_work_items: list = []
        self._session_search_results: list = []
        self._session_downloaded = 0
        self._session_skipped = 0
        self._session_failed = 0
        self._session_phase = 1  # 1=searching, 2=downloading

        self.title(f"Artist Art Downloader v{APP_VERSION}")
        geo = f"{self.settings.window_width}x{self.settings.window_height}"
        if self.settings.window_x >= 0 and self.settings.window_y >= 0:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            if self.settings.window_x < sw and self.settings.window_y < sh:
                geo += f"+{self.settings.window_x}+{self.settings.window_y}"
        self.geometry(geo)
        self.minsize(600, 500)

        # Set window icon
        try:
            photo = _load_icon_photo()
            self.iconphoto(True, photo)
            self._taskbar_photo = photo
        except Exception:
            pass

        self._apply_theme()
        self._build_ui()
        self._apply_theme_to_widgets()

        if self.settings.last_folder:
            self.folder_var.set(self.settings.last_folder)
            self._sync_recent_folders()

        # System tray — minimize → tray, Win+↓ → tray, X → confirm + quit
        self._tray_icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._tray_capable = True
        self._original_iconify = self.iconify
        self.iconify = self._minimize_to_tray  # type: ignore[method-assign]
        self.protocol("WM_DELETE_WINDOW", self._on_close_confirm)
        # Set proper 64-bit argtypes for WinAPI calls used in polling
        try:
            ctypes.windll.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            ctypes.windll.user32.GetAncestor.restype = wintypes.HWND
            ctypes.windll.user32.IsIconic.argtypes = [wintypes.HWND]
            ctypes.windll.user32.IsIconic.restype = wintypes.BOOL
        except Exception:
            pass
        self.after(50, self._check_minimize_poll)

        # Hotkeys
        self.bind("<Return>", lambda e: self._resume() if self._paused else self._start())
        self.bind("<Escape>", lambda e: self._stop())
        self.bind("<Control-o>", lambda e: self._browse_folder())

        # Check for saved session to resume
        self.after(100, self._check_resume_session)

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
        style.configure("Phase.TLabel", font=("Segoe UI", 9, "italic"),
                         background=t["bg"], foreground=t["fg_dim"])
        style.configure("Success.TLabel", foreground=t["success"], background=t["bg"])
        style.configure("Error.TLabel", foreground=t["error"], background=t["bg"])
        style.configure("Warning.TLabel", foreground=t["warning"], background=t["bg"])
        style.configure("Counter.TLabel", font=("Segoe UI", 10, "bold"),
                         background=t["bg"], foreground=t["fg"])

        style.configure("TButton", font=("Segoe UI", 10, "bold"),
                         padding=(16, 8))
        style.map("TButton",
                   background=[("active", t["accent_hover"]), ("!active", t["button_bg"])],
                   foreground=[("active", t["button_fg"]), ("!active", t["button_fg"])])

        style.configure("Small.TButton", font=("Segoe UI", 9), padding=(10, 4))
        style.map("Small.TButton",
                   background=[("active", t["bg_hover"]), ("!active", t["bg_secondary"])],
                   foreground=[("active", t["fg"]), ("!active", t["fg"])])

        style.configure("Accent.TButton", font=("Segoe UI", 11, "bold"), padding=(24, 12))
        style.map("Accent.TButton",
                   background=[("active", t["accent_hover"]), ("!active", t["accent"])],
                   foreground=[("active", t["button_fg"]), ("!active", t["button_fg"])])

        style.configure("Stop.TButton", font=("Segoe UI", 10), padding=(16, 8))
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
                         background=t["fg_dim"], troughcolor=t["bg"])
        style.configure("Horizontal.TScale",
                         background=t["fg_dim"], troughcolor=t["bg"])

        style.configure("Log.TFrame", background=t["list_bg"])
        style.configure("Log.TLabel", background=t["list_bg"], foreground=t["fg"],
                         font=("Consolas", 10))

        style.configure("TSeparator", background=t["border"])

        style.configure("TLabelframe", background=t["bg"], foreground=t["fg"])
        style.configure("TLabelframe.Label", background=t["bg"], foreground=t["accent"],
                         font=("Segoe UI", 10, "bold"))

        style.configure("TSpinbox", fieldbackground=t["entry_bg"],
                         background=t["entry_bg"], foreground=t["entry_fg"],
                         arrowcolor=t["fg"], padding=4)

    # -- UI Construction ---------------------------------------------------

    def _build_ui(self):
        t = self.settings.get_theme()

        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # -- Header --
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(header, text="Artist Art Downloader", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Settings", style="Small.TButton",
                   command=self._open_settings).pack(side=tk.RIGHT)

        # -- Source frame (folder picker + recent + skip) --
        source_frame = ttk.LabelFrame(main, text="  Source  ", padding=12)
        source_frame.pack(fill=tk.X, pady=(0, 12))

        # Recent folders row
        recent_row = ttk.Frame(source_frame)
        recent_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(recent_row, text="Recent:").pack(side=tk.LEFT, padx=(0, 6))
        self.recent_var = tk.StringVar()
        self.recent_combo = ttk.Combobox(recent_row, textvariable=self.recent_var,
                                          state="readonly", font=("Segoe UI", 9))
        self.recent_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.recent_combo.bind("<<ComboboxSelected>>", self._on_recent_select)

        # Folder picker row
        folder_row = ttk.Frame(source_frame)
        folder_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(folder_row, text="Folder:").pack(side=tk.LEFT, padx=(0, 6))
        self.folder_var = tk.StringVar()
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(folder_row, text="Browse", style="Small.TButton",
                   command=self._browse_folder).pack(side=tk.RIGHT)

        # Drag-and-drop hint
        if HAS_DND:
            self.folder_entry.drop_target_register(tkdnd.DND_FILES)
            self.folder_entry.dnd_bind("<<Drop>>", self._on_drop)
            self.folder_entry.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.folder_entry.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # Skip checkbox
        self.skip_var = tk.BooleanVar(value=self.settings.skip_existing)
        ttk.Checkbutton(source_frame, text="Skip artists with existing artist.jpg",
                         variable=self.skip_var).pack(anchor=tk.W)

        # -- Action buttons --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.start_btn = ttk.Button(btn_frame, text="Start", style="Accent.TButton",
                                     command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = ttk.Button(btn_frame, text="Stop", style="Stop.TButton",
                                     command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        self.pause_btn = ttk.Button(btn_frame, text="Pause", style="Small.TButton",
                                     command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.retry_btn = ttk.Button(btn_frame, text="Retry Failed", style="Small.TButton",
                                     command=self._retry_failed, state=tk.DISABLED)
        self.retry_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.export_btn = ttk.Button(btn_frame, text="Export Log", style="Small.TButton",
                                      command=self._export_log)
        self.export_btn.pack(side=tk.RIGHT)

        # -- Progress --
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(main, variable=self.progress_var,
                                         maximum=100, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 2))

        self.phase_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.phase_var, style="Phase.TLabel").pack(anchor=tk.W)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var, style="Dim.TLabel").pack(anchor=tk.W, pady=(0, 4))

        self.counter_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.counter_var, style="Counter.TLabel").pack(anchor=tk.W, pady=(0, 8))

        # -- Log --
        log_frame = ttk.Frame(main, style="Log.TFrame", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD,
                                 bg=t["list_bg"], fg=t["fg"],
                                 font=("Consolas", 10), bd=0, highlightthickness=0,
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
        self.log_text.tag_configure("placeholder", foreground=t["fg_dim"],
                                     font=("Segoe UI", 10, "italic"))

        # Right-click context menu for log
        self._log_menu = tk.Menu(self, tearoff=0)
        self._log_menu.add_command(label="Open Folder in Explorer", command=self._open_log_folder)
        self._log_menu.add_separator()
        self._log_menu.add_command(label="Copy Line", command=self._copy_log_line)
        self.log_text.bind("<Button-3>", self._show_log_menu)

        # Show placeholder
        self._show_placeholder()

    # -- Placeholder -------------------------------------------------------

    def _show_placeholder(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", _LOG_PLACEHOLDER, "placeholder")
        self.log_text.configure(state=tk.DISABLED)
        self._log_visible = False

    def _ensure_log_active(self):
        """Remove placeholder and enable log for writing."""
        if not getattr(self, '_log_visible', True):
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete("1.0", tk.END)
            self.log_text.configure(state=tk.DISABLED)
            self._log_visible = True

    # -- Drag and Drop -----------------------------------------------------

    def _on_drop(self, event):
        if not HAS_DND:
            return
        data = event.data
        # Strip braces that tkinterdnd2 adds around paths with spaces
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        # Handle multiple files — take the first directory
        paths = self.splitlist(data) if hasattr(self, 'splitlist') else [data]
        for p in paths:
            p = p.strip()
            if Path(p).is_dir():
                self.folder_var.set(p)
                self._add_recent_folder(p)
                return
        messagebox.showwarning("Invalid Drop", "Please drop a folder, not a file.")

    def _on_drag_enter(self, event):
        if HAS_DND:
            self.folder_entry.configure(foreground="#3fb950")
            return event.action

    def _on_drag_leave(self, event):
        t = self.settings.get_theme()
        self.folder_entry.configure(foreground=t["entry_fg"])

    def _splitlist(self, data: str) -> list[str]:
        """Split tkinterdnd2 drop data (handles braced paths with spaces)."""
        import re
        return [p.strip('{}') for p in re.findall(r'\{[^}]+\}|[^\s]+', data)]

    # -- Recent Folders ----------------------------------------------------

    def _sync_recent_folders(self):
        folders = self.settings.recent_folders
        self.recent_combo["values"] = folders
        if folders and self.folder_var.get() in folders:
            self.recent_var.set(self.folder_var.get())
        elif folders:
            self.recent_var.set("")

    def _add_recent_folder(self, folder: str):
        self.settings.add_recent_folder(folder)
        self._sync_recent_folders()

    def _on_recent_select(self, event=None):
        selected = self.recent_var.get()
        if selected and Path(selected).is_dir():
            self.folder_var.set(selected)

    # -- Actions -----------------------------------------------------------

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select music folder",
                                          initialdir=self.folder_var.get() or None)
        if folder:
            self.folder_var.set(folder)
            self._add_recent_folder(folder)
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
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        if threading.current_thread() is threading.main_thread():
            self._ensure_log_active()
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, line + "\n", tag)
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
        self.log_text.tag_configure("placeholder", foreground=t["fg_dim"],
                                     font=("Segoe UI", 10, "italic"))

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self._log_visible = False

    def _export_log(self, path: str = ""):
        if not path:
            if self.running:
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Export Log",
            )
            if not path:
                return
        try:
            text = self.log_text.get("1.0", tk.END)
            Path(path).write_text(text, encoding="utf-8")
            if not self.running:
                self._log(f"Log saved to: {path}", "success")
        except Exception as e:
            self._log(f"Failed to save log: {e}", "error")

    def _auto_export_log(self):
        """Auto-export log next to the executable on errors."""
        from datetime import datetime
        exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = exe_dir / f"ArtistArtDownloader_{ts}.log"
        try:
            text = self.log_text.get("1.0", tk.END)
            path.write_text(text, encoding="utf-8")
        except Exception:
            pass

    def _show_log_menu(self, event):
        self._log_menu.event_x = event.x
        self._log_menu.event_y = event.y
        self._log_menu.click_index = self.log_text.index(f"@{event.x},{event.y}")
        self._log_menu.tk_popup(event.x_root, event.y_root)

    def _open_log_folder(self):
        idx = getattr(self._log_menu, "click_index", None)
        if not idx:
            return
        line = self.log_text.get(f"{idx} linestart", f"{idx} lineend")
        # Parse "Saved to:" lines from the log
        if "Saved to:" in line:
            path = line.split("Saved to:", 1)[1].strip()
            if Path(path).is_dir():
                os.startfile(path)
                return
        # Fallback: try each word on the line
        for word in line.split():
            p = Path(word)
            if p.exists() and p.is_dir():
                os.startfile(str(p))
                return
            if p.exists() and p.parent.exists():
                os.startfile(str(p.parent))
                return
        messagebox.showinfo("Cannot Open", "No folder path found on this line.")

    def _copy_log_line(self):
        idx = getattr(self._log_menu, "click_index", None)
        if not idx:
            return
        line = self.log_text.get(f"{idx} linestart", f"{idx} lineend")
        self.clipboard_clear()
        self.clipboard_append(line)

    def _show_preview_in_log(self, file_path: Path):
        """Show a thumbnail preview in the log after download."""
        try:
            from PIL import Image, ImageTk
            img = Image.open(str(file_path))
            img.thumbnail((80, 80))
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

    # -- System Tray -------------------------------------------------------

    # -- System Tray ---------------------------------------------------------

    def _create_tray_icon(self) -> pystray.Icon:
        from PIL import Image, ImageDraw
        data = base64.b64decode(_ICON_B64)
        try:
            img = Image.open(io.BytesIO(data))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            small = img.resize((64, 64), Image.LANCZOS)
        except Exception:
            small = Image.new('RGBA', (64, 64), (64, 128, 255, 255))
            d = ImageDraw.Draw(small)
            d.ellipse([6, 6, 58, 58], fill=(255, 255, 255, 255))
            try:
                d.text((22, 14), "A", fill=(64, 128, 255, 255))
            except Exception:
                pass

        def on_show(_icon, _item):
            self.after(0, self._restore_from_tray)

        def on_quit(_icon, _item):
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

    def _check_minimize_poll(self):
        if not getattr(self, '_minimizing_to_tray', False):
            try:
                hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)
                if hwnd and ctypes.windll.user32.IsIconic(hwnd):
                    self._minimize_to_tray()
            except Exception:
                pass
        self.after(50, self._check_minimize_poll)

    def _on_close_confirm(self):
        """Close button (X) → confirm dialog → quit."""
        try:
            import tkinter.messagebox as mb
            ok = mb.askyesno(
                "Exit",
                "Are you sure you want to exit?",
                parent=self,
                icon='question',
                default='no',
            )
        except Exception:
            ok = True
        if ok:
            self._quit_from_tray()

    def _minimize_to_tray(self, event=None):
        if not self._tray_capable:
            if self.state() in ('normal', 'iconic'):
                self._original_iconify()
            return
        if getattr(self, '_minimizing_to_tray', False):
            return
        self._minimizing_to_tray = True
        try:
            if self.state() in ('withdrawn',):
                return
            if self.state() != 'iconic':
                self.wm_state('iconic')
            self.withdraw()
            if self._tray_icon is not None:
                return
            icon = self._create_tray_icon()
            self._tray_icon = icon
            self._tray_thread = threading.Thread(
                target=self._run_tray_thread, args=(icon,), daemon=True,
            )
            self._tray_thread.start()
        except Exception:
            self._tray_capable = False
            try:
                if self.state() == 'withdrawn':
                    self.deiconify()
            except Exception:
                pass
        finally:
            self._minimizing_to_tray = False

    def _run_tray_thread(self, icon: pystray.Icon):
        try:
            icon.run()
        except Exception:
            self.after(0, self._on_tray_failed)

    def _on_tray_failed(self):
        self._tray_icon = None
        self._tray_thread = None
        self._tray_capable = False
        try:
            import tkinter.messagebox as mb
            mb.showerror(
                "Error",
                "Could not create system tray icon.\n"
                "Please restart the app.",
                parent=self,
            )
        except Exception:
            pass
        if self.state() == 'withdrawn':
            self.deiconify()

    def _restore_from_tray(self):
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
        if self.running:
            self._save_session()
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
        self._paused = False
        self._pause_event.set()
        if self.running:
            self._save_session()
        self.running = False
        self.status_var.set("Stopping...")

    def _save_settings(self):
        try:
            self.settings.window_width = self.winfo_width()
            self.settings.window_height = self.winfo_height()
            self.settings.window_x = self.winfo_x()
            self.settings.window_y = self.winfo_y()
            self.settings.save()
            self.cache.save()
        except Exception:
            pass

    def _update_tray_tooltip(self, text: str):
        try:
            if self._tray_icon is not None:
                self._tray_icon.title = f"Artist Art Downloader v{APP_VERSION} — {text}"
        except Exception:
            pass

    # -- Pause / Resume ----------------------------------------------------

    def _toggle_pause(self):
        if self._paused:
            self._resume()
        else:
            self._pause()

    def _pause(self):
        self._paused = True
        self._pause_event.clear()
        self.pause_btn.configure(text="Resume")
        self.status_var.set("Paused")
        self._log("Paused.", "warning")
        self._save_session()

    def _resume(self):
        self._paused = False
        self._pause_event.set()
        self.pause_btn.configure(text="Pause")
        self.status_var.set("Resumed")
        self.after(0, self._update_tray_tooltip, "Resumed")
        self._log("Resumed.", "info")
        self._clear_session()

    def _check_pause(self):
        """Block if paused; return False if stopped while waiting."""
        if self._paused and self.running:
            self.after(0, self._update_tray_tooltip, "Paused")
        while self._paused and self.running:
            self._pause_event.wait(timeout=0.5)
        return self.running

    # -- Session persistence (resume after restart) ------------------------

    @staticmethod
    def _serialize_context(ctx) -> dict:
        return {
            "albums": list(ctx.albums),
            "genres": list(ctx.genres),
            "track_names": list(ctx.track_names),
            "album_track_counts": dict(ctx.album_track_counts),
            "album_years": dict(ctx.album_years),
            "album_dirs": [str(p) for p in ctx.album_dirs],
        }

    @staticmethod
    def _deserialize_context(d: dict):
        from .scanner import ArtistContext
        return ArtistContext(
            albums=set(d.get("albums", [])),
            genres=set(d.get("genres", [])),
            track_names=set(d.get("track_names", [])),
            album_track_counts=dict(d.get("album_track_counts", {})),
            album_years=dict(d.get("album_years", {})),
            album_dirs={Path(p) for p in d.get("album_dirs", [])},
        )

    def _save_session(self):
        """Save current processing state so it can be resumed after restart."""
        import json
        try:
            completed = []
            remaining_names = []
            remaining_contexts = {}
            # Atomic snapshot to avoid race with worker thread
            snapshot_results = list(self._session_search_results)
            snapshot_work = list(self._session_work_items)
            for item in snapshot_results:
                name, url, save_path, err = item
                completed.append([name, url or "", str(save_path), err or ""])
            processed_names = {item[0] for item in snapshot_results}
            for item in snapshot_work:
                name = item[0]
                if name not in processed_names:
                    remaining_names.append(name)
                    remaining_contexts[name] = self._serialize_context(item[1])

            state = {
                "folder": self.folder_var.get(),
                "source": self.settings.source,
                "skip_existing": self.skip_var.get(),
                "phase": self._session_phase,
                "completed_searches": completed,
                "remaining_artists": remaining_names,
                "remaining_contexts": remaining_contexts,
                "downloaded": self._session_downloaded,
                "skipped": self._session_skipped,
                "failed": self._session_failed,
            }
            _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SESSION_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _clear_session(self):
        """Delete saved session file (processing completed or cancelled)."""
        try:
            if _SESSION_FILE.exists():
                _SESSION_FILE.unlink()
        except Exception:
            pass

    def _check_resume_session(self):
        """On startup, prompt to resume a previous interrupted session."""
        import json
        if not _SESSION_FILE.exists():
            return
        try:
            state = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            folder = state.get("folder", "")
            if not folder or not Path(folder).is_dir():
                self._clear_session()
                return
            choice = messagebox.askyesnocancel(
                "Resume Session",
                f"An interrupted session was found for folder:\n{folder}\n\n"
                "Do you want to resume where you left off?\n\n"
                "Yes = Resume   No = Start fresh   Cancel = Exit",
            )
            if choice is None:
                self.quit()
                return
            if not choice:
                self._clear_session()
                return
            # Resume
            self.folder_var.set(folder)
            self.skip_var.set(state.get("skip_existing", False))
            if state.get("source"):
                self.settings.source = state["source"]
            self._start_resume(state)
        except Exception:
            self._clear_session()

    def _start_resume(self, state: dict):
        """Continue processing from saved session state."""
        if self.running:
            return
        folder = state["folder"]
        if not Path(folder).is_dir():
            messagebox.showerror("Error", "The folder no longer exists.")
            self._clear_session()
            return

        self._run_counter += 1
        self.running = True
        self._paused = False
        self._pause_event.set()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.pause_btn.configure(state=tk.NORMAL, text="Pause")
        self.retry_btn.configure(state=tk.DISABLED)
        self._failed_items.clear()
        self._retry_names.clear()
        self.progress_var.set(0)
        self.phase_var.set("")
        self.status_var.set("Resuming...")
        self.counter_var.set("")
        self._clear_log()

        thread = threading.Thread(
            target=self._process_resume,
            args=(Path(folder), state),
            daemon=True,
        )
        thread.start()

    def _process_resume(self, root: Path, state: dict):
        """Resume processing from saved state (no re-scan)."""
        from .scanner import artist_image_exists, get_artist_root, scan_folder, merge_artists

        self.after(0, self._update_tray_tooltip, "Resuming...")
        self._log("Resuming previous session...", "info")

        completed_searches = state.get("completed_searches", [])
        completed_names = {item[0] for item in completed_searches}
        remaining_contexts = state.get("remaining_contexts", {})
        downloaded = state.get("downloaded", 0)
        skipped = state.get("skipped", 0)
        failed = state.get("failed", 0)

        # If no saved contexts (old session format), fall back to re-scan
        if not remaining_contexts:
            self._log("No saved contexts found, re-scanning folder...", "info")
            try:
                from .scanner import scan_folder, merge_artists
                raw_artists = scan_folder(root, skip_existing=state.get("skip_existing", False),
                                          separate_folder=self.settings.separate_folder,
                                          progress_cb=_on_scan_progress)
                if self.settings.artist_aliases:
                    raw_artists = merge_artists(raw_artists, self.settings.artist_aliases)
            except Exception as e:
                self._log(f"Scan error: {e}", "error")
                self._finish()
                return
        else:
            raw_artists = None

        # Build work list from saved contexts (no re-scan)
        work_items = []
        for artist_name in state.get("remaining_artists", []):
            if raw_artists is not None:
                ctx = raw_artists.get(artist_name)
                if not ctx:
                    self._log(f"  [X] {artist_name} -- not found in re-scan", "error")
                    failed += 1
                    continue
            else:
                ctx_data = remaining_contexts.get(artist_name)
                if not ctx_data:
                    self._log(f"  [X] {artist_name} -- no saved context", "error")
                    failed += 1
                    continue
                ctx = self._deserialize_context(ctx_data)
            if not ctx.album_dirs:
                self._log(f"  [X] {artist_name} -- no album directories", "error")
                failed += 1
                continue
            album_dir = next(iter(ctx.album_dirs))
            artist_root = get_artist_root(album_dir, root)
            if (state.get("skip_existing", False)
                    and artist_image_exists(album_dir, root, artist_name,
                                            separate_folder=self.settings.separate_folder)):
                self._log(f"  [>>] {artist_name} -- image exists", "skip")
                skipped += 1
                continue
            work_items.append((artist_name, ctx, artist_root))

        self._log(f"Resuming: {len(work_items)} remaining, {len(completed_searches)} already searched.", "info")

        # Update session state for subsequent pause/save
        self._session_work_items = list(work_items)
        self._session_search_results = list(completed_searches)
        self._session_downloaded = downloaded
        self._session_skipped = skipped
        self._session_failed = failed

        # Phase 1: search remaining artists
        source = state.get("source", self.settings.source)
        search_results = list(completed_searches)

        if work_items:
            self.after(0, self.phase_var.set, "Phase 1/2: Searching remaining...")
            total_work = len(search_results) + len(work_items)
            for i, (artist_name, ctx, artist_root) in enumerate(work_items, 1):
                if not self.running:
                    self._log("Stopped by user.", "warning")
                    break
                idx = len(search_results) + i
                self.after(0, self.status_var.set, f"[{idx}/{total_work}] Searching: {artist_name}")
                self.after(0, self.progress_var.set, (idx / total_work) * 50)
                self.after(0, self._update_tray_tooltip, f"Searching {idx}/{total_work}")

                safe_name = sanitize_filename(artist_name)
                if self.settings.separate_folder:
                    save_dir = Path(self.settings.separate_folder)
                    save_dir.mkdir(parents=True, exist_ok=True)
                    save_path = save_dir / safe_name
                else:
                    base_name = safe_name if self.settings.artist_filename else "artist"
                    save_path = artist_root / base_name

                self._log(f"  {artist_name}", "info")
                self._log(f"     Save to: {save_path}.jpg/.png", "info")
                img_url, error_detail = self._search_artist_image(artist_name, ctx, source)
                if img_url:
                    self._log(f"     [ok] URL found", "success")
                else:
                    self._log(f"     [X] {error_detail}", "error")
                search_results.append((artist_name, img_url, save_path, error_detail))
                self._session_search_results.append((artist_name, img_url, save_path, error_detail))

        # Phase 2: download
        self._do_download_phase(search_results, downloaded, skipped, failed)

    # -- Retry Failed ------------------------------------------------------

    def _retry_failed(self):
        if not self._failed_items:
            return
        self._retry_names = {item[0] for item in self._failed_items}
        self._failed_items.clear()
        self.retry_btn.configure(state=tk.DISABLED)
        self._log(f"\nRetrying {len(self._retry_names)} failed item(s)...\n", "info")
        folder = self.folder_var.get().strip()
        if folder and Path(folder).is_dir():
            thread = threading.Thread(target=self._process, args=(Path(folder),), daemon=True)
            thread.start()

    # -- Processing --------------------------------------------------------

    def _start(self):
        if self.running:
            if self._paused:
                self._resume()
            return
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Error", "Please select a valid music folder.")
            return

        self.running = False
        self.update_idletasks()

        self._run_counter += 1
        self.running = True
        self._paused = False
        self._pause_event.set()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.pause_btn.configure(state=tk.NORMAL, text="Pause")
        self.retry_btn.configure(state=tk.DISABLED)
        self._failed_items.clear()
        self._retry_names.clear()
        self.progress_var.set(0)
        self.phase_var.set("")
        self.status_var.set("Scanning...")
        self.counter_var.set("")
        self._clear_log()
        self._log(f"Artist Art Downloader v{APP_VERSION}", "info")
        self._log("", "")

        self._add_recent_folder(folder)
        self.settings.last_folder = folder
        self.settings.save()

        thread = threading.Thread(target=self._process, args=(Path(folder),), daemon=True)
        thread.start()

    def _process(self, root: Path):
        self.after(0, self._update_tray_tooltip, "Scanning...")
        self._log("Scanning folder for audio files...", "info")

        skip_existing = self.skip_var.get()
        sep_folder = self.settings.separate_folder
        scan_count = 0
        def _on_scan_progress():
            nonlocal scan_count
            scan_count += 1
            self.after(0, self.status_var.set, f"Scanning... ({scan_count} files)")
        try:
            raw_artists = scan_folder(root, skip_existing=skip_existing,
                                      separate_folder=sep_folder,
                                      progress_cb=_on_scan_progress)
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

        # Find similar names
        similar_groups = find_similar_artists(raw_artists)
        if similar_groups:
            if self.settings.skip_merge_dialog:
                self._log(f"Found {len(similar_groups)} group(s) of similar artist names (auto-apply aliases).\n", "info")
            else:
                self._log(f"Found {len(similar_groups)} group(s) of similar artist names.\n", "warning")
                merge_map = self._prompt_merge_artists(similar_groups, raw_artists)
                if merge_map:
                    raw_artists = merge_artists(raw_artists, merge_map)
                    self._log(f"Merged {len(merge_map)} artist alias(es).\n", "success")
                else:
                    self._log("Skipped merging -- keeping original names.\n", "info")

        # Filter to retry-only names when retrying failed
        if self._retry_names:
            matched = sum(1 for n in raw_artists if n in self._retry_names)
            raw_artists = {n: c for n, c in raw_artists.items() if n in self._retry_names}
            self._retry_names.clear()
            self._log(f"  [i] {matched} failed artist(s) matched in current scan.", "info")

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

        # Collect work items — resolve multi-artist names before any search
        work_items = []
        for artist_name, ctx in artists.items():
            if not ctx.album_dirs:
                self._log(f"  [X] {artist_name} -- no album directories", "error")
                failed += 1
                continue
            album_dir = next(iter(ctx.album_dirs))
            artist_root = get_artist_root(album_dir, root)
            # Skip existing images before any interactive dialogs
            if skip_existing and artist_image_exists(album_dir, root, artist_name,
                                                       separate_folder=sep_folder):
                self._log(f"  [>>] {artist_name} -- image exists", "skip")
                skipped += 1
                continue

            # Resolve multi-artist names before search phase
            alternatives = split_artists(artist_name)
            if len(alternatives) > 1:
                self._log(f"  Multiple artists detected: {artist_name}", "info")
                chosen = self._prompt_multi_artist(artist_name, alternatives)
                if not chosen:
                    self._log(f"  [>>] {artist_name} -- skipped by user", "skip")
                    skipped += 1
                    continue
                self._log(f"  Selected: {chosen}", "success")
                artist_name = chosen

            work_items.append((artist_name, ctx, artist_root))

        total = len(work_items)
        if total == 0:
            self._log(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed.", "info")
            self._finish()
            return

        self._log(f"Searching {total} artist(s)...\n", "info")

        # Store session state for pause/resume
        self._session_work_items = list(work_items)
        self._session_search_results = []
        self._session_downloaded = downloaded
        self._session_skipped = skipped
        self._session_failed = failed

        # Phase 1: Search
        self.after(0, self.phase_var.set, "Phase 1/2: Searching...")
        for i, (artist_name, ctx, artist_root) in enumerate(work_items, 1):
            if not self.running:
                self._log("Stopped by user.", "warning")
                break
            if not self._check_pause():
                break
            self.after(0, self.status_var.set, f"[{i}/{total}] Searching: {artist_name}")
            self.after(0, self.progress_var.set, (i / total) * 50)
            self.after(0, self._update_tray_tooltip, f"Searching {i}/{total}")

            safe_name = sanitize_filename(artist_name)
            if self.settings.separate_folder:
                save_dir = Path(self.settings.separate_folder)
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / safe_name
            else:
                base_name = safe_name if self.settings.artist_filename else "artist"
                save_path = artist_root / base_name

            self._log(f"  {artist_name}", "info")
            self._log(f"     Save to: {save_path}.jpg/.png", "info")
            # Check pause before each API call (in case paused while idle)
            if not self._check_pause():
                break
            img_url, error_detail = self._search_artist_image(artist_name, ctx, source)
            if img_url:
                self._log(f"     [ok] URL found", "success")
            else:
                self._log(f"     [X] {error_detail}", "error")
            self._session_search_results.append((artist_name, img_url, save_path, error_detail))

        self._do_download_phase(self._session_search_results,
                                self._session_downloaded,
                                self._session_skipped,
                                self._session_failed)

    def _search_artist_image(self, artist_name: str, ctx, source: str) -> tuple[Optional[str], str]:
        """Search for artist image. Returns (url, error_detail)."""
        import time

        def _fetch_with_retry(fetch_fn, *args, label="", **kwargs):
            """Call fetch_fn with retry on network errors. 3 attempts, 1s delay."""
            for attempt in range(3):
                try:
                    result = fetch_fn(*args, **kwargs)
                    if result:
                        return result
                    return None  # clean miss, no retry
                except (ConnectionError, TimeoutError, OSError) as e:
                    if attempt < 2:
                        self._log(f"     Network error (attempt {attempt+1}/3): {e}", "warning")
                        time.sleep(2.0)
                    else:
                        self._log(f"     Network error after 3 attempts, skipping", "error")
                        return None
            return None

        # Step 0: Check cache
        cached = self.cache.get(artist_name, source)
        if cached:
            self._log(f"     Cached URL -- using cached result", "skip")
            return cached, ""

        tried = []

        # Step 1: Album+year context
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
            img_url = _fetch_with_retry(fetch_artist_image, artist_name, source,
                album_name=album_name, year=year_ctx, genres=ctx.genres)
            if img_url:
                self.cache.put(artist_name, source, img_url)
                return img_url, ""
            tried.append(f"album:{album_name}")
            time.sleep(0.5)

        # Step 2: Track+artist
        tracks_sample = list(ctx.track_names)[:5]
        for track_name in tracks_sample:
            self._log(f"  Trying track: {track_name}...", "info")
            img_url = _fetch_with_retry(fetch_artist_image, artist_name, source,
                genres=ctx.genres, track_name=track_name)
            if img_url:
                self.cache.put(artist_name, source, img_url)
                return img_url, ""
            tried.append(f"track:{track_name}")
            time.sleep(0.5)

        # Step 3: Direct name search
        self._log(f"  Searching by name: {artist_name}...", "info")
        img_url = _fetch_with_retry(fetch_artist_image, artist_name, source,
            album_name="", year="", genres=ctx.genres)
        if img_url:
            self.cache.put(artist_name, source, img_url)
            return img_url, ""
        tried.append("name")
        time.sleep(0.5)

        # Step 3.5: Track-only fallback
        tracks_all = list(ctx.track_names)
        tracks_sample = tracks_all[:5]
        if tracks_all:
            self._log(f"  Track-only fallback ({len(tracks_sample)}/{len(tracks_all)} tracks)...", "info")
            for track_name in tracks_sample:
                self._log(f"    track: {track_name}...", "info")
                img_url = _fetch_with_retry(fetch_artist_image_by_track_only,
                    track_name, artist_name, source, genres=ctx.genres)
                if img_url:
                    self._log(f"  Track-only match via: {track_name}", "success")
                    self.cache.put(artist_name, source, img_url)
                    return img_url, ""
                time.sleep(0.5)
            tried.append("track_only")

        # Step 3.6: Album-only fallback
        albums_all = sorted(
            ctx.album_track_counts.keys(),
            key=lambda a: ctx.album_track_counts[a],
            reverse=True,
        )[:5]
        if albums_all:
            self._log(f"  Album-only fallback ({len(albums_all)} albums)...", "info")
            for album_name in albums_all:
                img_url = _fetch_with_retry(fetch_artist_image_by_album_only,
                    album_name, artist_name, source, genres=ctx.genres)
                if img_url:
                    self._log(f"  Album-only match via: {album_name}", "success")
                    self.cache.put(artist_name, source, img_url)
                    return img_url, ""
                time.sleep(0.5)
            tried.append("album_only")

        # Step 4: Candidate picker — absolute last resort
        candidates = search_artist_candidates(artist_name, source)
        if len(candidates) == 1:
            url = fetch_artist_image_by_id(candidates[0])
            if url:
                self.cache.put(artist_name, source, url)
            return url, "" if url else "no image for candidate"
        elif len(candidates) > 1:
            chosen = self._prompt_artist_choice(artist_name, candidates)
            if chosen:
                for attempt in range(3):
                    url = fetch_artist_image_by_id(chosen)
                    if url:
                        self.cache.put(artist_name, source, url)
                        return url, ""
                    if attempt < 2:
                        time.sleep(1.0)
                return None, "no image for chosen candidate"
            return None, "skipped candidate selection"

        detail = "tried: " + ", ".join(tried) if tried else "no results from any search"
        return None, detail

    # -- Dialog prompts (thread-safe) --------------------------------------

    def _prompt_multi_artist(self, original_name: str, alternatives: list[str]):
        return _prompt_dialog(self, MultiArtistDialog, original_name, alternatives)

    def _prompt_merge_artists(self, groups, artists):
        return _prompt_dialog(self, MergeArtistsDialog, groups, artists)

    def _prompt_artist_choice(self, artist_name, candidates):
        return _prompt_dialog(self, ArtistChoiceDialog, artist_name, candidates)

    def _do_download_phase(self, search_results, downloaded=0, skipped=0, failed=0):
        """Phase 2: download images from search results."""
        import time
        found_count = sum(1 for _, u, _, _ in search_results if u)
        self.after(0, self.phase_var.set, f"Phase 2/2: Downloading {found_count} image(s)...")
        self._log(f"\nDownloading {found_count} image(s)...\n", "info")

        _counters = [downloaded, failed]

        skip = self.skip_var.get()

        _download_delay = 0.0

        def _do_download(item):
            nonlocal _download_delay
            name, url, path, _ = item
            if not url:
                return name, None, _, "search failed"
            # Skip if image already exists on disk
            if skip:
                for ext in (".jpg", ".png", ".jpeg"):
                    if Path(str(path) + ext).exists():
                        return name, Path(str(path) + ext), url, ""
            self._check_pause()
            if not self.running:
                return name, None, _, "stopped"
            # 1-second delay between downloads to avoid rate limiting
            elapsed = time.time() - _download_delay
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            _download_delay = time.time()
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
                self.after(0, self._update_tray_tooltip,
                           f"d{_counters[0]} f{_counters[1]} ({done_count}/{len(search_results)})")
                if result:
                    self.after(0, self._log, f"  [ok] {name} -> {result.name}", "success")
                    self.after(0, self._log, f"     Saved to: {result.parent}", "skip")
                    self.after(0, self._show_preview_in_log, result)
                    _counters[0] += 1
                else:
                    detail = err or "download error"
                    self.after(0, self._log, f"  [X] {name} -- {detail}", "error")
                    self.after(0, self.cache.invalidate, name, self.settings.source)
                    _counters[1] += 1
                    for item in search_results:
                        if item[0] == name:
                            self._failed_items.append(item)
                            break

        downloaded, failed = _counters[0], _counters[1]

        self.after(0, self.phase_var.set, "")
        self._log(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed.", "info")
        self.after(0, self.counter_var.set, f"{downloaded} ok | {skipped} skip | {failed} fail")
        self.after(0, self._update_tray_tooltip, f"Done: {downloaded} ok {skipped} skip {failed} fail")
        if self._failed_items:
            self.after(0, self.retry_btn.configure, {"state": tk.NORMAL})
            self._log("Click 'Retry Failed' to try again.", "info")
            self._auto_export_log()
        self._finish()

    # -- Finish ------------------------------------------------------------

    def _finish(self):
        self._clear_session()
        self._paused = False
        self._pause_event.set()
        run_gen = self._run_counter
        self.after(0, lambda: self._set_finished(run_gen))

    def _set_finished(self, run_gen: int = 0):
        if run_gen != self._run_counter:
            return
        self.running = False
        self._paused = False
        self._pause_event.set()
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.pause_btn.configure(state=tk.DISABLED, text="Pause")
        self.progress_var.set(100)
        self.status_var.set("Finished")
        self.after(0, self.phase_var.set, "")


# ===========================================================================
# Dialogs
# ===========================================================================

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: App, settings: Settings, on_apply):
        super().__init__(parent)
        self.settings = settings
        self.on_apply = on_apply

        t = settings.get_theme()
        self.configure(bg=t["bg"])
        self.title("Settings")
        self.geometry("640x580")
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

        # -- Theme (Combobox) --
        ttk.Label(main, text="Theme", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))
        theme_frame = ttk.Frame(main)
        theme_frame.pack(fill=tk.X, pady=(0, 14))

        self.theme_var = tk.StringVar(value=settings.theme)
        theme_names = list(THEMES.keys())
        theme_display = [name.title() for name in theme_names]

        self.theme_combo = ttk.Combobox(theme_frame, textvariable=self.theme_var,
                                         values=theme_names, state="readonly",
                                         font=("Segoe UI", 10))
        self.theme_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Set display value to match current
        self.theme_combo.set(settings.theme)

        # Color preview swatch
        self.swatch = tk.Canvas(theme_frame, width=24, height=24, bd=0,
                                 highlightthickness=0, bg=t["accent"])
        self.swatch.pack(side=tk.LEFT, padx=(8, 0))
        self.theme_combo.bind("<<ComboboxSelected>>", self._update_swatch)

        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 14))

        # -- Output --
        ttk.Label(main, text="Output", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))

        self.filename_var = tk.BooleanVar(value=settings.artist_filename)
        self.filename_cb = ttk.Checkbutton(main, text='Use artist name as filename (e.g. "Pink Floyd.jpg")',
                                            variable=self.filename_var)
        self.filename_cb.pack(anchor=tk.W)
        if settings.separate_folder:
            self.filename_cb.configure(state=tk.DISABLED)

        # Format + Quality row
        fmt_quality_frame = ttk.Frame(main)
        fmt_quality_frame.pack(fill=tk.X, pady=(4, 8))

        fmt_row = ttk.Frame(fmt_quality_frame)
        fmt_row.pack(fill=tk.X, pady=(0, 4))
        self.format_var = tk.StringVar(value=settings.output_format)
        ttk.Label(fmt_row, text="Format:").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(fmt_row, text="JPEG", variable=self.format_var,
                         value="jpeg", command=self._toggle_quality).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(fmt_row, text="PNG", variable=self.format_var,
                         value="png", command=self._toggle_quality).pack(side=tk.LEFT)

        # Quality: slider + percentage label
        self.quality_frame = ttk.Frame(fmt_quality_frame)
        self.quality_var = tk.IntVar(value=settings.jpeg_quality)

        q_row = ttk.Frame(self.quality_frame)
        q_row.pack(fill=tk.X)
        ttk.Label(q_row, text="Quality:").pack(side=tk.LEFT, padx=(0, 8))
        self.quality_scale = ttk.Scale(
            self.quality_frame, from_=10, to=100, variable=self.quality_var,
            orient=tk.HORIZONTAL, command=self._on_quality_change,
        )
        self.quality_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.quality_label = ttk.Label(q_row, text=f"{settings.jpeg_quality}%", width=4, anchor=tk.CENTER)
        self.quality_label.pack(side=tk.RIGHT)
        ttk.Label(self.quality_frame, text="10 = small file, 100 = best quality",
                   style="Dim.TLabel").pack(anchor=tk.W, pady=(2, 0))

        ttk.Label(main, text="Apple Music: JPEG or PNG (varies by artist). Deezer: always JPEG.",
                   style="Dim.TLabel", wraplength=440).pack(anchor=tk.W, pady=(0, 4))

        # -- Merge behavior --
        self.merge_skip_var = tk.BooleanVar(value=settings.skip_merge_dialog)
        ttk.Checkbutton(main, text="Auto-apply saved artist aliases",
                         variable=self.merge_skip_var).pack(anchor=tk.W, pady=(4, 0))

        # -- Separate folder --
        sep_frame = ttk.Frame(main)
        sep_frame.pack(fill=tk.X, pady=(8, 4))
        self.sep_var = tk.BooleanVar(value=bool(settings.separate_folder))
        ttk.Checkbutton(sep_frame, text="Save to separate folder",
                         variable=self.sep_var,
                         command=self._toggle_sep_folder).pack(anchor=tk.W, side=tk.LEFT)
        self.sep_path_var = tk.StringVar(value=settings.separate_folder)
        self.sep_entry = ttk.Entry(sep_frame, textvariable=self.sep_path_var,
                                    state=tk.NORMAL if settings.separate_folder else tk.DISABLED)
        self.sep_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4))
        self.sep_btn = ttk.Button(sep_frame, text="Browse", style="Small.TButton",
                                   command=self._browse_sep,
                                   state=tk.NORMAL if settings.separate_folder else tk.DISABLED)
        self.sep_btn.pack(side=tk.LEFT)

        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 12))

        # -- Buttons --
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Clear Cache", style="Small.TButton",
                   command=self._clear_cache).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="Reset to Defaults", style="Small.TButton",
                   command=self._reset_defaults).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Apply", style="Accent.TButton",
                   command=self._apply).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="Cancel", style="Small.TButton",
                   command=self.destroy).pack(side=tk.RIGHT)

        self._toggle_quality()

    def _update_swatch(self, event=None):
        theme = self.theme_var.get()
        colors = THEMES.get(theme, THEMES["gruvbox"])
        self.swatch.configure(bg=colors["accent"])

    def _toggle_quality(self):
        if self.format_var.get() == "jpeg":
            self.quality_frame.pack(fill=tk.X, pady=(4, 10))
            self.after_idle(lambda: self.quality_var.set(self.quality_var.get()))
        else:
            self.quality_frame.pack_forget()

    def _on_quality_change(self, _=None):
        val = self.quality_var.get()
        snapped = round(val / 5) * 5
        snapped = max(10, min(100, snapped))
        if snapped != val:
            self.quality_var.set(snapped)
        self.quality_label.configure(text=f"{snapped}%")

    def _toggle_sep_folder(self):
        sep_on = self.sep_var.get()
        state = tk.NORMAL if sep_on else tk.DISABLED
        self.sep_entry.configure(state=state)
        self.sep_btn.configure(state=state)
        self.filename_cb.configure(state=tk.DISABLED if sep_on else tk.NORMAL)

    def _browse_sep(self):
        folder = filedialog.askdirectory(title="Select output folder for artist images")
        if folder:
            self.sep_path_var.set(folder)

    def _clear_cache(self):
        self.master.cache.clear()
        self.master.cache.save()
        messagebox.showinfo("Cache Cleared", "Artist image URL cache has been cleared.")

    def _reset_defaults(self):
        defaults = Settings()
        self.source_var.set(defaults.source)
        self.theme_var.set(defaults.theme)
        self.filename_var.set(defaults.artist_filename)
        self.format_var.set(defaults.output_format)
        self.quality_var.set(defaults.jpeg_quality)
        self.merge_skip_var.set(defaults.skip_merge_dialog)
        self.sep_var.set(False)
        self.sep_path_var.set("")
        self._toggle_quality()
        self._toggle_sep_folder()
        self._update_swatch()

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


class MultiArtistDialog(tk.Toplevel):
    """Dialog to pick one artist from a multi-artist tag."""

    def __init__(self, parent: App, original_name: str, alternatives: list[str]):
        super().__init__(parent)
        t = parent.settings.get_theme()
        self.configure(bg=t["bg"])
        self.title("Multiple artists in tag")
        self.geometry("480x380")
        self.minsize(440, 340)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text=f'The tag contains multiple artists:\n"{original_name}"\n\nSelect which artist to use:',
            style="Warning.TLabel", wraplength=380,
        ).pack(anchor=tk.W, pady=(0, 12))

        # Listbox
        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        self.listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 10), bd=0,
            highlightthickness=0, selectbackground=t["list_select"],
            bg=t["entry_bg"], fg=t["entry_fg"],
        )
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda e: self._ok())

        for a in alternatives:
            self.listbox.insert(tk.END, a)
        self.listbox.selection_set(0)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Skip this artist", style="Small.TButton",
                   command=self._skip).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Use first artist", style="Small.TButton",
                   command=self._use_first).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_frame, text="OK", style="Accent.TButton",
                   command=self._ok).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._skip)
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _ok(self):
        sel = self.listbox.curselection()
        if sel:
            self._dialog_result = self.listbox.get(sel[0])
        self.destroy()

    def _use_first(self):
        self._dialog_result = self.listbox.get(0)
        self.destroy()

    def _skip(self):
        self._dialog_result = None
        self.destroy()


class MergeArtistsDialog(tk.Toplevel):
    """Dialog to review and merge similar artist names."""

    def __init__(self, parent: App, groups: list[list[str]], artists):
        super().__init__(parent)
        self.groups = groups
        self.artists = artists
        self.name_vars: list[tk.StringVar] = []
        self.skip_vars: list[tk.BooleanVar] = []
        self._expanded: dict[int, bool] = {}

        t = parent.settings.get_theme()
        self.configure(bg=t["bg"])
        self.title("Merge Duplicate Artists")
        self.geometry("640x520")
        self.minsize(520, 350)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text=f"Found {len(groups)} group(s) of similar artist names.\n"
            "Select the main name to keep for each group.",
            style="Warning.TLabel", wraplength=580,
        ).pack(anchor=tk.W, pady=(0, 12))

        # Keep all separate checkbox
        self.keep_all_separate = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            main, text="Keep all separate (don't merge any)",
            variable=self.keep_all_separate,
            command=self._toggle_keep_all,
        ).pack(anchor=tk.W, pady=(0, 8))

        # Scrollable area
        canvas_frame = ttk.Frame(main)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        canvas = tk.Canvas(canvas_frame, bg=t["bg"], bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)

        # Build groups
        for idx, group in enumerate(groups):
            self._expanded[idx] = False
            group_frame = ttk.LabelFrame(scrollable, text=f"Group {idx + 1}", padding=8)
            group_frame.pack(fill=tk.X, pady=(0, 6), padx=4)

            name_var = tk.StringVar(value=group[0])
            self.name_vars.append(name_var)

            # Compact view: show names inline
            names_text = " / ".join(group)
            compact_label = ttk.Label(group_frame, text=names_text,
                                       font=("Segoe UI", 9), style="Dim.TLabel")
            compact_label.pack(anchor=tk.W)

            # Expandable details (hidden by default)
            details_frame = ttk.Frame(group_frame)
            for name in group:
                ctx = artists.get(name)
                radio_frame = ttk.Frame(details_frame)
                radio_frame.pack(fill=tk.X, pady=1)

                ttk.Radiobutton(radio_frame, text=name, variable=name_var, value=name).pack(anchor=tk.W, side=tk.LEFT)

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
                        ttk.Label(radio_frame, text=" | ".join(info_parts),
                                   style="Dim.TLabel", wraplength=380).pack(anchor=tk.W, side=tk.LEFT, padx=(16, 0))

            # Expand/collapse toggle
            expand_var = tk.BooleanVar(value=False)
            def make_toggle(idx=idx, ef=details_frame, ev=expand_var, cl=compact_label):
                def toggle():
                    if ev.get():
                        ef.pack(fill=tk.X, pady=(4, 0))
                        cl.pack_forget()
                    else:
                        ef.pack_forget()
                        cl.pack(fill=tk.X)
                return toggle

            expand_cb = ttk.Checkbutton(group_frame, text="Show details",
                                         variable=expand_var, command=make_toggle())
            expand_cb.pack(anchor=tk.W, pady=(2, 0))

            # Skip checkbox
            skip_var = tk.BooleanVar(value=False)
            self.skip_vars.append(skip_var)
            ttk.Checkbutton(group_frame, text="Don't merge this group",
                             variable=skip_var).pack(anchor=tk.W)

        # Save aliases
        self.save_aliases_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="Remember these choices as permanent aliases",
                         variable=self.save_aliases_var).pack(anchor=tk.W, pady=(0, 12))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Skip All", style="Small.TButton", command=self._skip_all).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Cancel", style="Small.TButton", command=self._cancel).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Apply", style="Accent.TButton", command=self._apply).pack(side=tk.RIGHT, padx=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _toggle_keep_all(self):
        val = self.keep_all_separate.get()
        for var in self.skip_vars:
            var.set(val)

    def _skip_all(self):
        self._dialog_result = {}
        self.destroy()

    def _apply(self):
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

        self._dialog_result = merge_map
        self.destroy()

    def _cancel(self):
        self._dialog_result = None
        self.destroy()


class ArtistChoiceDialog(tk.Toplevel):
    """Dialog when multiple API artists have the same name."""

    def __init__(self, parent: App, artist_name: str, candidates):
        super().__init__(parent)
        self.candidates = list(candidates)
        self._preview_request_id = 0

        t = parent.settings.get_theme()
        self.configure(bg=t["bg"])
        self.title(f"Choose artist: {artist_name}")
        self.geometry("660x440")
        self.minsize(580, 360)
        self.transient(parent)
        self.grab_set()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main,
            text=f'Multiple artists found with the name "{artist_name}".\nSelect the correct one:',
            style="Warning.TLabel", wraplength=620,
        ).pack(anchor=tk.W, pady=(0, 12))

        # Content: listbox + preview
        content = ttk.Frame(main)
        content.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        # Listbox with scrollbar
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
        self.listbox.bind("<Double-Button-1>", lambda e: self._apply())

        for i, c in enumerate(self.candidates):
            source_name = "Apple Music" if c.source == "apple_music" else "Deezer"
            genre_text = f" ({c.genre})" if c.genre else ""
            self.listbox.insert(tk.END, f"{c.name}{genre_text}  --  {source_name}")
        self.listbox.selection_set(0)

        def on_select(event):
            sel = self.listbox.curselection()
            if sel:
                self._show_preview(sel[0])

        self.listbox.bind("<<ListboxSelect>>", on_select)
        self.listbox.focus_set()

        # Preview panel
        preview_frame = ttk.Frame(content, width=230)
        preview_frame.pack(side=tk.RIGHT, fill=tk.Y)
        preview_frame.pack_propagate(False)

        self.preview_label = ttk.Label(
            preview_frame, text="\n\n\nPreview\n\n\n",
            style="Dim.TLabel", anchor=tk.CENTER,
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        self.after(100, lambda: self._show_preview(0))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Skip", style="Small.TButton", command=self._skip).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Cancel", style="Small.TButton", command=self._cancel).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="Select", style="Accent.TButton", command=self._apply).pack(side=tk.RIGHT, padx=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _show_preview(self, idx: int):
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
        if request_id != self._preview_request_id:
            return
        if not data:
            self.preview_label.configure(text="\n\nNo preview\navailable\n\n")
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(data))
            img.thumbnail((210, 210))
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
        self._dialog_result = self.candidates[sel[0]]
        self.destroy()

    def _skip(self):
        self._dialog_result = None
        self.destroy()

    def _cancel(self):
        self._dialog_result = None
        self.destroy()
