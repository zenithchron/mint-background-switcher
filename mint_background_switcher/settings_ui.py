"""Simple Tk settings editor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from . import APP_NAME, __version__, config_io, public_collections, updater
from .config import (
    BAR_COLOR_CHOICES,
    DEFAULT_BLACK_HOTKEY,
    DEFAULT_IDLE_SECONDS,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_NEXT_HOTKEY,
    DEFAULT_PAUSE_HOTKEY,
    EFFECT_CHOICES,
    FIT_MODE_CHOICES,
    FIT_MODE_LABELS,
    FIT_MODE_LABEL_TO_VALUE,
    MAX_IGNORE_PATTERN_LENGTH,
    MAX_IGNORE_PATTERNS,
    MAX_IDLE_SECONDS,
    MAX_SUPPRESS_PROCESS_LENGTH,
    POSTCARD_BACKGROUND_CHOICES,
    Config,
    Profile,
    load_config,
    parse_night_time,
    save_config,
)
from .hotkeys import register_all_cinnamon_hotkeys
from .images import SUPPORTED_EXTENSIONS, SUPPORTED_TYPE_NAMES, is_usable_image
from .monitor import Monitor, detect_monitors
from .paths import config_file
from .service import (
    SwitchCancelled,
    black_screen,
    clear_excluded_images,
    current_source_images,
    exclude_current_images,
    excluded_path_set,
    get_excluded_images,
    remove_excluded_images,
    save_current_wallpaper,
    switch_once,
)
from .availability import CollectionUnavailableError
from .working_storage import (
    MARKER_FILENAME,
    WorkingDirectoryMigrationCancelled,
    configured_working_directory,
    create_working_directory,
    migrate_working_directory,
)

__all__ = ["MARKER_FILENAME", "SettingsApp"]


SETTINGS_WINDOW_TARGET_WIDTH = 1120
SETTINGS_WINDOW_TARGET_HEIGHT = 760
SETTINGS_WINDOW_MIN_WIDTH = 980
SETTINGS_WINDOW_MIN_HEIGHT = 680
SETTINGS_WINDOW_SCREEN_MARGIN_X = 80
SETTINGS_WINDOW_SCREEN_MARGIN_Y = 100
PROJECT_URL = "https://github.com/zenithchron/mint-background-switcher"
WORKING_DIRECTORY_STATUS_PATH_LIMIT = 64
LAYOUT_CHOICES = (
    "shared",
    "same",
    "montage",
    "collage",
    "postcard",
    "polaroid",
    "per-monitor",
    "span",
)
LAYOUT_DESCRIPTIONS = {
    "shared": "Show a different image from the shared picture sources on each screen.",
    "same": "Show the same image from the shared picture sources on every screen.",
    "montage": "Arrange four images from the shared picture sources in a grid on each screen.",
    "collage": "Arrange five images from the shared picture sources in an asymmetric collage on each screen.",
    "postcard": "Randomly place bare photos from the shared picture sources without frames or pins.",
    "polaroid": "Randomly place overlapping Polaroid-style prints from the shared picture sources.",
    "per-monitor": "Choose separate picture folders for individual screens.",
    "span": "Span one image from the shared picture sources across the complete virtual desktop.",
}
SUPPORTED_PICTURE_PATTERNS = " ".join(
    pattern
    for extension in SUPPORTED_EXTENSIONS
    for pattern in (f"*{extension}", f"*{extension.upper()}")
)


def _excluded_count_status(count: int, action: str | None = None) -> str:
    """Short user-facing sentence for the never-show-again list and its edits."""
    label = "picture" if count == 1 else "pictures"
    if action == "excluded":
        return f"Excluded {count} {label} from the current wallpaper."
    if action == "removed":
        return f"Removed {count} {label} from the never-show-again list."
    if action == "cleared":
        return f"Cleared {count} {label} from the never-show-again list."
    return f"{count} {label} will never show again for this profile."


def _active_working_directory_status(path: str | Path) -> str:
    """Describe the active folder without allowing a long path to resize Settings."""

    display = str(path)
    if len(display) > WORKING_DIRECTORY_STATUS_PATH_LIMIT:
        left = (WORKING_DIRECTORY_STATUS_PATH_LIMIT - 3) // 2
        right = WORKING_DIRECTORY_STATUS_PATH_LIMIT - left - 3
        display = f"{display[:left]}...{display[-right:]}"
    return f"Active: {display} - source images remain in their original folders."


def _current_picture_path(path: str | Path) -> Path:
    """Resolve and revalidate one source recorded for the current wallpaper."""

    picture = Path(path).expanduser().resolve(strict=False)
    if not picture.is_file():
        raise FileNotFoundError(f"Current source picture is missing: {picture}")
    return picture


def _selected_source_picture(path: str | Path) -> Path:
    """Resolve and validate one picture selected for a shared source pool."""

    try:
        picture = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Could not access the selected picture: {path}") from exc
    if not picture.is_file():
        raise ValueError(f"The selected picture is not a regular file: {picture}")
    if picture.suffix.lower() not in SUPPORTED_EXTENSIONS:
        extensions = ", ".join(SUPPORTED_EXTENSIONS)
        raise ValueError(f"Choose a supported picture file ({extensions}).")
    if "\n" in str(picture) or "\r" in str(picture):
        raise ValueError("Picture paths containing line breaks are not supported.")
    if not is_usable_image(picture):
        raise ValueError("The selected file could not be read as a supported picture.")
    return picture


def _open_desktop_target(target: Path, *, failure_subject: str, recovery: str) -> Path:
    """Launch one validated path through xdg-open without invoking a shell."""

    opener = shutil.which("xdg-open")
    if opener is None:
        raise RuntimeError("xdg-open is unavailable; install xdg-utils to open source pictures or folders")
    process = subprocess.Popen(
        [opener, str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
        shell=False,
    )
    try:
        return_code = process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        # Some desktop openers remain attached to the launched application. Once
        # the validated opener has stayed alive this long, let the detached handoff
        # continue instead of blocking Settings or terminating the application.
        return target
    if return_code != 0:
        raise RuntimeError(
            f"xdg-open could not open {failure_subject} (exit status {return_code}). "
            f"{recovery}"
        )
    return target


def _open_picture(path: str | Path) -> Path:
    """Launch one existing picture through the desktop's default application."""

    picture = _current_picture_path(path)
    return _open_desktop_target(
        picture,
        failure_subject="the selected picture",
        recovery="Check the default image application.",
    )


def _open_containing_folder(path: str | Path) -> Path:
    """Launch the resolved parent folder for one existing current picture."""

    picture = _current_picture_path(path)
    return _open_desktop_target(
        picture.parent,
        failure_subject="the selected picture's containing folder",
        recovery="Check the desktop file manager.",
    )


def _monitor_window_rect(
    screen_width: int,
    screen_height: int,
    monitors: list[Monitor] | None = None,
    pointer_x: int | None = None,
    pointer_y: int | None = None,
) -> tuple[int, int, int, int] | None:
    """Return the monitor rectangle to use for opening the settings window."""

    if not monitors:
        return None

    choices: list[tuple[int, int, int, int, bool]] = []
    for monitor in monitors:
        x, y, width, height = monitor.logical_geometry
        if width > 0 and height > 0:
            choices.append((x, y, width, height, monitor.primary))
    if not choices:
        return None

    if pointer_x is not None and pointer_y is not None:
        for x, y, width, height, _primary in choices:
            if x <= pointer_x < x + width and y <= pointer_y < y + height:
                return (x, y, width, height)

    for x, y, width, height, primary in choices:
        if primary:
            return (x, y, width, height)

    x, y, width, height, _primary = sorted(choices, key=lambda rect: (rect[0], rect[1]))[0]
    return (x, y, width, height)


def _settings_window_geometry(
    screen_width: int,
    screen_height: int,
    requested_width: int = 0,
    requested_height: int = 0,
    monitor_rect: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int, int, int]:
    """Return initial width/height/x/y and safe minimum size for the settings window."""

    origin_x = 0
    origin_y = 0
    area_width = screen_width
    area_height = screen_height
    if monitor_rect is not None:
        origin_x, origin_y, monitor_width, monitor_height = monitor_rect
        if monitor_width > 0 and monitor_height > 0:
            area_width = monitor_width
            area_height = monitor_height

    usable_width = max(320, area_width - min(SETTINGS_WINDOW_SCREEN_MARGIN_X, max(0, area_width - 320)))
    usable_height = max(320, area_height - min(SETTINGS_WINDOW_SCREEN_MARGIN_Y, max(0, area_height - 320)))
    target_width = max(SETTINGS_WINDOW_TARGET_WIDTH, requested_width)
    target_height = max(SETTINGS_WINDOW_TARGET_HEIGHT, requested_height)
    min_width = min(SETTINGS_WINDOW_MIN_WIDTH, usable_width)
    min_height = min(SETTINGS_WINDOW_MIN_HEIGHT, usable_height)
    width = max(min(target_width, usable_width), min_width)
    height = max(min(target_height, usable_height), min_height)
    x = origin_x + max(0, (area_width - width) // 2)
    y = origin_y + max(0, (area_height - height) // 3)
    return width, height, x, y, min_width, min_height


class SettingsApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} Settings — {__version__}")
        self.config_data: Config = load_config()
        self.profile_var = tk.StringVar(value=self.config_data.active_profile)
        self.profile_scope_var = tk.StringVar()
        self.collections_profile_scope_var = tk.StringVar()
        self.interval_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar()
        self.min_image_size_var = tk.StringVar()
        self.ignore_hidden_var = tk.BooleanVar()
        self.ignore_patterns_var = tk.StringVar()
        self.image_types_var = tk.StringVar()
        self.sequential_var = tk.BooleanVar()
        self.match_orientation_var = tk.BooleanVar()
        self.rotate_on_startup_var = tk.BooleanVar(value=True)
        self.night_black_screen_var = tk.BooleanVar(value=False)
        self.night_start_var = tk.StringVar(value=DEFAULT_NIGHT_START)
        self.night_end_var = tk.StringVar(value=DEFAULT_NIGHT_END)
        self.mirror_lockscreen_var = tk.BooleanVar(value=False)
        self.suppress_process_var = tk.BooleanVar(value=False)
        self.suppress_process_name_var = tk.StringVar()
        self.suppress_battery_var = tk.BooleanVar(value=False)
        self.suppress_remote_var = tk.BooleanVar(value=False)
        self.idle_only_var = tk.BooleanVar(value=False)
        self.idle_seconds_var = tk.StringVar(value=str(DEFAULT_IDLE_SECONDS))
        self.suppress_locked_var = tk.BooleanVar(value=False)
        self.hotkey_var = tk.StringVar()
        self.next_hotkey_var = tk.StringVar()
        self.pause_hotkey_var = tk.StringVar()
        self.desktop_var = tk.StringVar()
        self.effect_var = tk.StringVar()
        self.bar_color_var = tk.StringVar()
        self.fit_mode_var = tk.StringVar(value=FIT_MODE_LABELS[FIT_MODE_CHOICES[0]])
        self.postcard_background_var = tk.StringVar(value=POSTCARD_BACKGROUND_CHOICES[0])
        self.postcard_count_var = tk.IntVar(value=4)
        self.postcard_size_var = tk.DoubleVar(value=0.5)
        self.postcard_span_var = tk.BooleanVar(value=False)
        self.postcard_tilt_var = tk.BooleanVar(value=True)
        self.postcard_captions_var = tk.BooleanVar(value=False)
        self.polaroid_count_var = tk.IntVar(value=4)
        self.polaroid_size_var = tk.DoubleVar(value=0.5)
        self.polaroid_span_var = tk.BooleanVar(value=False)
        self.polaroid_tilt_var = tk.BooleanVar(value=True)
        self.polaroid_captions_var = tk.BooleanVar(value=False)
        self.monitor_folder_var = tk.StringVar()
        self.update_status_var = tk.StringVar()
        first_collection = public_collections.PUBLIC_COLLECTIONS[0]
        self.collections_name_var = tk.StringVar(value=first_collection.name)
        self.collections_count_var = tk.IntVar(value=25)
        self.collections_root_var = tk.StringVar(
            value=str(Path.home() / "Pictures" / "Mint Background Switcher Collections")
        )
        self.collections_add_source_var = tk.BooleanVar(value=True)
        self.collections_description_var = tk.StringVar(value=first_collection.description)
        self.collections_status_var = tk.StringVar(value="Choose a collection and download folder.")
        working_directory = configured_working_directory(self.config_data)
        self.working_directory_var = tk.StringVar(value=str(working_directory))
        self.working_status_var = tk.StringVar(value=_active_working_directory_status(working_directory))
        self.backup_status_var = tk.StringVar(value="No export or import done yet in this session.")
        self.monitor_folders_data: dict[str, list[str]] = {}
        self._update_busy = False
        self._update_worker: threading.Thread | None = None
        self._update_results: queue.Queue[
            tuple[Callable[[Any], None] | None, Any, str, Exception | None]
        ] = queue.Queue()
        self._apply_busy = False
        self._apply_worker: threading.Thread | None = None
        self._apply_cancel = threading.Event()
        self._migration_busy = False
        self._migration_worker: threading.Thread | None = None
        self._migration_cancel = threading.Event()
        self._collection_busy = False
        self._collection_worker: threading.Thread | None = None
        self._collection_cancel = threading.Event()
        self._current_pictures_window: tk.Toplevel | None = None
        self._refresh_current_pictures: Callable[[], bool] | None = None
        self._excluded_display: list[str] = []
        self._operation_results: queue.Queue[tuple[str, Any, Exception | None]] = queue.Queue()
        self.detected_monitors = detect_monitors()
        self._build()
        self.profile_var.trace_add("write", self._refresh_profile_scope_labels)
        self.mode_var.trace_add("write", self._refresh_layout_workspace)
        self.postcard_span_var.trace_add("write", self._refresh_postcard_count_label)
        self.polaroid_span_var.trace_add("write", self._refresh_polaroid_count_label)
        self._refresh_profile_scope_labels()
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self._load_profile(self.profile_var.get())
        self._set_initial_window_geometry()
        self.after(100, self._poll_update_results)
        self.after(100, self._poll_operation_results)

    def _set_initial_window_geometry(self) -> None:
        self.update_idletasks()
        monitor_rect = _monitor_window_rect(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            self._optional_attr("detected_monitors", []),
            self.winfo_pointerx(),
            self.winfo_pointery(),
        )
        width, height, x, y, min_width, min_height = _settings_window_geometry(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            self.winfo_reqwidth(),
            self.winfo_reqheight(),
            monitor_rect,
        )
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min_width, min_height)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        self.profile_context_frame = ttk.LabelFrame(
            root,
            text="Profile and layout",
            padding=(6, 6),
        )
        self.profile_context_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(self.profile_context_frame, text="Profile:").grid(row=0, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(
            self.profile_context_frame,
            textvariable=self.profile_var,
            values=sorted(self.config_data.profiles),
            state="readonly",
            width=14,
        )
        self.profile_combo.grid(row=0, column=1, sticky="w", padx=(4, 6))
        self.profile_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._load_profile(self.profile_var.get()),
        )
        self.profile_new_button = ttk.Button(
            self.profile_context_frame,
            text="New",
            command=self._new_profile,
        )
        self.profile_new_button.grid(row=0, column=2, padx=2)
        self.profile_rename_button = ttk.Button(
            self.profile_context_frame,
            text="Edit",
            command=self._rename_profile,
        )
        self.profile_rename_button.grid(row=0, column=3, padx=2)
        self.profile_delete_button = ttk.Button(
            self.profile_context_frame,
            text="Delete",
            command=self._delete_profile,
        )
        self.profile_delete_button.grid(row=0, column=4, padx=2)
        ttk.Label(self.profile_context_frame, text="Layout:").grid(
            row=0,
            column=6,
            sticky="e",
            padx=(8, 0),
        )
        self.mode_menu = ttk.OptionMenu(
            self.profile_context_frame,
            self.mode_var,
            LAYOUT_CHOICES[0],
            *LAYOUT_CHOICES,
            command=lambda selected: self._select_layout(str(selected)),
        )
        self.mode_menu.grid(row=0, column=7, sticky="w", padx=5)
        self.profile_save_button = ttk.Button(
            self.profile_context_frame,
            text="Save Profile",
            command=self._save_current,
        )
        self.profile_save_button.grid(row=0, column=8, sticky="e", padx=(8, 0))
        self.profile_context_frame.columnconfigure(5, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.sources_tab = ttk.Frame(self.notebook, padding=10)
        self.layout_tab = ttk.Frame(self.notebook, padding=12)
        self.rotation_tab = ttk.Frame(self.notebook, padding=12)
        self.conditions_tab = ttk.Frame(self.notebook, padding=12)
        self.excluded_tab = ttk.Frame(self.notebook, padding=12)
        self.collections_tab = ttk.Frame(self.notebook, padding=12)
        self.storage_tab = ttk.Frame(self.notebook, padding=12)
        self.about_tab = ttk.Frame(self.notebook, padding=12)
        # Retain the old attribute for third-party automation while the visible page is task-named.
        self.general_tab = self.sources_tab
        self.notebook.add(self.sources_tab, text="Sources", underline=0)
        self.notebook.add(self.layout_tab, text="Layout & Appearance", underline=0)
        self.notebook.add(self.rotation_tab, text="Rotation & Shortcuts", underline=0)
        self.notebook.add(self.conditions_tab, text="Conditions", underline=0)
        self.notebook.add(self.excluded_tab, text="Never Show Again", underline=0)
        self.notebook.add(self.collections_tab, text="Public Collections", underline=0)
        self.notebook.add(self.storage_tab, text="Storage", underline=1)
        self.notebook.add(self.about_tab, text="Updates & About", underline=0)
        self.notebook.enable_traversal()

        self.sources_scope_label = ttk.Label(
            self.sources_tab,
            textvariable=self.profile_scope_var,
            style="Heading.TLabel",
        )
        self.sources_scope_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.sources_tab,
            text="Choose local folders and pictures for this profile. Source files remain read-only.",
            justify=tk.LEFT,
            wraplength=840,
        ).pack(anchor="w", pady=(0, 8))

        source_options = ttk.LabelFrame(self.sources_tab, text="Folder scanning", padding=(8, 5))
        source_options.pack(fill=tk.X, pady=(0, 4))
        self.recursive_checkbutton = ttk.Checkbutton(
            source_options,
            text="Scan folders recursively",
            variable=self.recursive_var,
        )
        self.recursive_checkbutton.grid(row=0, column=0, sticky="w")
        self.ignore_hidden_checkbutton = ttk.Checkbutton(
            source_options,
            text="Ignore hidden files and folders",
            variable=self.ignore_hidden_var,
        )
        self.ignore_hidden_checkbutton.grid(row=0, column=2, sticky="w")
        ttk.Label(source_options, text="Minimum image size:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.min_image_size_entry = ttk.Entry(source_options, textvariable=self.min_image_size_var, width=6)
        self.min_image_size_entry.grid(row=1, column=1, sticky="w", padx=5, pady=(5, 0))
        ttk.Label(
            source_options,
            text="px on the smallest side; 0 means no limit. Smaller pictures are skipped when the library is scanned.",
        ).grid(row=1, column=2, sticky="w", pady=(5, 0))
        ttk.Label(source_options, text="Ignore name patterns:").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.ignore_patterns_entry = ttk.Entry(
            source_options,
            textvariable=self.ignore_patterns_var,
            width=11,
        )
        self.ignore_patterns_entry.grid(row=2, column=1, sticky="w", padx=5, pady=(5, 0))
        ttk.Label(
            source_options,
            text="wildcards, comma-separated; for example thumb*.jpg",
        ).grid(row=2, column=2, sticky="w", pady=(5, 0))
        self.match_orientation_checkbutton = ttk.Checkbutton(
            source_options,
            text="Match monitor orientation",
            variable=self.match_orientation_var,
        )
        self.match_orientation_checkbutton.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Label(
            source_options,
            text="prefer landscape pictures on landscape monitors and portrait pictures on portrait monitors",
        ).grid(row=3, column=2, sticky="w", pady=(5, 0))
        ttk.Label(source_options, text="Image types:").grid(row=4, column=0, sticky="w", pady=(5, 0))
        self.image_types_entry = ttk.Entry(
            source_options,
            textvariable=self.image_types_var,
            width=12,
        )
        self.image_types_entry.grid(row=4, column=1, sticky="w", padx=5, pady=(5, 0))
        ttk.Label(
            source_options,
            text="comma-separated; for example jpg, png; empty means all supported types",
        ).grid(row=4, column=2, sticky="w", pady=(5, 0))
        source_options.columnconfigure(2, weight=1)

        shared_frame = ttk.LabelFrame(self.sources_tab, text="Shared picture sources", padding=8)
        shared_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        ttk.Label(
            shared_frame,
            text=(
                "Folders and individual pictures used by Shared, Same, Montage, Collage, "
                "Postcard, Polaroid, and Span modes."
            ),
        ).pack(anchor="w", pady=(0, 4))
        self.shared_text = tk.Text(shared_frame, height=5, width=40)
        self.shared_text.pack(fill=tk.BOTH, expand=True)
        shared_buttons = ttk.Frame(shared_frame)
        shared_buttons.pack(fill=tk.X, pady=4)
        self.shared_add_folder_button = ttk.Button(
            shared_buttons,
            text="Add folder...",
            command=self._add_shared_folder,
        )
        self.shared_add_folder_button.pack(side=tk.LEFT)
        self.shared_add_picture_button = ttk.Button(
            shared_buttons,
            text="Add picture...",
            command=self._add_shared_picture,
        )
        self.shared_add_picture_button.pack(side=tk.LEFT, padx=4)
        self.shared_browse_drives_button = ttk.Button(
            shared_buttons,
            text="Browse hard drives...",
            command=self._add_shared_folder_from_root,
        )
        self.shared_browse_drives_button.pack(side=tk.LEFT)

        self.layout_scope_label = ttk.Label(
            self.layout_tab,
            textvariable=self.profile_scope_var,
            style="Heading.TLabel",
        )
        self.layout_scope_label.pack(anchor="w", pady=(0, 4))
        appearance = ttk.LabelFrame(self.layout_tab, text="Appearance", padding=(8, 4))
        appearance.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(appearance, text="Effect:").grid(row=0, column=0, sticky="w")
        self.effect_menu = ttk.OptionMenu(
            appearance,
            self.effect_var,
            EFFECT_CHOICES[0],
            *EFFECT_CHOICES,
        )
        self.effect_menu.grid(row=0, column=1, sticky="w", padx=(5, 20))
        ttk.Label(appearance, text="Letterbox bars:").grid(row=0, column=2, sticky="w")
        self.bar_color_menu = ttk.OptionMenu(
            appearance,
            self.bar_color_var,
            BAR_COLOR_CHOICES[0],
            *BAR_COLOR_CHOICES,
        )
        self.bar_color_menu.grid(row=0, column=3, sticky="w", padx=5)
        self.bar_color_help = ttk.Label(
            appearance,
            text="Blurred fills unused space with a softened copy while keeping the whole picture visible.",
            wraplength=500,
            justify=tk.LEFT,
        )
        self.bar_color_help.grid(row=1, column=2, columnspan=2, sticky="w", pady=(3, 0))
        ttk.Label(appearance, text="Display fit mode:").grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.fit_mode_menu = ttk.OptionMenu(
            appearance,
            self.fit_mode_var,
            FIT_MODE_LABELS[FIT_MODE_CHOICES[0]],
            *(FIT_MODE_LABELS[value] for value in FIT_MODE_CHOICES),
        )
        self.fit_mode_menu.grid(row=1, column=1, sticky="w", padx=(5, 20), pady=(3, 0))
        appearance.columnconfigure(3, weight=1)

        self.layout_description_var = tk.StringVar(value=LAYOUT_DESCRIPTIONS[LAYOUT_CHOICES[0]])
        ttk.Label(
            self.layout_tab,
            text="Choose a layout above. This page always shows the options for the pending layout.",
            justify=tk.LEFT,
            wraplength=820,
        ).pack(anchor="w")
        self.layout_description_label = ttk.Label(
            self.layout_tab,
            textvariable=self.layout_description_var,
            justify=tk.LEFT,
            wraplength=820,
        )
        self.layout_description_label.pack(anchor="w", pady=(4, 6))
        self.layout_options_container = ttk.Frame(self.layout_tab)
        self.layout_options_container.pack(fill=tk.BOTH, expand=True)
        self.layout_panels: dict[str, ttk.Frame] = {
            mode: ttk.Frame(self.layout_options_container) for mode in LAYOUT_CHOICES
        }
        for mode in LAYOUT_CHOICES:
            if mode not in {"postcard", "polaroid", "per-monitor"}:
                ttk.Label(
                    self.layout_panels[mode],
                    text="This layout has no additional layout-specific options.",
                    justify=tk.LEFT,
                ).pack(anchor="w")

        photo_scale_style = ttk.Style(self)
        photo_scale_style.configure("ScatteredPhoto.Horizontal.TScale", sliderlength=36)

        postcard_panel = self.layout_panels["postcard"]
        self.postcard_options = ttk.LabelFrame(postcard_panel, text="Postcard options", padding=10)
        self.postcard_options.pack(fill=tk.X)
        postcard_layout_options = ttk.Frame(self.postcard_options)
        postcard_layout_options.pack(fill=tk.X)
        self.postcard_count_label = ttk.Label(postcard_layout_options, text="Postcard photos per screen:")
        self.postcard_count_label.pack(side=tk.LEFT)
        self.postcard_count_spinbox = ttk.Spinbox(
            postcard_layout_options,
            from_=1,
            to=100,
            textvariable=self.postcard_count_var,
            width=4,
        )
        self.postcard_count_spinbox.pack(side=tk.LEFT, padx=(5, 18))
        ttk.Label(postcard_layout_options, text="Photo size:").pack(side=tk.LEFT)
        ttk.Label(postcard_layout_options, text="Small").pack(side=tk.LEFT, padx=(5, 2))
        self.postcard_size_scale = ttk.Scale(
            postcard_layout_options,
            from_=0.0,
            to=1.0,
            variable=self.postcard_size_var,
            orient=tk.HORIZONTAL,
            length=180,
            style="ScatteredPhoto.Horizontal.TScale",
        )
        self.postcard_size_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(postcard_layout_options, text="Large").pack(side=tk.LEFT, padx=(2, 0))
        self.postcard_span_checkbutton = ttk.Checkbutton(
            postcard_layout_options,
            text="Span across all screens",
            variable=self.postcard_span_var,
        )
        self.postcard_span_checkbutton.pack(side=tk.LEFT, padx=(18, 0))
        postcard_style_options = ttk.Frame(self.postcard_options)
        postcard_style_options.pack(fill=tk.X, pady=(8, 0))
        self.postcard_tilt_checkbutton = ttk.Checkbutton(
            postcard_style_options,
            text="Randomly tilt photos",
            variable=self.postcard_tilt_var,
        )
        self.postcard_tilt_checkbutton.pack(side=tk.LEFT)
        self.postcard_captions_checkbutton = ttk.Checkbutton(
            postcard_style_options,
            text="Show photo captions",
            variable=self.postcard_captions_var,
        )
        self.postcard_captions_checkbutton.pack(side=tk.LEFT, padx=(24, 0))
        ttk.Label(postcard_style_options, text="Background:").pack(side=tk.LEFT, padx=(24, 5))
        self.postcard_background_menu = ttk.OptionMenu(
            postcard_style_options,
            self.postcard_background_var,
            POSTCARD_BACKGROUND_CHOICES[0],
            *POSTCARD_BACKGROUND_CHOICES,
        )
        self.postcard_background_menu.pack(side=tk.LEFT)
        self.postcard_background_help = ttk.Label(
            self.postcard_options,
            text="Textured backgrounds are generated locally—no photographic texture or download.",
            justify=tk.LEFT,
            wraplength=820,
        )
        self.postcard_background_help.pack(anchor="w", pady=(6, 0))

        polaroid_panel = self.layout_panels["polaroid"]
        self.polaroid_options = ttk.LabelFrame(polaroid_panel, text="Polaroid options", padding=10)
        self.polaroid_options.pack(fill=tk.X)
        polaroid_layout_options = ttk.Frame(self.polaroid_options)
        polaroid_layout_options.pack(fill=tk.X)
        self.polaroid_count_label = ttk.Label(polaroid_layout_options, text="Polaroid photos per screen:")
        self.polaroid_count_label.pack(side=tk.LEFT)
        self.polaroid_count_spinbox = ttk.Spinbox(
            polaroid_layout_options,
            from_=1,
            to=100,
            textvariable=self.polaroid_count_var,
            width=4,
        )
        self.polaroid_count_spinbox.pack(side=tk.LEFT, padx=(5, 18))
        ttk.Label(polaroid_layout_options, text="Photo size:").pack(side=tk.LEFT)
        ttk.Label(polaroid_layout_options, text="Small").pack(side=tk.LEFT, padx=(5, 2))
        self.polaroid_size_scale = ttk.Scale(
            polaroid_layout_options,
            from_=0.0,
            to=1.0,
            variable=self.polaroid_size_var,
            orient=tk.HORIZONTAL,
            length=180,
            style="ScatteredPhoto.Horizontal.TScale",
        )
        self.polaroid_size_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(polaroid_layout_options, text="Large").pack(side=tk.LEFT, padx=(2, 0))
        self.polaroid_span_checkbutton = ttk.Checkbutton(
            polaroid_layout_options,
            text="Span across all screens",
            variable=self.polaroid_span_var,
        )
        self.polaroid_span_checkbutton.pack(side=tk.LEFT, padx=(18, 0))
        polaroid_style_options = ttk.Frame(self.polaroid_options)
        polaroid_style_options.pack(fill=tk.X, pady=(8, 0))
        self.polaroid_tilt_checkbutton = ttk.Checkbutton(
            polaroid_style_options,
            text="Randomly tilt prints",
            variable=self.polaroid_tilt_var,
        )
        self.polaroid_tilt_checkbutton.pack(side=tk.LEFT)
        self.polaroid_captions_checkbutton = ttk.Checkbutton(
            polaroid_style_options,
            text="Show photo captions",
            variable=self.polaroid_captions_var,
        )
        self.polaroid_captions_checkbutton.pack(side=tk.LEFT, padx=(24, 0))

        monitor_frame = ttk.LabelFrame(self.layout_panels["per-monitor"], text="Per-monitor folders", padding=8)
        monitor_frame.pack(fill=tk.BOTH, expand=True)
        monitors = self.detected_monitors
        self.monitor_names = [m.name for m in monitors]
        if self.monitor_names:
            self.monitor_folder_var.set(self.monitor_names[0])
        current_monitors = ", ".join(
            f"{m.name} ({m.width}×{m.height}, {int(m.scale * 100)}% scale)" for m in monitors
        )
        ttk.Label(
            monitor_frame,
            text=(
                "Add a per-monitor folder, then choose the screen it should use.\n"
                "Current screens: " + (current_monitors or "none detected")
            ),
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor="w")
        ttk.Button(monitor_frame, text="Add per-monitor folder...", command=self._add_monitor_folder_from_root).pack(
            anchor="w", pady=(4, 2)
        )
        ttk.Button(monitor_frame, text="Remove per-monitor folder...", command=self._remove_monitor_folder_from_dialog).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(monitor_frame, text="Current assignments:").pack(anchor="w", pady=(6, 0))
        self.monitor_text = tk.Text(monitor_frame, height=6, width=48)
        self.monitor_text.pack(fill=tk.BOTH, expand=True)
        self._refresh_layout_workspace()

        self.rotation_scope_label = ttk.Label(
            self.rotation_tab,
            textvariable=self.profile_scope_var,
            style="Heading.TLabel",
        )
        self.rotation_scope_label.pack(anchor="w", pady=(0, 6))
        rotation_schedule = ttk.LabelFrame(self.rotation_tab, text="Rotation", padding=6)
        rotation_schedule.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(rotation_schedule, text="Interval minutes:").grid(row=0, column=0, sticky="w")
        self.interval_entry = ttk.Entry(rotation_schedule, textvariable=self.interval_var, width=10)
        self.interval_entry.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(
            rotation_schedule,
            text="The background loop reloads this saved value before each rotation.",
            justify=tk.LEFT,
            wraplength=570,
        ).grid(row=0, column=2, sticky="w", padx=(16, 0))
        rotation_schedule.columnconfigure(2, weight=1)
        self.sequential_checkbutton = ttk.Checkbutton(
            rotation_schedule,
            text="Rotate pictures in folder order instead of random",
            variable=self.sequential_var,
        )
        self.sequential_checkbutton.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.rotate_on_startup_checkbutton = ttk.Checkbutton(
            rotation_schedule,
            text="Rotate at startup (off keeps the current background after login)",
            variable=self.rotate_on_startup_var,
        )
        self.rotate_on_startup_checkbutton.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.night_black_screen_checkbutton = ttk.Checkbutton(
            rotation_schedule,
            text="Keep the desktop black during a nightly window",
            variable=self.night_black_screen_var,
        )
        self.night_black_screen_checkbutton.grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(rotation_schedule, text="Night window:").grid(row=4, column=0, sticky="w", padx=(20, 0))
        night_window_frame = ttk.Frame(rotation_schedule)
        night_window_frame.grid(row=4, column=1, sticky="w", padx=5)
        self.night_start_entry = ttk.Entry(night_window_frame, textvariable=self.night_start_var, width=6)
        self.night_start_entry.pack(side=tk.LEFT)
        ttk.Label(night_window_frame, text="to").pack(side=tk.LEFT, padx=(6, 6))
        self.night_end_entry = ttk.Entry(night_window_frame, textvariable=self.night_end_var, width=6)
        self.night_end_entry.pack(side=tk.LEFT)
        ttk.Label(
            rotation_schedule,
            text="Local HH:MM; may cross midnight; auto-resumes.",
            justify=tk.LEFT,
            wraplength=430,
        ).grid(row=4, column=2, sticky="w", padx=(16, 0))
        self.night_black_screen_var.trace_add("write", self._refresh_night_time_state)
        self._refresh_night_time_state()

        shortcuts = ttk.LabelFrame(self.rotation_tab, text="Shortcuts", padding=6)
        shortcuts.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(shortcuts, text="Next hotkey:").grid(row=0, column=0, sticky="w")
        self.next_hotkey_entry = ttk.Entry(shortcuts, textvariable=self.next_hotkey_var, width=22)
        self.next_hotkey_entry.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(
            shortcuts,
            text="Cinnamon keybindings, e.g. <Primary><Alt>n.",
            justify=tk.LEFT,
            wraplength=430,
        ).grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Label(shortcuts, text="Pause/Resume hotkey:").grid(row=1, column=0, sticky="w")
        self.pause_hotkey_entry = ttk.Entry(shortcuts, textvariable=self.pause_hotkey_var, width=22)
        self.pause_hotkey_entry.grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(shortcuts, text="Black screen hotkey:").grid(row=2, column=0, sticky="w")
        self.hotkey_entry = ttk.Entry(shortcuts, textvariable=self.hotkey_var, width=22)
        self.hotkey_entry.grid(row=2, column=1, sticky="w", padx=5)
        self.register_hotkeys_button = ttk.Button(shortcuts, text="Register hotkeys", command=self._register_hotkeys)
        self.register_hotkeys_button.grid(row=2, column=2, sticky="w", padx=(16, 0))
        shortcuts.columnconfigure(2, weight=1)

        desktop_integration = ttk.LabelFrame(self.rotation_tab, text="Desktop integration", padding=10)
        desktop_integration.pack(fill=tk.X)
        ttk.Label(desktop_integration, text="Desktop:").grid(row=0, column=0, sticky="w")
        self.desktop_menu = ttk.OptionMenu(
            desktop_integration,
            self.desktop_var,
            "auto",
            "auto",
            "cinnamon",
            "gnome",
            "mate",
            "xfce",
        )
        self.desktop_menu.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(
            desktop_integration,
            text="Auto is recommended for Linux Mint and detects the active desktop at apply time.",
            justify=tk.LEFT,
            wraplength=570,
        ).grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.mirror_lockscreen_checkbutton = ttk.Checkbutton(
            desktop_integration,
            text="Mirror wallpaper to the lock screen",
            variable=self.mirror_lockscreen_var,
        )
        self.mirror_lockscreen_checkbutton.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(
            desktop_integration,
            text="GNOME writes the lock-screen image on each rotation; Cinnamon already mirrors it.",
            justify=tk.LEFT,
            wraplength=800,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=(20, 0))
        desktop_integration.columnconfigure(2, weight=1)

        self.conditions_scope_label = ttk.Label(
            self.conditions_tab,
            textvariable=self.profile_scope_var,
            style="Heading.TLabel",
        )
        self.conditions_scope_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.conditions_tab,
            text=(
                "Choose the local conditions that pause scheduled switching for this profile. "
                "Manual switches and Save & Apply Now always apply."
            ),
            justify=tk.LEFT,
            wraplength=860,
        ).pack(anchor="w", pady=(0, 8))
        run_conditions = ttk.LabelFrame(self.conditions_tab, text="Run conditions", padding=(10, 6))
        run_conditions.pack(fill=tk.X, pady=(0, 8))
        self.suppress_process_checkbutton = ttk.Checkbutton(
            run_conditions,
            text="Pause scheduled switching while a named process is running:",
            variable=self.suppress_process_var,
        )
        self.suppress_process_checkbutton.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.suppress_process_name_entry = ttk.Entry(
            run_conditions, textvariable=self.suppress_process_name_var, width=18
        )
        self.suppress_process_name_entry.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 4))
        self.suppress_battery_checkbutton = ttk.Checkbutton(
            run_conditions,
            text="Pause scheduled switching while running on battery (laptops)",
            variable=self.suppress_battery_var,
        )
        self.suppress_battery_checkbutton.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.suppress_remote_checkbutton = ttk.Checkbutton(
            run_conditions,
            text="Pause scheduled switching while a remote (VNC) session is active",
            variable=self.suppress_remote_var,
        )
        self.suppress_remote_checkbutton.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.idle_only_checkbutton = ttk.Checkbutton(
            run_conditions,
            text="Only switch when the session has been idle (seconds):",
            variable=self.idle_only_var,
        )
        self.idle_only_checkbutton.grid(row=3, column=0, sticky="w", pady=(0, 4))
        self.idle_seconds_entry = ttk.Entry(run_conditions, textvariable=self.idle_seconds_var, width=6)
        self.idle_seconds_entry.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(0, 4))
        self.suppress_locked_checkbutton = ttk.Checkbutton(
            run_conditions,
            text="Pause scheduled switching while the session is locked or the screensaver is active",
            variable=self.suppress_locked_var,
        )
        self.suppress_locked_checkbutton.grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 2))
        ttk.Label(
            run_conditions,
            text=(
                "Conditions pause the background loop only — Save & Apply Now and manual next switches always apply. "
                "Battery, idle time (xprintidle), and lock state are probed locally; a condition that cannot be "
                "detected never blocks."
            ),
            justify=tk.LEFT,
            wraplength=860,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.suppress_process_var.trace_add("write", self._refresh_run_condition_states)
        self.idle_only_var.trace_add("write", self._refresh_run_condition_states)
        self._refresh_run_condition_states()

        self.excluded_scope_label = ttk.Label(
            self.excluded_tab,
            textvariable=self.profile_scope_var,
            style="Heading.TLabel",
        )
        self.excluded_scope_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.excluded_tab,
            text=(
                "Pictures on this list are never chosen for this profile. "
                "Excluding the current wallpaper removes every picture it is using from future rotation."
            ),
            justify=tk.LEFT,
            wraplength=860,
        ).pack(anchor="w", pady=(0, 8))
        excluded_current_frame = ttk.LabelFrame(self.excluded_tab, text="Current wallpaper", padding=(10, 6))
        excluded_current_frame.pack(fill=tk.X, pady=(0, 8))
        self.excluded_current_text = tk.Text(
            excluded_current_frame,
            height=3,
            width=80,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.excluded_current_text.pack(fill=tk.X)
        self.excluded_current_button = ttk.Button(
            excluded_current_frame,
            text="Never Show Again (current wallpaper)",
            command=self._exclude_current_wallpaper,
        )
        self.excluded_current_button.pack(anchor="w", pady=(6, 0))
        excluded_frame = ttk.LabelFrame(self.excluded_tab, text="Excluded pictures", padding=(10, 6))
        excluded_frame.pack(fill=tk.BOTH, expand=True)
        self.excluded_status_var = tk.StringVar()
        ttk.Label(excluded_frame, textvariable=self.excluded_status_var).pack(anchor="w")
        excluded_list_row = ttk.Frame(excluded_frame)
        excluded_list_row.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self.excluded_list = tk.Listbox(excluded_list_row, height=5, selectmode=tk.EXTENDED, exportselection=False)
        excluded_scrollbar = ttk.Scrollbar(excluded_list_row, orient=tk.VERTICAL, command=self.excluded_list.yview)
        self.excluded_list.configure(yscrollcommand=excluded_scrollbar.set)
        self.excluded_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        excluded_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.excluded_remove_button = ttk.Button(
            excluded_frame,
            text="Remove Selected",
            command=self._remove_selected_excluded,
        )
        self.excluded_remove_button.pack(anchor="w", pady=(0, 4))
        self.excluded_clear_button = ttk.Button(
            excluded_frame,
            text="Clear All...",
            command=self._clear_excluded_confirmed,
        )
        self.excluded_clear_button.pack(anchor="w")

        self.storage_scope_label = ttk.Label(
            self.storage_tab,
            text="Application setting — shared by every profile",
            style="Heading.TLabel",
        )
        self.storage_scope_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.storage_tab,
            text=(
                "Choose where generated wallpapers and the image-library index live. "
                "Changing this does not move or modify source pictures."
            ),
            justify=tk.LEFT,
            wraplength=840,
        ).pack(anchor="w", pady=(0, 8))
        self.working_frame = ttk.LabelFrame(self.storage_tab, text="Working files", padding=(8, 8))
        self.working_frame.pack(fill=tk.X)
        ttk.Label(self.working_frame, text="Working directory:").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.working_directory_entry = ttk.Entry(
            self.working_frame,
            textvariable=self.working_directory_var,
            width=16,
        )
        self.working_directory_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.working_browse_button = ttk.Button(
            self.working_frame,
            text="Browse...",
            command=self._browse_working_directory,
        )
        self.working_browse_button.grid(row=0, column=2, padx=2)
        self.working_create_button = ttk.Button(
            self.working_frame,
            text="Create Folder...",
            command=self._create_working_directory,
        )
        self.working_create_button.grid(row=0, column=3, padx=2)
        self.working_use_button = ttk.Button(
            self.working_frame,
            text="Use Folder...",
            command=self._use_working_directory,
        )
        self.working_use_button.grid(row=0, column=4, padx=2)
        self.working_cancel_button = ttk.Button(
            self.working_frame,
            text="Cancel Move",
            command=self._cancel_working_migration,
        )
        self.working_cancel_button.grid(row=0, column=5, padx=(2, 0))
        self.working_cancel_button.state(["disabled"])
        self.working_status_label = ttk.Label(
            self.working_frame,
            textvariable=self.working_status_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
        )
        self.working_status_label.grid(
            row=1,
            column=0,
            columnspan=6,
            sticky="ew",
            pady=(6, 0),
        )
        self.working_frame.columnconfigure(1, weight=1)

        self.backup_frame = ttk.LabelFrame(self.storage_tab, text="Import / Export", padding=(8, 8))
        self.backup_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(
            self.backup_frame,
            text=(
                "Export the full settings — every profile, folder, and per-profile option — to a JSON "
                "file, or restore them from a previous export. Importing replaces every profile and "
                "setting in this installation; the background loop picks up the imported settings on "
                "its next rotation."
            ),
            justify=tk.LEFT,
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="ew")
        self.export_settings_button = ttk.Button(
            self.backup_frame,
            text="Export Settings...",
            command=self._export_settings,
        )
        self.export_settings_button.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.import_settings_button = ttk.Button(
            self.backup_frame,
            text="Import Settings...",
            command=self._import_settings,
        )
        self.import_settings_button.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        self.backup_status_label = ttk.Label(
            self.backup_frame,
            textvariable=self.backup_status_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
        )
        self.backup_status_label.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.backup_frame.columnconfigure(2, weight=1)

        self.collections_scope_label = ttk.Label(
            self.collections_tab,
            text="Application feature — downloads run only when requested",
            style="Heading.TLabel",
        )
        self.collections_scope_label.pack(anchor="w")
        self.collections_profile_label = ttk.Label(
            self.collections_tab,
            textvariable=self.collections_profile_scope_var,
            justify=tk.LEFT,
            wraplength=840,
        )
        self.collections_profile_label.pack(anchor="w", pady=(0, 4))

        ttk.Label(
            self.collections_tab,
            text=(
                "Download optional wallpaper collections directly into a local folder. MBS accepts only "
                "NASA records without third-party copyright metadata and Wikimedia files explicitly marked "
                "CC0 or public domain. Downloaded originals are not modified."
            ),
            justify=tk.LEFT,
            wraplength=860,
        ).pack(anchor="w", pady=(0, 6))
        automatic = ttk.LabelFrame(
            self.collections_tab,
            text="Automatic collections — no account required",
            padding=(10, 6),
        )
        automatic.pack(fill=tk.X)
        ttk.Label(automatic, text="Collection:").grid(row=0, column=0, sticky="w")
        self.collections_combo = ttk.Combobox(
            automatic,
            textvariable=self.collections_name_var,
            values=[collection.name for collection in public_collections.PUBLIC_COLLECTIONS],
            state="readonly",
            width=38,
        )
        self.collections_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.collections_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_collection_description())
        ttk.Label(automatic, text="Images:").grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.collections_count_spinbox = ttk.Spinbox(
            automatic,
            from_=10,
            to=100,
            increment=5,
            textvariable=self.collections_count_var,
            width=5,
        )
        self.collections_count_spinbox.grid(row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Label(
            automatic,
            textvariable=self.collections_description_var,
            justify=tk.LEFT,
            wraplength=800,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 6))
        ttk.Label(automatic, text="Collection library folder:").grid(row=2, column=0, sticky="w")
        self.collections_root_entry = ttk.Entry(automatic, textvariable=self.collections_root_var)
        self.collections_root_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6)
        self.collections_browse_button = ttk.Button(
            automatic,
            text="Browse...",
            command=self._browse_collections_root,
        )
        self.collections_browse_button.grid(row=2, column=3, sticky="w")
        self.collections_add_source_checkbutton = ttk.Checkbutton(
            automatic,
            text="Add the downloaded collection folder to the selected profile and save it",
            variable=self.collections_add_source_var,
        )
        self.collections_add_source_checkbutton.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 2))
        collection_actions = ttk.Frame(automatic)
        collection_actions.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.collections_download_button = ttk.Button(
            collection_actions,
            text="Download Collection",
            command=self._download_public_collection,
        )
        self.collections_download_button.pack(side=tk.LEFT)
        self.collections_cancel_button = ttk.Button(
            collection_actions,
            text="Cancel Download",
            command=self._cancel_public_collection_download,
        )
        self.collections_cancel_button.pack(side=tk.LEFT, padx=6)
        self.collections_cancel_button.state(["disabled"])
        ttk.Label(
            collection_actions,
            textvariable=self.collections_status_var,
            justify=tk.LEFT,
            wraplength=600,
        ).pack(side=tk.LEFT, padx=(8, 0))
        automatic.columnconfigure(1, weight=1)

        recommended = ttk.LabelFrame(
            self.collections_tab,
            text="Additional recommended sources — manual access or personal API key required",
            padding=(10, 6),
        )
        recommended.pack(fill=tk.X, pady=(8, 0))
        self.collection_source_buttons = []
        for row, source in enumerate(public_collections.RECOMMENDED_SOURCES):
            ttk.Label(recommended, text=source.name, width=24).grid(row=row, column=0, sticky="nw", pady=3)
            ttk.Label(recommended, text=source.description, wraplength=570, justify=tk.LEFT).grid(
                row=row,
                column=1,
                sticky="w",
                padx=6,
                pady=3,
            )
            button = ttk.Button(
                recommended,
                text="Open Source",
                command=lambda selected=source: self._open_collection_source(selected),
            )
            button.grid(row=row, column=2, sticky="e", pady=3)
            self.collection_source_buttons.append(button)
        recommended.columnconfigure(1, weight=1)
        self.collections_safety_label = ttk.Label(
            self.collections_tab,
            text=(
                "Provenance is saved. CC0/public-domain status covers copyright only; "
                "review other rights and suitability before sharing."
            ),
            justify=tk.LEFT,
            wraplength=860,
        )
        self.collections_safety_label.pack(anchor="w", pady=(6, 0))

        self.about_scope_label = ttk.Label(
            self.about_tab,
            text="Application settings and information — shared by every profile",
            style="Heading.TLabel",
        )
        self.about_scope_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.about_tab,
            text=f"{APP_NAME}\nVersion {__version__}",
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.about_tab,
            text=(
                "A local Linux Mint/Cinnamon wallpaper switcher with per-profile layouts, effects, "
                "multi-monitor composition, and source-preserving generated wallpapers."
            ),
            justify=tk.LEFT,
            wraplength=760,
        ).pack(anchor="w", pady=(0, 16))
        maintenance = ttk.LabelFrame(self.about_tab, text="Application updates", padding=10)
        maintenance.pack(fill=tk.X)
        ttk.Label(maintenance, text="Application updates:").pack(side=tk.LEFT, padx=(3, 6))
        self.update_button = ttk.Button(maintenance, text="Check for Updates...", command=self._check_for_updates)
        self.update_button.pack(side=tk.LEFT, padx=3)
        self.rollback_button = ttk.Button(maintenance, text="Roll Back...", command=self._rollback_update)
        self.rollback_button.pack(side=tk.LEFT, padx=3)
        ttk.Label(maintenance, textvariable=self.update_status_var).pack(side=tk.LEFT, padx=(8, 3))

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X)
        self.apply_button = ttk.Button(bottom, text="Save & Apply Now", command=self._apply_next)
        self.apply_button.pack(side=tk.LEFT, padx=1)
        self.black_button = ttk.Button(bottom, text="Black Screen", command=self._black_screen)
        self.black_button.pack(side=tk.LEFT, padx=1)
        self.export_button = ttk.Button(bottom, text="Save Wallpaper...", command=self._export_current_wallpaper)
        self.export_button.pack(side=tk.LEFT, padx=1)
        self.current_pictures_button = ttk.Button(
            bottom,
            text="View Pictures...",
            command=self._view_current_pictures,
        )
        self.current_pictures_button.pack(side=tk.LEFT, padx=1)
        self.close_button = ttk.Button(bottom, text="Close", command=self._request_close)
        self.close_button.pack(side=tk.RIGHT, padx=1)
        self.about_button = ttk.Button(
            bottom,
            text="Updates & About",
            command=lambda: self.notebook.select(self.about_tab),
        )
        self.about_button.pack(side=tk.RIGHT, padx=1)
        self.footer_version_label = ttk.Label(bottom, text=f"v{__version__}")
        self.footer_version_label.pack(side=tk.RIGHT, padx=(2, 4))
        self._refresh_rollback_button()
        self._refresh_update_status()

    def _refresh_profile_scope_labels(self, *_args: object) -> None:
        """Keep profile-scoped pages and collection targeting explicit."""

        profile_name = self.profile_var.get().strip() or "selected profile"
        self.profile_scope_var.set(f"Profile settings for “{profile_name}”")
        self.collections_profile_scope_var.set(
            f"Optional source setup targets the selected profile: “{profile_name}”."
        )

    def _select_layout(self, layout: str) -> None:
        """Show the workspace for a user-selected pending layout without saving it."""

        if layout not in self.layout_panels:
            return
        if self.mode_var.get() != layout:
            self.mode_var.set(layout)
        else:
            self._refresh_layout_workspace()
        self.notebook.select(self.layout_tab)

    def _refresh_layout_workspace(self, *_args: object) -> None:
        """Keep the unified Layout page synchronized with the pending layout value."""

        layout = self.mode_var.get()
        if layout not in self.layout_panels:
            layout = LAYOUT_CHOICES[0]
            self.mode_var.set(layout)
        self.layout_description_var.set(LAYOUT_DESCRIPTIONS[layout])
        for panel in self.layout_panels.values():
            panel.pack_forget()
        self.layout_panels[layout].pack(fill=tk.BOTH, expand=True)

    def _load_profile(self, name: str) -> None:
        profile = self.config_data.get_profile(name)
        self.interval_var.set(str(profile.interval_minutes))
        self.mode_var.set(profile.mode)
        self.recursive_var.set(profile.recursive)
        self.min_image_size_var.set(str(profile.min_image_size))
        self.ignore_hidden_var.set(profile.ignore_hidden)
        self.ignore_patterns_var.set(", ".join(profile.ignore_patterns))
        self.image_types_var.set(", ".join(profile.image_types))
        self.sequential_var.set(profile.sequential)
        self.match_orientation_var.set(profile.match_orientation)
        self.rotate_on_startup_var.set(profile.rotate_on_startup)
        self.night_black_screen_var.set(profile.night_black_screen)
        self.night_start_var.set(profile.night_start)
        self.night_end_var.set(profile.night_end)
        self.mirror_lockscreen_var.set(profile.mirror_lockscreen)
        self.suppress_process_var.set(bool(profile.suppress_process))
        self.suppress_process_name_var.set(profile.suppress_process)
        self.suppress_battery_var.set(profile.suppress_on_battery)
        self.suppress_remote_var.set(profile.suppress_remote_session)
        self.idle_only_var.set(profile.idle_only)
        self.idle_seconds_var.set(str(profile.idle_seconds))
        self.suppress_locked_var.set(profile.suppress_when_locked)
        self.hotkey_var.set(profile.black_hotkey)
        self.next_hotkey_var.set(profile.next_hotkey)
        self.pause_hotkey_var.set(profile.pause_hotkey)
        self.desktop_var.set(profile.desktop)
        self.effect_var.set(profile.effect)
        self.bar_color_var.set(profile.bar_color)
        self.fit_mode_var.set(FIT_MODE_LABELS.get(profile.fit_mode, FIT_MODE_LABELS["fit_bars"]))
        self.postcard_background_var.set(profile.postcard_background)
        self.postcard_count_var.set(profile.postcard_count)
        self.postcard_size_var.set(profile.postcard_size)
        self.postcard_span_var.set(profile.postcard_span)
        self.postcard_tilt_var.set(profile.postcard_tilt)
        self.postcard_captions_var.set(profile.postcard_captions)
        self.polaroid_count_var.set(profile.polaroid_count)
        self.polaroid_size_var.set(profile.polaroid_size)
        self.polaroid_span_var.set(profile.polaroid_span)
        self.polaroid_tilt_var.set(profile.polaroid_tilt)
        self.polaroid_captions_var.set(profile.polaroid_captions)
        self.shared_text.delete("1.0", tk.END)
        self.shared_text.insert(tk.END, "\n".join(profile.shared_folders))
        self._write_monitor_folders({monitor: list(paths) for monitor, paths in profile.monitor_folders.items()})
        self._refresh_excluded_tab()

    def _refresh_excluded_tab(self) -> None:
        """Reload the Never Show Again page from the saved config and state."""
        name = self.profile_var.get()
        try:
            excluded = get_excluded_images(name)
        except Exception:
            excluded = []
        self._excluded_display = list(excluded)
        self.excluded_list.delete(0, tk.END)
        for path in excluded:
            self.excluded_list.insert(tk.END, path)
        try:
            sources = [str(image) for image in current_source_images()]
        except Exception:
            sources = []
        self.excluded_current_text.configure(state=tk.NORMAL)
        self.excluded_current_text.delete("1.0", tk.END)
        self.excluded_current_text.insert(
            tk.END,
            "\n".join(sources) if sources else "No source pictures are recorded for the current wallpaper yet.",
        )
        self.excluded_current_text.configure(state=tk.DISABLED)
        self.excluded_status_var.set(_excluded_count_status(len(excluded)))

    def _sync_profile_exclusions(self, name: str) -> None:
        """Keep the in-memory profile's exclusion list in step with the saved config."""
        profile = self.config_data.profiles.get(name)
        if profile is None:
            return
        try:
            profile.excluded_images = list(get_excluded_images(name))
        except Exception:
            pass

    def _exclude_current_wallpaper(self) -> None:
        name = self.profile_var.get()
        try:
            sources = [str(image) for image in current_source_images()]
        except Exception as exc:
            messagebox.showerror("Could not read the current wallpaper", str(exc), parent=self)
            return
        if not sources:
            self.excluded_status_var.set("No source pictures are recorded for the current wallpaper yet.")
            return
        try:
            added = exclude_current_images(name, sources)
        except Exception as exc:
            messagebox.showerror("Could not exclude pictures", str(exc), parent=self)
            return
        self._sync_profile_exclusions(name)
        self._refresh_excluded_tab()
        if added:
            self.excluded_status_var.set(_excluded_count_status(len(added), action="excluded"))
        else:
            self.excluded_status_var.set("The current wallpaper's pictures are already excluded.")

    def _remove_selected_excluded(self) -> None:
        selection = self.excluded_list.curselection()
        if not selection:
            self.excluded_status_var.set("Select one or more pictures to remove first.")
            return
        name = self.profile_var.get()
        paths = [self._excluded_display[index] for index in selection]
        try:
            removed = remove_excluded_images(name, paths)
        except Exception as exc:
            messagebox.showerror("Could not remove exclusions", str(exc), parent=self)
            return
        self._sync_profile_exclusions(name)
        self._refresh_excluded_tab()
        self.excluded_status_var.set(_excluded_count_status(len(removed), action="removed"))

    def _clear_excluded_confirmed(self) -> None:
        name = self.profile_var.get()
        count = len(self._excluded_display)
        if not count:
            self.excluded_status_var.set("The never-show-again list is already empty.")
            return
        if not messagebox.askyesno(
            "Clear never-show-again list",
            f"Remove all {count} excluded picture{'s' if count != 1 else ''} for “{name}”?",
            parent=self,
        ):
            return
        try:
            removed = clear_excluded_images(name)
        except Exception as exc:
            messagebox.showerror("Could not clear exclusions", str(exc), parent=self)
            return
        self._sync_profile_exclusions(name)
        self._refresh_excluded_tab()
        self.excluded_status_var.set(_excluded_count_status(removed, action="cleared"))

    def _refresh_night_time_state(self, *_args: object) -> None:
        """Enable the night-window time fields only while the schedule is on."""
        state = "normal" if self.night_black_screen_var.get() else "disabled"
        self.night_start_entry.configure(state=state)
        self.night_end_entry.configure(state=state)

    def _refresh_run_condition_states(self, *_args: object) -> None:
        """Enable the run-condition value fields only while their toggle is on."""
        process_state = "normal" if self.suppress_process_var.get() else "disabled"
        self.suppress_process_name_entry.configure(state=process_state)
        idle_state = "normal" if self.idle_only_var.get() else "disabled"
        self.idle_seconds_entry.configure(state=idle_state)

    def _refresh_postcard_count_label(self, *_args: object) -> None:
        text = "Postcard photos across all screens:" if self.postcard_span_var.get() else "Postcard photos per screen:"
        self.postcard_count_label.configure(text=text)

    def _refresh_polaroid_count_label(self, *_args: object) -> None:
        text = "Polaroid photos across all screens:" if self.polaroid_span_var.get() else "Polaroid photos per screen:"
        self.polaroid_count_label.configure(text=text)

    def _set_monitor_text(self, text: str) -> None:
        try:
            self.monitor_text.configure(state="normal")
        except Exception:
            pass
        self.monitor_text.delete("1.0", tk.END)
        self.monitor_text.insert(tk.END, text)
        try:
            self.monitor_text.configure(state="disabled")
        except Exception:
            pass

    def _parse_monitor_folders(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for raw in self.monitor_text.get("1.0", tk.END).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Monitor folder line must be MONITOR=/path/a;/path/b: {line!r}")
            monitor, paths = line.split("=", 1)
            result[monitor.strip()] = [p.strip() for p in paths.split(";") if p.strip()]
        return result

    def _profile_from_fields(self, name: str) -> Profile:
        postcard_count_var = vars(self).get("postcard_count_var")
        postcard_size_var = vars(self).get("postcard_size_var")
        postcard_span_var = vars(self).get("postcard_span_var")
        postcard_tilt_var = vars(self).get("postcard_tilt_var")
        postcard_background_var = vars(self).get("postcard_background_var")
        count_var = vars(self).get("polaroid_count_var")
        size_var = vars(self).get("polaroid_size_var")
        span_var = vars(self).get("polaroid_span_var")
        tilt_var = vars(self).get("polaroid_tilt_var")
        min_image_size_var = vars(self).get("min_image_size_var")
        if min_image_size_var is None:
            min_image_size = 0
        else:
            raw_min_image_size = str(min_image_size_var.get()).strip()
            try:
                min_image_size = max(0, min(int(raw_min_image_size), 100_000))
            except ValueError:
                raise ValueError(
                    "Minimum image size must be a whole number of pixels (0 means no limit)."
                ) from None
        ignore_hidden_var = vars(self).get("ignore_hidden_var")
        ignore_hidden = bool(ignore_hidden_var.get()) if ignore_hidden_var is not None else False
        ignore_patterns_var = vars(self).get("ignore_patterns_var")
        raw_patterns = str(ignore_patterns_var.get()).strip() if ignore_patterns_var is not None else ""
        ignore_patterns: list[str] = []
        seen_patterns: set[str] = set()
        for raw in raw_patterns.split(","):
            pattern = raw.strip()
            if not pattern:
                continue
            if len(pattern) > MAX_IGNORE_PATTERN_LENGTH:
                raise ValueError(
                    f"Each ignore pattern can be at most {MAX_IGNORE_PATTERN_LENGTH} characters: {pattern!r}"
                )
            lowered = pattern.lower()
            if lowered in seen_patterns:
                continue
            seen_patterns.add(lowered)
            ignore_patterns.append(pattern)
        if len(ignore_patterns) > MAX_IGNORE_PATTERNS:
            raise ValueError(f"At most {MAX_IGNORE_PATTERNS} ignore patterns can be saved.")
        image_types_var = vars(self).get("image_types_var")
        raw_types = str(image_types_var.get()).strip() if image_types_var is not None else ""
        image_types: list[str] = []
        seen_types: set[str] = set()
        for raw in raw_types.split(","):
            token = raw.strip().lower().lstrip(".")
            if not token or token in seen_types:
                continue
            if token not in SUPPORTED_TYPE_NAMES:
                raise ValueError(
                    f"Unknown image type {token!r}; supported types are {', '.join(SUPPORTED_TYPE_NAMES)}."
                )
            seen_types.add(token)
            image_types.append(token)
        sequential_var = vars(self).get("sequential_var")
        sequential = bool(sequential_var.get()) if sequential_var is not None else False
        match_orientation_var = vars(self).get("match_orientation_var")
        match_orientation = bool(match_orientation_var.get()) if match_orientation_var is not None else False
        rotate_on_startup_var = vars(self).get("rotate_on_startup_var")
        rotate_on_startup = bool(rotate_on_startup_var.get()) if rotate_on_startup_var is not None else True
        mirror_lockscreen_var = vars(self).get("mirror_lockscreen_var")
        mirror_lockscreen = bool(mirror_lockscreen_var.get()) if mirror_lockscreen_var is not None else False
        night_black_screen_var = vars(self).get("night_black_screen_var")
        night_black_screen = bool(night_black_screen_var.get()) if night_black_screen_var is not None else False
        night_start_var = vars(self).get("night_start_var")
        night_end_var = vars(self).get("night_end_var")
        raw_night_start = str(night_start_var.get()).strip() if night_start_var is not None else DEFAULT_NIGHT_START
        raw_night_end = str(night_end_var.get()).strip() if night_end_var is not None else DEFAULT_NIGHT_END
        parsed_night_start = parse_night_time(raw_night_start)
        parsed_night_end = parse_night_time(raw_night_end)
        if night_black_screen:
            if parsed_night_start is None:
                raise ValueError("Night window start time must use HH:MM (for example 22:00).")
            if parsed_night_end is None:
                raise ValueError("Night window end time must use HH:MM (for example 06:00).")
            if parsed_night_start == parsed_night_end:
                raise ValueError("The night window start and end times must differ.")
        night_start = raw_night_start if parsed_night_start is not None else DEFAULT_NIGHT_START
        night_end = raw_night_end if parsed_night_end is not None else DEFAULT_NIGHT_END
        suppress_process_var = vars(self).get("suppress_process_var")
        suppress_process_enabled = bool(suppress_process_var.get()) if suppress_process_var is not None else False
        suppress_process_name_var = vars(self).get("suppress_process_name_var")
        raw_suppress_process = (
            str(suppress_process_name_var.get()).strip() if suppress_process_name_var is not None else ""
        )
        if suppress_process_enabled:
            if not raw_suppress_process:
                raise ValueError("Enter the process name to watch, or turn the run condition off.")
            if len(raw_suppress_process) > MAX_SUPPRESS_PROCESS_LENGTH:
                raise ValueError(
                    f"The process name can be at most {MAX_SUPPRESS_PROCESS_LENGTH} characters "
                    "(Linux process names are limited to that length)."
                )
        else:
            raw_suppress_process = ""
        suppress_battery_var = vars(self).get("suppress_battery_var")
        suppress_on_battery = bool(suppress_battery_var.get()) if suppress_battery_var is not None else False
        suppress_remote_var = vars(self).get("suppress_remote_var")
        suppress_remote_session = bool(suppress_remote_var.get()) if suppress_remote_var is not None else False
        idle_only_var = vars(self).get("idle_only_var")
        idle_only = bool(idle_only_var.get()) if idle_only_var is not None else False
        idle_seconds_var = vars(self).get("idle_seconds_var")
        raw_idle_seconds = str(idle_seconds_var.get()).strip() if idle_seconds_var is not None else str(DEFAULT_IDLE_SECONDS)
        try:
            idle_seconds = int(raw_idle_seconds)
        except ValueError:
            raise ValueError("The idle time must be a whole number of seconds.") from None
        if not 0 <= idle_seconds <= MAX_IDLE_SECONDS:
            raise ValueError(f"The idle time must be between 0 and {MAX_IDLE_SECONDS} seconds.")
        suppress_locked_var = vars(self).get("suppress_locked_var")
        suppress_when_locked = bool(suppress_locked_var.get()) if suppress_locked_var is not None else False
        next_hotkey_var = vars(self).get("next_hotkey_var")
        next_hotkey = (
            str(next_hotkey_var.get()).strip() if next_hotkey_var is not None else ""
        ) or DEFAULT_NEXT_HOTKEY
        pause_hotkey_var = vars(self).get("pause_hotkey_var")
        pause_hotkey = (
            str(pause_hotkey_var.get()).strip() if pause_hotkey_var is not None else ""
        ) or DEFAULT_PAUSE_HOTKEY
        postcard_count = max(1, min(100, int(postcard_count_var.get()))) if postcard_count_var is not None else 4
        postcard_size = (
            max(0.0, min(1.0, float(postcard_size_var.get()))) if postcard_size_var is not None else 0.5
        )
        postcard_span = bool(postcard_span_var.get()) if postcard_span_var is not None else False
        postcard_tilt = bool(postcard_tilt_var.get()) if postcard_tilt_var is not None else True
        postcard_captions_var = vars(self).get("postcard_captions_var")
        postcard_captions = bool(postcard_captions_var.get()) if postcard_captions_var is not None else False
        postcard_background = (
            str(postcard_background_var.get()).strip().lower()
            if postcard_background_var is not None
            else POSTCARD_BACKGROUND_CHOICES[0]
        )
        if postcard_background not in POSTCARD_BACKGROUND_CHOICES:
            postcard_background = POSTCARD_BACKGROUND_CHOICES[0]
        polaroid_count = max(1, min(100, int(count_var.get()))) if count_var is not None else 4
        polaroid_size = max(0.0, min(1.0, float(size_var.get()))) if size_var is not None else 0.5
        polaroid_span = bool(span_var.get()) if span_var is not None else False
        polaroid_tilt = bool(tilt_var.get()) if tilt_var is not None else True
        polaroid_captions_var = vars(self).get("polaroid_captions_var")
        polaroid_captions = bool(polaroid_captions_var.get()) if polaroid_captions_var is not None else False
        fit_mode = FIT_MODE_LABEL_TO_VALUE.get(str(self.fit_mode_var.get()).strip(), "fit_bars")
        # Exclusions are managed on the Never Show Again page, not in these fields; carry the
        # current profile's list forward so saving or renaming never silently wipes it.
        existing = self.config_data.profiles.get(self.profile_var.get())
        excluded_images = list(existing.excluded_images) if existing is not None else []
        return Profile(
            name=name,
            interval_minutes=float(self.interval_var.get()),
            mode=self.mode_var.get(),
            recursive=self.recursive_var.get(),
            min_image_size=min_image_size,
            ignore_hidden=ignore_hidden,
            ignore_patterns=ignore_patterns,
            image_types=image_types,
            sequential=sequential,
            match_orientation=match_orientation,
            rotate_on_startup=rotate_on_startup,
            night_black_screen=night_black_screen,
            night_start=night_start,
            night_end=night_end,
            mirror_lockscreen=mirror_lockscreen,
            suppress_process=raw_suppress_process,
            suppress_on_battery=suppress_on_battery,
            suppress_remote_session=suppress_remote_session,
            idle_only=idle_only,
            idle_seconds=idle_seconds,
            suppress_when_locked=suppress_when_locked,
            postcard_captions=postcard_captions,
            polaroid_captions=polaroid_captions,
            shared_folders=[p.strip() for p in self.shared_text.get("1.0", tk.END).split("\n") if p.strip()],
            monitor_folders={monitor: list(paths) for monitor, paths in self._current_monitor_folders().items()},
            black_hotkey=self.hotkey_var.get().strip() or DEFAULT_BLACK_HOTKEY,
            next_hotkey=next_hotkey,
            pause_hotkey=pause_hotkey,
            desktop=self.desktop_var.get(),
            effect=self.effect_var.get(),
            bar_color=self.bar_color_var.get(),
            fit_mode=fit_mode,
            postcard_background=postcard_background,
            postcard_count=postcard_count,
            postcard_size=postcard_size,
            postcard_span=postcard_span,
            postcard_tilt=postcard_tilt,
            polaroid_count=polaroid_count,
            polaroid_size=polaroid_size,
            polaroid_span=polaroid_span,
            polaroid_tilt=polaroid_tilt,
            excluded_images=excluded_images,
        )

    def _save_current(self, show_success: bool = True) -> bool:
        if self._any_worker_busy():
            return False
        try:
            name = self.profile_var.get()
            profile = self._profile_from_fields(name)
            self.config_data.profiles[name] = profile
            self.config_data.active_profile = name
            save_config(self.config_data)
            self._refresh_profiles()
            if show_success:
                messagebox.showinfo("Saved", f"Saved profile {name!r}.")
            return True
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return False

    def _ask_profile_name(self, title: str, prompt: str, *, initialvalue: str = "") -> str | None:
        return simpledialog.askstring(title, prompt, initialvalue=initialvalue, parent=self)

    def _default_new_profile_name(self) -> str:
        base = "New Profile"
        if base not in self.config_data.profiles:
            return base
        i = 2
        while f"{base} {i}" in self.config_data.profiles:
            i += 1
        return f"{base} {i}"

    def _validated_profile_name(self, raw_name: str | None, *, existing_name: str | None = None) -> str | None:
        if raw_name is None:
            return None
        name = raw_name.strip()
        if not name:
            messagebox.showerror("Invalid profile name", "Profile name cannot be blank.")
            return None
        if name != existing_name and name in self.config_data.profiles:
            messagebox.showerror("Profile exists", f"A profile named {name!r} already exists.")
            return None
        return name

    def _new_profile(self) -> None:
        if self._any_worker_busy():
            return
        suggested = self._default_new_profile_name()
        name = self._validated_profile_name(
            self._ask_profile_name("New profile", "Profile name:", initialvalue=suggested)
        )
        if not name:
            return
        self.config_data.profiles[name] = Profile(name=name)
        self.config_data.active_profile = name
        save_config(self.config_data)
        self._refresh_profiles()
        self.profile_var.set(name)
        self._load_profile(name)

    def _rename_profile(self) -> None:
        if self._any_worker_busy():
            return
        old_name = self.profile_var.get()
        if old_name not in self.config_data.profiles:
            messagebox.showerror("Rename failed", f"No profile named {old_name!r}.")
            return
        new_name = self._validated_profile_name(
            self._ask_profile_name("Rename profile", "Profile name:", initialvalue=old_name),
            existing_name=old_name,
        )
        if not new_name or new_name == old_name:
            return
        try:
            profile = self._profile_from_fields(new_name)
            self.config_data.profiles.pop(old_name)
            self.config_data.profiles[new_name] = profile
            self.config_data.active_profile = new_name
            save_config(self.config_data)
            self._refresh_profiles()
            self.profile_var.set(new_name)
            self._load_profile(new_name)
        except Exception as exc:
            messagebox.showerror("Rename failed", str(exc))

    def _delete_profile(self) -> None:
        if self._any_worker_busy():
            return
        name = self.profile_var.get()
        if len(self.config_data.profiles) <= 1:
            messagebox.showwarning("Cannot delete", "At least one profile is required.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete profile {name!r}?"):
            return
        del self.config_data.profiles[name]
        self.config_data.active_profile = next(iter(self.config_data.profiles))
        save_config(self.config_data)
        self._refresh_profiles()
        self.profile_var.set(self.config_data.active_profile)
        self._load_profile(self.config_data.active_profile)

    def _refresh_profiles(self) -> None:
        values = sorted(self.config_data.profiles)
        self.profile_combo.configure(values=values)

    def _append_text_line(self, text_widget: tk.Text, value: str) -> None:
        value = value.strip()
        if not value:
            return
        existing = [line.strip() for line in text_widget.get("1.0", tk.END).split("\n") if line.strip()]
        if value in existing:
            return
        current = text_widget.get("1.0", tk.END).strip()
        if current:
            text_widget.insert(tk.END, "\n" + value)
        else:
            text_widget.insert(tk.END, value)

    def _selected_public_collection(self) -> public_collections.PublicCollection:
        selected_name = self.collections_name_var.get()
        for collection in public_collections.PUBLIC_COLLECTIONS:
            if collection.name == selected_name:
                return collection
        raise public_collections.CollectionDownloadError(f"Unknown public collection: {selected_name}")

    def _refresh_collection_description(self) -> None:
        try:
            self.collections_description_var.set(self._selected_public_collection().description)
        except public_collections.CollectionDownloadError as exc:
            self.collections_description_var.set(str(exc))

    def _browse_collections_root(self) -> None:
        current = Path(self.collections_root_var.get().strip() or Path.home()).expanduser()
        initial = current if current.is_dir() else current.parent
        selected = self._ask_folder(initialdir=str(initial), title="Choose a folder for public collections")
        if selected:
            self.collections_root_var.set(str(Path(selected).expanduser().absolute()))

    def _open_collection_source(self, source: public_collections.RecommendedSource) -> None:
        if source not in public_collections.RECOMMENDED_SOURCES:
            messagebox.showerror("Could not open source", "The selected collection source is not trusted.", parent=self)
            return
        opener = shutil.which("xdg-open")
        if opener is None:
            messagebox.showerror(
                "Could not open source",
                f"xdg-open is unavailable. Open this address manually:\n{source.url}",
                parent=self,
            )
            return
        try:
            subprocess.Popen(
                [opener, source.url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                shell=False,
            )
        except OSError as exc:
            messagebox.showerror("Could not open source", str(exc), parent=self)

    def _download_public_collection(self) -> None:
        if self._any_worker_busy():
            return
        try:
            collection = self._selected_public_collection()
            count = int(self.collections_count_var.get())
            if count < 10 or count > 100:
                raise ValueError("Choose between 10 and 100 images.")
            root_text = self.collections_root_var.get().strip()
            if not root_text:
                raise ValueError("Choose a collection library folder.")
            root = Path(root_text).expanduser().absolute()
            destination = root / collection.slug
        except (ValueError, public_collections.CollectionDownloadError) as exc:
            messagebox.showerror("Could not start collection download", str(exc), parent=self)
            return

        self._collection_cancel.clear()
        self._collection_busy = True
        self.collections_status_var.set("Starting collection download...")
        self._refresh_worker_controls()

        def progress(completed: int, total: int, name: str) -> None:
            self._operation_results.put(("collection-progress", (completed, total, name), None))

        def run() -> None:
            try:
                result = public_collections.download_public_collection(
                    collection.slug,
                    destination,
                    count,
                    cancelled=self._collection_cancel.is_set,
                    progress=progress,
                )
            except Exception as exc:
                self._operation_results.put(("collection-done", None, exc))
            else:
                self._operation_results.put(("collection-done", result, None))

        worker = threading.Thread(target=run, name="mbs-public-collection-download", daemon=False)
        self._collection_worker = worker
        try:
            worker.start()
        except Exception:
            self._collection_worker = None
            self._collection_busy = False
            self._refresh_worker_controls()
            raise

    def _cancel_public_collection_download(self) -> None:
        if self._optional_attr("_collection_busy", False):
            self._collection_cancel.set()
            self.collections_status_var.set("Cancellation requested; finishing the current safe download step...")

    def _ask_folder(self, *, initialdir: str | None = None, title: str | None = None) -> str:
        if initialdir and title:
            return filedialog.askdirectory(initialdir=initialdir, title=title)
        if initialdir:
            return filedialog.askdirectory(initialdir=initialdir)
        if title:
            return filedialog.askdirectory(title=title)
        return filedialog.askdirectory()

    def _add_shared_folder(self, *, initialdir: str | None = None, title: str | None = None) -> None:
        folder = self._ask_folder(initialdir=initialdir, title=title)
        if folder:
            self._append_text_line(self.shared_text, folder)

    def _add_shared_folder_from_root(self) -> None:
        self._add_shared_folder(initialdir="/", title="Add a wallpaper folder from any mounted drive")

    def _ask_picture(self) -> str:
        pictures = Path.home() / "Pictures"
        initial_directory = pictures if pictures.is_dir() else Path.home()
        return filedialog.askopenfilename(
            parent=self,
            initialdir=str(initial_directory),
            title="Add an individual wallpaper picture",
            filetypes=(
                ("Supported pictures", SUPPORTED_PICTURE_PATTERNS),
                ("All files", "*"),
            ),
        )

    def _add_shared_picture(self) -> None:
        selected = self._ask_picture()
        if not selected:
            return
        try:
            picture = _selected_source_picture(selected)
            existing = {
                line.strip()
                for line in self.shared_text.get("1.0", tk.END).split("\n")
                if line.strip()
            }
            if str(picture) in existing:
                messagebox.showinfo(
                    "Picture already listed",
                    f"This picture is already in the shared source list:\n{picture}",
                    parent=self,
                )
                return
            self._append_text_line(self.shared_text, str(picture))
        except Exception as exc:
            messagebox.showerror("Could not add picture", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Picture added",
            f"Added to the shared source list:\n{picture}\n\nChoose Save Profile to keep this profile change.",
            parent=self,
        )

    def _optional_attr(self, name: str, default=None):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return default

    def _current_monitor_folders(self) -> dict[str, list[str]]:
        data = self._optional_attr("monitor_folders_data")
        if isinstance(data, dict):
            return {str(monitor): [str(path) for path in paths] for monitor, paths in data.items()}
        return self._parse_monitor_folders()

    def _write_monitor_folders(self, folders: dict[str, list[str]]) -> None:
        self.monitor_folders_data = {str(monitor): list(paths) for monitor, paths in folders.items() if paths}
        lines = [f"{mon}=" + ";".join(paths) for mon, paths in sorted(self.monitor_folders_data.items())]
        self._set_monitor_text("\n".join(lines))

    def _insert_monitor_folder(self, monitor: str, folder: str) -> None:
        monitor = monitor.strip()
        folder = folder.strip()
        if not monitor or not folder:
            return
        folders = self._current_monitor_folders()
        monitor_folders = folders.setdefault(monitor, [])
        if folder not in monitor_folders:
            monitor_folders.append(folder)
        self._write_monitor_folders(folders)

    def _remove_monitor_folder(self, monitor: str, folder: str) -> None:
        monitor = monitor.strip()
        folder = folder.strip()
        if not monitor or not folder:
            return
        folders = self._current_monitor_folders()
        remaining = [path for path in folders.get(monitor, []) if path != folder]
        if remaining:
            folders[monitor] = remaining
        else:
            folders.pop(monitor, None)
        self._write_monitor_folders(folders)

    def _choose_monitor_folder_to_remove(self) -> tuple[str, str] | None:
        folders = self._current_monitor_folders()
        monitors = [monitor for monitor, paths in sorted(folders.items()) if paths]
        if not monitors:
            messagebox.showinfo("No per-monitor folders", "There are no per-monitor folder assignments to remove.")
            return None

        selected: dict[str, tuple[str, str] | None] = {"value": None}
        dialog = tk.Toplevel(self)
        dialog.title("Remove per-monitor folder")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        monitor_var = tk.StringVar(value=monitors[0])
        folder_var = tk.StringVar(value=folders[monitors[0]][0])

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Remove which per-monitor folder?").pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="Screen:").pack(anchor="w")
        monitor_combo = ttk.Combobox(frame, textvariable=monitor_var, values=monitors, state="readonly", width=32)
        monitor_combo.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(frame, text="Folder:").pack(anchor="w")
        folder_combo = ttk.Combobox(frame, textvariable=folder_var, values=folders[monitors[0]], state="readonly", width=60)
        folder_combo.pack(fill=tk.X, pady=(0, 8))

        def refresh_folders(_event=None) -> None:
            paths = folders.get(monitor_var.get(), [])
            folder_combo.configure(values=paths)
            folder_var.set(paths[0] if paths else "")

        def ok() -> None:
            selected["value"] = (monitor_var.get().strip(), folder_var.get().strip())
            dialog.destroy()

        def cancel() -> None:
            selected["value"] = None
            dialog.destroy()

        monitor_combo.bind("<<ComboboxSelected>>", refresh_folders)
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(buttons, text="Remove", command=ok).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.wait_window()
        return selected["value"]

    def _remove_monitor_folder_from_dialog(self) -> None:
        choice = self._choose_monitor_folder_to_remove()
        if not choice:
            return
        monitor, folder = choice
        self._remove_monitor_folder(monitor, folder)

    def _available_monitor_names(self) -> list[str]:
        names = list(dict.fromkeys(self._optional_attr("monitor_names", []) or []))
        for monitor in self._current_monitor_folders():
            if monitor not in names:
                names.append(monitor)
        return names

    def _choose_monitor_for_folder(self, folder: str) -> str:
        monitors = self._available_monitor_names()
        if not monitors:
            messagebox.showerror("No monitors detected", "No screens are available to assign this folder to.")
            return ""

        selected = {"monitor": ""}
        dialog = tk.Toplevel(self)
        dialog.title("Choose screen")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        default = self.monitor_folder_var.get().strip()
        if default not in monitors:
            default = monitors[0]
        choice = tk.StringVar(value=default)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"Use this folder on which screen?\n{folder}", justify=tk.LEFT).pack(anchor="w", pady=(0, 8))
        for monitor in monitors:
            ttk.Radiobutton(frame, text=monitor, variable=choice, value=monitor).pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))

        def ok() -> None:
            selected["monitor"] = choice.get().strip()
            dialog.destroy()

        def cancel() -> None:
            selected["monitor"] = ""
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(buttons, text="Add", command=ok).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.wait_window()
        return selected["monitor"]

    def _add_monitor_folder_from_root(self) -> None:
        folder = self._ask_folder(initialdir="/", title="Choose a wallpaper folder for one screen")
        if not folder:
            return
        monitor = self._choose_monitor_for_folder(folder)
        if not monitor:
            return
        try:
            self._insert_monitor_folder(monitor, folder)
            self.monitor_folder_var.set(monitor)
        except Exception as exc:
            messagebox.showerror("Could not add folder", str(exc))

    def _any_worker_busy(self) -> bool:
        return bool(
            self._optional_attr("_update_busy", False)
            or self._optional_attr("_apply_busy", False)
            or self._optional_attr("_migration_busy", False)
            or self._optional_attr("_collection_busy", False)
        )

    def _refresh_worker_controls(self) -> None:
        busy = self._any_worker_busy()
        self.close_button.state(["disabled"] if busy else ["!disabled"])
        self.apply_button.configure(text="Applying..." if self._apply_busy else "Save & Apply Now")
        self.apply_button.state(["disabled"] if busy else ["!disabled"])
        for button in (
            self.profile_new_button,
            self.profile_rename_button,
            self.profile_delete_button,
            self.profile_save_button,
            self.shared_add_folder_button,
            self.shared_add_picture_button,
            self.shared_browse_drives_button,
            self.working_browse_button,
            self.working_create_button,
            self.working_use_button,
            self.collections_browse_button,
            self.collections_download_button,
            self.black_button,
            self.export_button,
            self.export_settings_button,
            self.import_settings_button,
            self.current_pictures_button,
            self.register_hotkeys_button,
        ):
            button.state(["disabled"] if busy else ["!disabled"])
        for control in (
            self.profile_combo,
            self.collections_combo,
            self.collections_count_spinbox,
            self.collections_root_entry,
            self.collections_add_source_checkbutton,
        ):
            control.state(["disabled"] if busy else ["!disabled"])
        for button in self.collection_source_buttons:
            button.state(["disabled"] if busy else ["!disabled"])
        self.working_cancel_button.state(["!disabled"] if self._migration_busy else ["disabled"])
        self.collections_cancel_button.state(["!disabled"] if self._collection_busy else ["disabled"])
        if busy:
            self.update_button.state(["disabled"])
            self.rollback_button.state(["disabled"])
        else:
            self.update_button.state(["!disabled"])
            self._refresh_rollback_button()

    def _browse_working_directory(self) -> None:
        current = Path(self.working_directory_var.get().strip() or "/").expanduser()
        initial = current if current.is_dir() else current.parent
        selected = self._ask_folder(initialdir=str(initial), title="Choose an empty MBS working folder")
        if selected:
            self.working_directory_var.set(str(Path(selected).expanduser().absolute()))
            self.working_status_var.set("Selected but not active. Click Use Folder to validate and copy managed files.")

    def _create_working_directory(self) -> None:
        parent = self._ask_folder(initialdir="/", title="Choose where to create an MBS working folder")
        if not parent:
            return
        name = simpledialog.askstring(
            "Create working folder",
            "New folder name:",
            initialvalue="MBS Working Files",
            parent=self,
        )
        if name is None:
            return
        try:
            created = create_working_directory(parent, name, self.config_data)
        except Exception as exc:
            messagebox.showerror("Could not create working folder", str(exc), parent=self)
            return
        self.working_directory_var.set(str(created))
        self.working_status_var.set("Folder created and validated. Click Use Folder to activate it.")

    def _use_working_directory(self) -> None:
        if self._any_worker_busy():
            return
        selected = self.working_directory_var.get().strip()
        if not selected:
            messagebox.showerror("Working folder required", "Choose or create a working folder first.", parent=self)
            return
        current = configured_working_directory(self.config_data)
        candidate = Path(selected).expanduser().absolute()
        if candidate.resolve(strict=False) == current.resolve(strict=False):
            self.working_directory_var.set(str(current))
            self.working_status_var.set(_active_working_directory_status(current))
            return
        create_candidate = not candidate.exists()
        if create_candidate and not candidate.parent.is_dir():
            messagebox.showerror(
                "Working folder parent missing",
                f"Create or choose the parent folder first:\n{candidate.parent}",
                parent=self,
            )
            return
        creation_note = "\n\nThis folder does not exist and will be created." if create_candidate else ""
        if not messagebox.askyesno(
            "Change working folder?",
            (
                f"Copy generated wallpapers and the library index from:\n{current}\n\nto:\n{candidate}\n\n"
                "The old files will be retained for recovery. Source wallpaper folders are never moved."
                f"{creation_note}"
            ),
            parent=self,
        ):
            return
        if not self._save_current(show_success=False):
            return
        if create_candidate:
            try:
                candidate = create_working_directory(candidate.parent, candidate.name, self.config_data)
            except Exception as exc:
                messagebox.showerror("Could not create working folder", str(exc), parent=self)
                return
            self.working_directory_var.set(str(candidate))

        self._migration_cancel.clear()
        self._migration_busy = True
        self.working_status_var.set("Preparing working-folder migration...")
        self._refresh_worker_controls()

        def progress(completed: int, total: int, name: str) -> None:
            self._operation_results.put(("migration-progress", (completed, total, name), None))

        def run() -> None:
            try:
                result = migrate_working_directory(
                    self.config_data,
                    candidate,
                    cancelled=self._migration_cancel.is_set,
                    progress=progress,
                )
            except Exception as exc:
                self._operation_results.put(("migration-done", None, exc))
            else:
                self._operation_results.put(("migration-done", result, None))

        worker = threading.Thread(target=run, name="mbs-working-folder-migration", daemon=False)
        self._migration_worker = worker
        try:
            worker.start()
        except Exception:
            self._migration_worker = None
            self._migration_busy = False
            self._refresh_worker_controls()
            raise

    def _cancel_working_migration(self) -> None:
        if self._optional_attr("_migration_busy", False):
            self._migration_cancel.set()
            self.working_status_var.set("Cancellation requested; waiting for the current verified copy step...")

    def _default_export_filename(self) -> str:
        return f"mbs-settings-{datetime.now():%Y%m%d-%H%M%S}.json"

    @staticmethod
    def _profile_count_text(count: int) -> str:
        return f"{count} profile" if count == 1 else f"{count} profiles"

    def _export_settings(self) -> None:
        if self._any_worker_busy():
            self.backup_status_var.set("Wait for the background work to finish, then export.")
            return
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Export settings",
            defaultextension=".json",
            initialfile=self._default_export_filename(),
            filetypes=[
                ("Mint Background Switcher settings (*.json)", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not destination:
            return
        try:
            path = config_io.export_config(self.config_data, Path(destination))
        except Exception as exc:
            self.backup_status_var.set("Export failed.")
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        count_text = self._profile_count_text(len(self.config_data.profiles))
        self.backup_status_var.set(f"Exported {count_text} to {path}")
        messagebox.showinfo(
            "Settings exported",
            (
                f"Exported {count_text} to\n{path}\n\n"
                "The export contains the saved settings; unsaved editor changes "
                "are not included."
            ),
            parent=self,
        )

    def _import_settings(self) -> None:
        if self._any_worker_busy():
            self.backup_status_var.set("Wait for the background work to finish, then import.")
            return
        source = filedialog.askopenfilename(
            parent=self,
            title="Import settings",
            filetypes=[
                ("Mint Background Switcher settings (*.json)", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not source:
            return
        try:
            candidate = config_io.load_export(Path(source))
        except Exception as exc:
            self.backup_status_var.set("Import failed: the selected file is not a valid settings export.")
            messagebox.showerror(
                "Import failed",
                f"The selected file is not a valid settings export:\n{exc}",
                parent=self,
            )
            return
        count_text = self._profile_count_text(len(candidate.profiles))
        if not messagebox.askokcancel(
            "Import settings",
            (
                f"Replace ALL profiles and settings with the contents of\n{source}?\n\n"
                f"Importing makes {count_text} from that file the only settings in this "
                "installation. Export a backup first if you want to restore the current "
                "settings later."
            ),
            parent=self,
        ):
            return
        try:
            imported = config_io.import_settings(Path(source), config_file())
        except Exception as exc:
            self.backup_status_var.set("Import failed.")
            messagebox.showerror("Import failed", str(exc), parent=self)
            return
        count_text = self._profile_count_text(len(imported.profiles))
        self.config_data = imported
        self.profile_var.set(imported.active_profile)
        self._refresh_profiles()
        self._load_profile(imported.active_profile)
        working_directory = configured_working_directory(imported)
        self.working_directory_var.set(str(working_directory))
        self.working_status_var.set(_active_working_directory_status(working_directory))
        self.backup_status_var.set(f"Imported {count_text} from {source}")
        messagebox.showinfo(
            "Settings imported",
            (
                f"Imported {count_text} from\n{source}\n\n"
                "The imported settings are active; the background loop uses them from "
                "its next rotation."
            ),
            parent=self,
        )

    def _set_apply_busy(self, busy: bool) -> None:
        self._apply_busy = busy
        self._refresh_worker_controls()

    def _poll_operation_results(self) -> None:
        try:
            while True:
                kind, result, error = self._operation_results.get_nowait()
                if kind == "migration-progress":
                    completed, total, name = result
                    self.working_status_var.set(f"Copying {completed}/{total}: {name}")
                    continue
                if kind == "migration-done":
                    if self._migration_worker is not None:
                        self._migration_worker.join()
                    self._migration_worker = None
                    self._migration_busy = False
                    self._refresh_worker_controls()
                    if error is not None:
                        if isinstance(error, WorkingDirectoryMigrationCancelled):
                            self.working_status_var.set("Working-folder migration cancelled; the previous folder remains active.")
                        else:
                            self.working_status_var.set("Working-folder migration failed; the previous folder remains active.")
                            messagebox.showerror("Working folder change failed", str(error), parent=self)
                    else:
                        self.config_data = load_config()
                        self.working_directory_var.set(str(result.destination))
                        self.working_status_var.set(_active_working_directory_status(result.destination))
                        messagebox.showinfo(
                            "Working folder changed",
                            (
                                f"MBS now uses:\n{result.destination}\n\n"
                                f"Previous generated files were retained at:\n{result.source}"
                            ),
                            parent=self,
                        )
                    continue
                if kind == "collection-progress":
                    completed, total, name = result
                    if completed:
                        self.collections_status_var.set(f"Downloading {completed}/{total}: {name}")
                    else:
                        self.collections_status_var.set(str(name))
                    continue
                if kind == "collection-done":
                    if self._collection_worker is not None:
                        self._collection_worker.join()
                    self._collection_worker = None
                    self._collection_busy = False
                    self._refresh_worker_controls()
                    if error is not None:
                        if isinstance(error, public_collections.CollectionDownloadCancelled):
                            self.collections_status_var.set("Collection download cancelled; no new partial files were kept.")
                        else:
                            self.collections_status_var.set("Collection download failed.")
                            messagebox.showerror("Collection download failed", str(error), parent=self)
                        continue

                    source_note = "The profile source list was not changed."
                    if self.collections_add_source_var.get():
                        self._append_text_line(self.shared_text, str(result.destination))
                        if self._save_current(show_success=False):
                            source_note = "The collection folder was added to the selected profile and saved."
                        else:
                            source_note = "The images were downloaded, but the profile source change could not be saved."
                    self.collections_status_var.set(
                        f"Ready: {result.downloaded} new, {result.existing} already present, {result.failed} unavailable."
                    )
                    unavailable = (
                        f"\n{result.failed} could not be downloaded from eligible provider results."
                        if result.failed
                        else ""
                    )
                    messagebox.showinfo(
                        "Collection downloaded",
                        (
                            f"{result.collection.name}: {result.downloaded} new, "
                            f"{result.existing} already present.{unavailable}\n\n"
                            f"Folder:\n{result.destination}\n\n"
                            f"Provenance manifest:\n{result.manifest_path}\n\n{source_note}"
                        ),
                        parent=self,
                    )
                    continue
                if kind == "apply-progress":
                    count, _path = result
                    self.apply_button.configure(text=f"Scanning... {count}")
                    continue
                if kind == "hotkeys-done":
                    if self._apply_worker is not None:
                        self._apply_worker.join()
                    self._apply_worker = None
                    self._set_apply_busy(False)
                    if error is not None:
                        messagebox.showerror("Register hotkeys failed", str(error), parent=self)
                    else:
                        lines = "\n".join(f"{label}: {binding}" for label, binding in result)
                        messagebox.showinfo(
                            "Hotkeys registered",
                            f"Cinnamon custom hotkeys for profile {self.profile_var.get()!r}:\n{lines}\n\n"
                            "They take effect immediately; re-register after future updates "
                            "from Settings or with the command-line register-hotkey action.",
                            parent=self,
                        )
                    continue
                if kind == "apply-rejected":
                    if self._apply_worker is not None:
                        self._apply_worker.join()
                    self._apply_worker = None
                    self._set_apply_busy(False)
                    previous_config, reason = result
                    # Roll the activation back so the previous profile keeps
                    # operating; the user's profile list and fields follow.
                    # Re-saving matters: the daemon and the next Settings
                    # session read the config from disk.
                    self.config_data = Config.from_dict(previous_config)
                    save_config(self.config_data)
                    self._refresh_profiles()
                    self.profile_var.set(self.config_data.active_profile)
                    self._load_profile(self.config_data.active_profile)
                    messagebox.showwarning(
                        "Profile switch rejected",
                        (
                            f"{reason}.\n\n"
                            f"The previous profile {self.config_data.active_profile!r} "
                            "remains active."
                        ),
                        parent=self,
                    )
                    continue
                if kind in {"apply-done", "black-done"}:
                    if self._apply_worker is not None:
                        self._apply_worker.join()
                    self._apply_worker = None
                    self._set_apply_busy(False)
                    if error is not None:
                        if kind == "black-done" and isinstance(error, SwitchCancelled):
                            continue
                        title = "Black screen failed" if kind == "black-done" else "Apply failed"
                        messagebox.showerror(title, str(error), parent=self)
                    else:
                        if kind == "apply-done" and getattr(result, "action", None) == "black-fallback":
                            title = "Safe black fallback"
                            detail = (
                                "No usable source images were available, so a black wallpaper was applied. "
                                "Check the selected profile folders and try again."
                            )
                        else:
                            title = "Black screen" if kind == "black-done" else "Applied"
                            detail = (
                                f"Generated {result.wallpaper}; rotation is paused."
                                if kind == "black-done"
                                else f"Generated {result.wallpaper}"
                            )
                        lockscreen_note = getattr(result, "lockscreen_note", "") or ""
                        if lockscreen_note:
                            detail = f"{detail}\n\n{lockscreen_note}"
                        messagebox.showinfo(title, detail, parent=self)
        except queue.Empty:
            pass
        try:
            self.after(100, self._poll_operation_results)
        except tk.TclError:
            pass

    def _export_current_wallpaper(self) -> None:
        if self._any_worker_busy():
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Save current wallpaper",
            defaultextension=".png",
            initialfile="current-background.png",
            filetypes=(("PNG image", "*.png"), ("All files", "*.*")),
            confirmoverwrite=False,
        )
        if not selected:
            return

        destination = Path(selected).expanduser()
        try:
            try:
                saved = save_current_wallpaper(destination)
            except FileExistsError:
                if not destination.exists() and not destination.is_symlink():
                    raise
                if not messagebox.askyesno(
                    "Replace existing file?",
                    f"A file already exists at:\n{destination}\n\nReplace it?",
                    parent=self,
                ):
                    return
                saved = save_current_wallpaper(destination, overwrite=True)
            messagebox.showinfo(
                "Wallpaper saved",
                f"Saved the current wallpaper to:\n{saved}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Save current wallpaper failed", str(exc), parent=self)

    def _view_current_pictures(self) -> None:
        if self._any_worker_busy():
            return

        existing_window = self._optional_attr("_current_pictures_window", None)
        try:
            if existing_window is not None and existing_window.winfo_exists():
                refresh = self._optional_attr("_refresh_current_pictures", None)
                if callable(refresh):
                    refresh()
                existing_window.deiconify()
                existing_window.lift()
                existing_window.focus_force()
                return
        except tk.TclError:
            self._current_pictures_window = None

        images = current_source_images()
        if not images:
            messagebox.showinfo(
                "No current pictures",
                "No source pictures are recorded for the current wallpaper. Choose Save & Apply Now first.",
                parent=self,
            )
            return

        window = tk.Toplevel(self)
        self._current_pictures_window = window
        window.title("Current Pictures")
        window.transient(self)
        window.geometry("760x360")
        window.minsize(520, 260)

        content = ttk.Frame(window, padding=12)
        content.pack(fill=tk.BOTH, expand=True)
        count_var = tk.StringVar(
            value=(
                f"{len(images)} unique source picture{'s' if len(images) != 1 else ''} "
                "were used in the current wallpaper."
            )
        )
        ttk.Label(content, textvariable=count_var).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(content)
        list_frame.pack(fill=tk.BOTH, expand=True)
        picture_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED, exportselection=False)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=picture_list.yview)
        picture_list.configure(yscrollcommand=scrollbar.set)
        picture_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        excluded_now = excluded_path_set(self.profile_var.get())

        def display_label(image: Path) -> str:
            if str(image) in excluded_now:
                return f"{image} [excluded]"
            try:
                resolved = str(image.resolve())
            except OSError:
                resolved = ""
            return f"{image} [excluded]" if resolved in excluded_now else str(image)

        for image in images:
            picture_list.insert(tk.END, display_label(image))
        picture_list.selection_set(0)
        picture_list.activate(0)

        status_var = tk.StringVar(
            value="Select a source picture, then open it, open its folder, or add it to Never Show Again."
        )
        ttk.Label(content, textvariable=status_var, anchor="w").pack(fill=tk.X, pady=(8, 4))
        buttons = ttk.Frame(content)
        buttons.pack(fill=tk.X)
        opening = [False]

        open_button = ttk.Button(buttons, text="Open Picture")
        open_button.pack(side=tk.LEFT)
        open_folder_button = ttk.Button(buttons, text="Open Containing Folder")
        open_folder_button.pack(side=tk.LEFT, padx=(6, 0))
        never_button = ttk.Button(buttons, text="Never Show Again")
        never_button.pack(side=tk.LEFT, padx=(6, 0))

        def set_open_controls_enabled(enabled: bool) -> None:
            state = ["!disabled"] if enabled else ["disabled"]
            open_button.state(state)
            open_folder_button.state(state)

        def refresh_sources() -> bool:
            nonlocal excluded_now
            latest = current_source_images()
            if latest == images:
                return False
            images[:] = latest
            excluded_now = excluded_path_set(self.profile_var.get())
            picture_list.delete(0, tk.END)
            for image in images:
                picture_list.insert(tk.END, display_label(image))
            count_var.set(
                f"{len(images)} unique source picture{'s' if len(images) != 1 else ''} "
                "were used in the current wallpaper."
            )
            if images:
                picture_list.selection_set(0)
                picture_list.activate(0)
                if not opening[0]:
                    set_open_controls_enabled(True)
                status_var.set("The wallpaper changed; the source list was refreshed. Select a picture to open.")
            else:
                set_open_controls_enabled(False)
                status_var.set("The current wallpaper has no recorded source pictures.")
            return True

        def open_selected(*, containing_folder: bool = False) -> None:
            if opening[0]:
                return
            if refresh_sources():
                return
            selected = picture_list.curselection()
            if not selected:
                messagebox.showinfo("Select a picture", "Select a source picture to open.", parent=window)
                return
            selected_picture = images[int(selected[0])]
            result_queue: queue.Queue[tuple[Path | None, Exception | None]] = queue.Queue()
            opening[0] = True
            set_open_controls_enabled(False)
            status_var.set(
                "Opening the selected picture's containing folder..."
                if containing_folder
                else "Opening the selected picture..."
            )

            def launch() -> None:
                try:
                    opener = _open_containing_folder if containing_folder else _open_picture
                    opened = opener(selected_picture)
                except Exception as exc:
                    result_queue.put((None, exc))
                else:
                    result_queue.put((opened, None))

            def poll_result() -> None:
                try:
                    opened, error = result_queue.get_nowait()
                except queue.Empty:
                    try:
                        window.after(50, poll_result)
                    except tk.TclError:
                        pass
                    return
                opening[0] = False
                try:
                    if images:
                        set_open_controls_enabled(True)
                    if error is not None:
                        status_var.set(
                            "The containing folder could not be opened."
                            if containing_folder
                            else "The selected picture could not be opened."
                        )
                        messagebox.showerror(
                            "Open folder failed" if containing_folder else "Open picture failed",
                            str(error),
                            parent=window,
                        )
                    elif opened is not None:
                        status_var.set(
                            f"Sent the folder containing {selected_picture.name} to the desktop file manager."
                            if containing_folder
                            else f"Sent {opened.name} to the default desktop application."
                        )
                except tk.TclError:
                    pass

            worker = threading.Thread(
                target=launch,
                name="mbs-picture-folder-opener" if containing_folder else "mbs-picture-opener",
                daemon=False,
            )
            try:
                worker.start()
            except Exception as exc:
                opening[0] = False
                set_open_controls_enabled(True)
                status_var.set(
                    "The containing folder could not be opened."
                    if containing_folder
                    else "The selected picture could not be opened."
                )
                messagebox.showerror(
                    "Open folder failed" if containing_folder else "Open picture failed",
                    str(exc),
                    parent=window,
                )
                return
            window.after(50, poll_result)

        open_button.configure(command=open_selected)
        open_folder_button.configure(command=lambda: open_selected(containing_folder=True))

        def exclude_selected() -> None:
            nonlocal excluded_now
            if opening[0]:
                return
            if refresh_sources():
                return
            selected = picture_list.curselection()
            if not selected:
                messagebox.showinfo("Select a picture", "Select one or more source pictures to exclude.", parent=window)
                return
            name = self.profile_var.get()
            paths = [str(images[index]) for index in selected]
            try:
                added = exclude_current_images(name, paths)
            except Exception as exc:
                messagebox.showerror("Could not exclude pictures", str(exc), parent=window)
                return
            self._sync_profile_exclusions(name)
            self._refresh_excluded_tab()
            if added:
                kept = set(selected)
                excluded_now = excluded_path_set(name)
                picture_list.delete(0, tk.END)
                for image in images:
                    picture_list.insert(tk.END, display_label(image))
                picture_list.selection_set(sorted(kept))
                status_var.set(_excluded_count_status(len(added), action="excluded"))
            else:
                status_var.set("The selected pictures are already on the never-show-again list.")

        never_button.configure(command=exclude_selected)
        ttk.Button(buttons, text="Refresh", command=refresh_sources).pack(side=tk.LEFT, padx=(6, 0))

        def close_window() -> None:
            self._current_pictures_window = None
            self._refresh_current_pictures = None
            window.destroy()

        ttk.Button(buttons, text="Close", command=close_window).pack(side=tk.RIGHT)
        window.protocol("WM_DELETE_WINDOW", close_window)
        picture_list.bind("<Double-Button-1>", lambda _event: open_selected())
        picture_list.bind("<Return>", lambda _event: open_selected())
        picture_list.focus_set()

        self.current_pictures_list = picture_list
        self.open_picture_button = open_button
        self.open_picture_folder_button = open_folder_button
        self.never_show_again_button = never_button
        self.current_picture_status_var = status_var
        self._refresh_current_pictures = refresh_sources

    def _show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            (
                f"{APP_NAME}\n"
                f"Version {__version__}\n\n"
                "A local-first Linux Mint/Cinnamon wallpaper switcher "
                "for multi-monitor desktops.\n\n"
                f"MIT License\n{PROJECT_URL}"
            ),
            parent=self,
        )

    def _refresh_rollback_button(self) -> None:
        try:
            available = updater.rollback_candidate() is not None
        except Exception:
            available = False
        if self._optional_attr("_update_busy", False):
            available = False
        self.rollback_button.state(["!disabled"] if available else ["disabled"])

    def _refresh_update_status(self) -> None:
        try:
            active = updater.active_install()
            managed_runtime = updater.is_managed_runtime()
        except Exception:
            active = None
            managed_runtime = False
        if active is not None and managed_runtime:
            status = f"Managed updates active (version {active.version})"
        elif active is not None:
            status = f"Managed version {active.version} ready after restart"
        else:
            status = "Managed updates not set up"
        self.update_status_var.set(status)

    def _set_update_busy(self, busy: bool, label: str = "Check for Updates...") -> None:
        self._update_busy = busy
        self.update_button.configure(text=label if busy else "Check for Updates...")
        if busy:
            self.update_status_var.set(label)
        else:
            self._refresh_update_status()
        self._refresh_worker_controls()

    def _request_close(self) -> None:
        if self._optional_attr("_update_busy", False):
            messagebox.showinfo(
                "Update in progress",
                "Keep Settings open until the current update operation finishes.",
                parent=self,
            )
            return
        if (
            self._optional_attr("_migration_busy", False)
            or self._optional_attr("_apply_busy", False)
            or self._optional_attr("_collection_busy", False)
        ):
            if self._optional_attr("_migration_busy", False):
                self._migration_cancel.set()
            if self._optional_attr("_apply_busy", False):
                self._apply_cancel.set()
            if self._optional_attr("_collection_busy", False):
                self._collection_cancel.set()
            messagebox.showinfo(
                "Operation in progress",
                "Cancellation was requested. Keep Settings open until the current safe step finishes.",
                parent=self,
            )
            return
        self.destroy()

    def _start_update_task(
        self,
        label: str,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        error_title: str,
    ) -> None:
        if self._any_worker_busy():
            return
        self._set_update_busy(True, label)

        def run() -> None:
            try:
                result = work()
            except Exception as exc:
                self._update_results.put((None, None, error_title, exc))
            else:
                self._update_results.put((on_success, result, error_title, None))

        worker = threading.Thread(target=run, name="mbs-update-worker", daemon=False)
        self._update_worker = worker
        try:
            worker.start()
        except Exception:
            self._update_worker = None
            self._set_update_busy(False)
            raise

    def _poll_update_results(self) -> None:
        try:
            while True:
                on_success, result, error_title, error = self._update_results.get_nowait()
                if self._update_worker is not None:
                    self._update_worker.join()
                self._update_worker = None
                self._set_update_busy(False)
                if error is not None:
                    messagebox.showerror(error_title, str(error), parent=self)
                elif on_success is not None:
                    on_success(result)
        except queue.Empty:
            pass
        try:
            self.after(100, self._poll_update_results)
        except tk.TclError:
            pass

    def _check_for_updates(self) -> None:
        self._start_update_task(
            "Checking...",
            lambda: updater.check_for_updates(__version__),
            self._handle_update_check,
            "Update check failed",
        )

    def _handle_update_check(self, check: updater.UpdateCheck) -> None:
        if check.update_available:
            install = messagebox.askyesno(
                "Update available",
                (
                    f"Version {check.latest.version} is available.\n"
                    f"You are running version {check.current_version}.\n\n"
                    "Download, verify, and install it for your user account now?"
                ),
                parent=self,
            )
            if install:
                self._install_checked_release(check.latest)
            return

        if updater.version_key(check.current_version) > updater.version_key(check.latest.version):
            messagebox.showinfo(
                "No update installed",
                (
                    f"This copy is version {check.current_version}, newer than the latest public "
                    f"release ({check.latest.version})."
                ),
                parent=self,
            )
            return

        if not updater.is_managed_runtime():
            install = messagebox.askyesno(
                "Set up managed updates",
                (
                    f"Version {check.current_version} is up to date.\n\n"
                    "This copy is not running from the managed installation. Install a managed copy "
                    "now so future releases can be installed from Settings?"
                ),
                parent=self,
            )
            if install:
                self._install_checked_release(check.latest)
            return

        messagebox.showinfo(
            "Up to date",
            f"Mint Background Switcher {check.current_version} is the latest public release.",
            parent=self,
        )

    def _install_checked_release(self, release: updater.ReleaseInfo) -> None:
        self._start_update_task(
            "Installing...",
            lambda: updater.install_release(release),
            self._handle_install_success,
            "Update failed",
        )

    def _handle_install_success(self, result: updater.InstallResult) -> None:
        self._handle_activation_success(
            result,
            title="Update installed",
            summary=f"Mint Background Switcher {result.record.version} is installed and activated.",
        )

    def _handle_rollback_success(self, result: updater.InstallResult) -> None:
        self._handle_activation_success(
            result,
            title="Rollback activated",
            summary=f"Mint Background Switcher was rolled back to version {result.record.version}.",
        )

    def _handle_activation_success(self, result: updater.InstallResult, *, title: str, summary: str) -> None:
        self._refresh_rollback_button()
        self._refresh_update_status()
        if result.restarted_background_modes:
            background_status = "The active MBS background process was restarted automatically."
        else:
            background_status = (
                "Any running tray or safe-start process will use the activated version after it is restarted "
                "or at your next login."
            )
        warning_text = ""
        if result.warnings:
            warning_text = "\n\n" + "\n".join(result.warnings)
        restart = messagebox.askyesno(
            title,
            (
                f"{summary}\n\n"
                f"{background_status}\n\n"
                "Restart Settings into the managed installation now?\n\n"
                "Unsaved profile changes in this Settings window will be lost."
                f"{warning_text}"
            ),
            parent=self,
        )
        if restart:
            self._restart_managed_settings()

    def _rollback_update(self) -> None:
        candidate = updater.rollback_candidate()
        if candidate is None:
            messagebox.showinfo(
                "No rollback available",
                "No previous managed version is available yet.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Roll back",
            f"Roll back to Mint Background Switcher {candidate.version}?",
            parent=self,
        ):
            return
        self._start_update_task(
            "Rolling Back...",
            updater.rollback_install,
            self._handle_rollback_success,
            "Rollback failed",
        )

    def _restart_managed_settings(self) -> None:
        try:
            updater.restart_settings()
        except Exception as exc:
            messagebox.showerror("Restart failed", str(exc), parent=self)
            return
        self.destroy()

    def _apply_next(self) -> None:
        if self._any_worker_busy():
            return
        # Snapshot the config before the save so a rejected switch can roll
        # back the activation and keep operating the previous profile.
        previous_config = self.config_data.to_dict()
        if not self._save_current(show_success=False):
            return
        profile_name = self.profile_var.get()
        self._apply_cancel.clear()
        self._set_apply_busy(True)

        def progress(count: int, path: str) -> None:
            self._operation_results.put(("apply-progress", (count, path), None))

        def run() -> None:
            try:
                result = switch_once(
                    profile_name,
                    cancelled=self._apply_cancel.is_set,
                    progress=progress,
                )
            except CollectionUnavailableError as exc:
                # The selected profile's collection is on an unresponsive
                # drive. Reject the switch; the poller rolls the activation
                # back so the previous profile keeps operating.
                self._operation_results.put(("apply-rejected", (previous_config, str(exc)), None))
            except Exception as exc:
                self._operation_results.put(("apply-done", None, exc))
            else:
                self._operation_results.put(("apply-done", result, None))

        worker = threading.Thread(target=run, name="mbs-settings-apply", daemon=False)
        self._apply_worker = worker
        try:
            worker.start()
        except Exception:
            self._apply_worker = None
            self._set_apply_busy(False)
            raise

    def _register_hotkeys(self) -> None:
        if self._any_worker_busy():
            return
        if not self._save_current(show_success=False):
            return
        summary = (
            ("Next", self.next_hotkey_var.get().strip() or DEFAULT_NEXT_HOTKEY),
            ("Pause/Resume", self.pause_hotkey_var.get().strip() or DEFAULT_PAUSE_HOTKEY),
            ("Black screen", self.hotkey_var.get().strip() or DEFAULT_BLACK_HOTKEY),
        )
        self._set_apply_busy(True)

        def run() -> None:
            try:
                register_all_cinnamon_hotkeys()
            except Exception as exc:
                self._operation_results.put(("hotkeys-done", None, exc))
            else:
                self._operation_results.put(("hotkeys-done", summary, None))

        worker = threading.Thread(target=run, name="mbs-settings-register-hotkeys", daemon=False)
        self._apply_worker = worker
        try:
            worker.start()
        except Exception:
            self._apply_worker = None
            self._set_apply_busy(False)
            raise

    def _black_screen(self) -> None:
        if self._any_worker_busy():
            return
        if not self._save_current(show_success=False):
            return
        profile_name = self.profile_var.get()
        self._apply_cancel.clear()
        self._set_apply_busy(True)

        def run() -> None:
            try:
                result = black_screen(profile_name, cancelled=self._apply_cancel.is_set)
            except Exception as exc:
                self._operation_results.put(("black-done", None, exc))
            else:
                self._operation_results.put(("black-done", result, None))

        worker = threading.Thread(target=run, name="mbs-settings-black-screen", daemon=False)
        self._apply_worker = worker
        try:
            worker.start()
        except Exception:
            self._apply_worker = None
            self._set_apply_busy(False)
            raise


def main() -> None:
    app = SettingsApp()
    app.mainloop()
