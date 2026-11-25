"""Cached web source picture browser (John's Background Switcher parity).

The shared web source cache (``<working folder>/web_sources``) accumulates one
file per downloaded image URL. This module lists those pictures newest-first
with the configured source each one belongs to — a direct image URL, an
RSS/Atom feed, or an orphan when its source was removed from the settings.
The browser is read-only: it lists, opens, and reveals cache files; pruning
stays the refresh path's job.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Callable

from .config import load_config
from .desktop import open_desktop_target
from .sources import (
    CachedPicture,
    all_web_source_entries,
    list_cached_pictures,
    web_source_cache_dir,
)
from .working_storage import configured_working_directory

BROWSER_TITLE = "Cached Pictures"
BROWSER_GEOMETRY = "760x360"
BROWSER_MINSIZE = (520, 260)
ROW_SOURCE_LIMIT = 72
ROW_PATH_LIMIT = 90

EMPTY_HINT = (
    "No cached pictures yet. Add web picture sources on the Sources page and "
    "choose Refresh Now to download them into the cache."
)


def _existing_picture_path(path: str | Path) -> Path:
    """Resolve and revalidate one cached picture before launching an opener."""

    picture = Path(path).expanduser().resolve(strict=False)
    if not picture.is_file():
        raise FileNotFoundError(f"Cached picture is missing: {picture}")
    return picture


def _size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MiB"
    if size >= 1024:
        return f"{size / 1024:.0f} KiB"
    return f"{size} B"


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _source_label(picture: CachedPicture) -> str:
    if picture.source_type == "feed" and picture.source_url:
        label = f"[feed] {picture.source_url}"
    elif picture.source_url:
        label = picture.source_url
    else:
        label = "source removed from settings"
    return _shorten(label, ROW_SOURCE_LIMIT)


def _row_label(picture: CachedPicture) -> str:
    cached = datetime.fromtimestamp(picture.mtime).strftime("%Y-%m-%d %H:%M")
    return (
        f"{_shorten(picture.name, ROW_PATH_LIMIT)}  |  {_source_label(picture)}"
        f"  |  {cached}  |  {_size_label(picture.size)}"
    )


class CachedPicturesWindow(tk.Toplevel):
    """Read-only browser over the shared web source cache directory."""

    def __init__(self, parent: tk.Tk, loader: Callable[[], list[CachedPicture]], cache_dir: Path):
        super().__init__(parent)
        self._loader = loader
        self._cache_dir = Path(cache_dir)
        self._pictures: list[CachedPicture] = []
        self._opening = False
        self._first_paint = True
        self.title(BROWSER_TITLE)
        self.transient(parent)
        self.geometry(BROWSER_GEOMETRY)
        self.minsize(*BROWSER_MINSIZE)

        content = ttk.Frame(self, padding=12)
        content.pack(fill=tk.BOTH, expand=True)
        self._header_var = tk.StringVar(value="")
        ttk.Label(content, textvariable=self._header_var, anchor="w", wraplength=700, justify=tk.LEFT).pack(
            anchor="w", pady=(0, 8)
        )

        self._picture_list = tk.Listbox(content, selectmode=tk.BROWSE, exportselection=False, height=10)
        scrollbar = ttk.Scrollbar(content, orient=tk.VERTICAL, command=self._picture_list.yview)
        self._picture_list.configure(yscrollcommand=scrollbar.set)
        self._picture_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._picture_list.bind("<<ListboxSelect>>", lambda _event: self._note_selection())

        self._status_var = tk.StringVar(value="")
        ttk.Label(content, textvariable=self._status_var, anchor="w", wraplength=700, justify=tk.LEFT).pack(
            fill=tk.X, pady=(8, 4)
        )
        buttons = ttk.Frame(content)
        buttons.pack(fill=tk.X)
        self._open_button = ttk.Button(buttons, text="Open Picture", command=lambda: self._open_selected())
        self._open_button.pack(side=tk.LEFT)
        self._open_folder_button = ttk.Button(
            buttons, text="Open Containing Folder", command=lambda: self._open_selected(containing_folder=True)
        )
        self._open_folder_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.RIGHT)

        self.refresh()
        self._first_paint = False

    @property
    def pictures(self) -> list[CachedPicture]:
        return list(self._pictures)

    def _header_text(self) -> str:
        count = len(self._pictures)
        noun = "picture" if count == 1 else "pictures"
        return f"{count} cached web source {noun} in {_shorten(str(self._cache_dir), 120)}"

    def _set_open_controls_enabled(self, enabled: bool) -> None:
        state = ["!disabled"] if enabled else ["disabled"]
        self._open_button.state(state)
        self._open_folder_button.state(state)

    def _repaint(self, pictures: list[CachedPicture], previously_selected: str | None) -> bool:
        """Replace the list content; returns True when the set changed."""

        changed = [picture.name for picture in pictures] != [picture.name for picture in self._pictures]
        self._pictures = list(pictures)
        self._picture_list.delete(0, tk.END)
        for picture in self._pictures:
            self._picture_list.insert(tk.END, _row_label(picture))
        self._header_var.set(self._header_text())
        if self._pictures:
            index = None
            if previously_selected is not None:
                names = [picture.name for picture in self._pictures]
                if previously_selected in names:
                    index = names.index(previously_selected)
            if index is None:
                index = 0
            self._picture_list.selection_clear(0, tk.END)
            self._picture_list.selection_set(index)
            self._picture_list.see(index)
            self._note_selection()
            self._set_open_controls_enabled(not self._opening)
            if changed and not self._first_paint:
                self._status_var.set("The cache list was refreshed. Select a picture to open it.")
        else:
            self._set_open_controls_enabled(False)
            self._status_var.set(EMPTY_HINT)
        return changed

    def refresh(self) -> bool:
        """Re-list the cache directory; keeps the selection when the row survives."""

        try:
            pictures = self._loader()
        except Exception:
            self._status_var.set("The cache could not be listed. Check the working folder setting.")
            return False
        selected = self._picture_list.curselection()
        previously_selected = self._pictures[int(selected[0])].name if selected and self._pictures else None
        return self._repaint(pictures, previously_selected)

    def _note_selection(self) -> None:
        selected = self._picture_list.curselection()
        if not selected or not self._pictures or self._opening:
            return
        picture = self._pictures[int(selected[0])]
        self._status_var.set(
            f"Selected {picture.name} from {_source_label(picture)} — Open Picture launches it in the "
            "default image application."
        )

    def _open_selected(self, *, containing_folder: bool = False) -> None:
        if self._opening:
            return
        selected = self._picture_list.curselection()
        if not selected or not self._pictures:
            self._status_var.set("Select a cached picture to open.")
            return
        picture = self._pictures[int(selected[0])]
        self._opening = True
        self._set_open_controls_enabled(False)
        self._status_var.set(
            "Opening the selected picture's containing folder..." if containing_folder else "Opening the selected picture..."
        )
        result_queue: queue.Queue[tuple[Path | None, Exception | None]] = queue.Queue()

        def launch() -> None:
            try:
                target = _existing_picture_path(picture.path)
                if containing_folder:
                    opened = open_desktop_target(
                        target.parent,
                        failure_subject="the selected picture's containing folder",
                        recovery="Check the desktop file manager.",
                    )
                else:
                    opened = open_desktop_target(
                        target,
                        failure_subject="the selected picture",
                        recovery="Check the default image application.",
                    )
                result_queue.put((opened, None))
            except Exception as exc:
                result_queue.put((None, exc))

        def poll_result() -> None:
            try:
                _opened, error = result_queue.get_nowait()
            except queue.Empty:
                try:
                    self.after(50, poll_result)
                except tk.TclError:
                    return
                return
            self._opening = False
            if self.winfo_exists():
                self._set_open_controls_enabled(True)
            if error is not None:
                subject = "folder" if containing_folder else "picture"
                self._status_var.set(f"The selected {subject} could not be opened: {error}")
            else:
                self._note_selection()

        threading.Thread(target=launch, daemon=True).start()
        self.after(50, poll_result)


def _quit_when_window_gone(root: tk.Tk, window: tk.Misc, *, interval_ms: int = 100) -> None:
    """End the root's mainloop once the browser window is destroyed.

    The standalone browser is a Toplevel over a hidden root, so closing the
    window does not end ``root.mainloop()`` by itself; without this the
    ``cached-pictures`` process (and the tray launch behind it) would live
    forever with no visible window.
    """

    def tick() -> None:
        if not window.winfo_exists():
            root.quit()
            return
        root.after(interval_ms, tick)

    root.after(interval_ms, tick)


def run_cached_pictures_gui(limit: int = 200) -> int:
    """Open the browser as a standalone window (the ``cached-pictures`` command)."""

    config = load_config(create=False)
    cache_dir = web_source_cache_dir(configured_working_directory(config))
    entries = all_web_source_entries(config)

    def loader() -> list[CachedPicture]:
        return list_cached_pictures(cache_dir, entries, limit=limit)

    root = tk.Tk()
    root.withdraw()
    try:
        window = CachedPicturesWindow(root, loader, cache_dir)
        _quit_when_window_gone(root, window)
        root.mainloop()
    except tk.TclError as exc:
        print(f"cached-pictures failed: could not open a display ({exc})", file=sys.stderr)
        return 1
    finally:
        root.destroy()
    return 0
