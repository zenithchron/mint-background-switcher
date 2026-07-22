"""Simple Tk settings editor."""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from . import APP_NAME, __version__, updater
from .config import EFFECT_CHOICES, Config, Profile, load_config, save_config
from .monitor import Monitor, detect_monitors
from .service import SwitchCancelled, black_screen, save_current_wallpaper, switch_once
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
        self.interval_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar()
        self.hotkey_var = tk.StringVar()
        self.desktop_var = tk.StringVar()
        self.effect_var = tk.StringVar()
        self.bar_color_var = tk.StringVar()
        self.monitor_folder_var = tk.StringVar()
        self.update_status_var = tk.StringVar()
        working_directory = configured_working_directory(self.config_data)
        self.working_directory_var = tk.StringVar(value=str(working_directory))
        self.working_status_var = tk.StringVar(
            value=f"Active: {working_directory} — source images remain in their original folders."
        )
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
        self._operation_results: queue.Queue[tuple[str, Any, Exception | None]] = queue.Queue()
        self.detected_monitors = detect_monitors()
        self._build()
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
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Profile:").pack(side=tk.LEFT)
        self.profile_combo = ttk.Combobox(top, textvariable=self.profile_var, values=sorted(self.config_data.profiles), state="readonly")
        self.profile_combo.pack(side=tk.LEFT, padx=5)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._load_profile(self.profile_var.get()))
        self.profile_new_button = ttk.Button(top, text="New", command=self._new_profile)
        self.profile_new_button.pack(side=tk.LEFT, padx=2)
        self.profile_rename_button = ttk.Button(top, text="Rename", command=self._rename_profile)
        self.profile_rename_button.pack(side=tk.LEFT, padx=2)
        self.profile_delete_button = ttk.Button(top, text="Delete", command=self._delete_profile)
        self.profile_delete_button.pack(side=tk.LEFT, padx=2)
        self.profile_save_button = ttk.Button(top, text="Save", command=self._save_current)
        self.profile_save_button.pack(side=tk.RIGHT, padx=2)

        form = ttk.LabelFrame(root, text="Profile settings", padding=10)
        form.pack(fill=tk.X, pady=8)
        ttk.Label(form, text="Interval minutes:").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.interval_var, width=10).grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(form, text="Mode:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.mode_menu = ttk.OptionMenu(
            form,
            self.mode_var,
            "shared",
            "shared",
            "same",
            "montage",
            "postcard",
            "per-monitor",
            "span",
        )
        self.mode_menu.grid(row=0, column=3, sticky="w", padx=5)
        ttk.Checkbutton(form, text="Scan folders recursively", variable=self.recursive_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Label(form, text="Black screen hotkey:").grid(row=1, column=2, sticky="w", padx=(20, 0))
        ttk.Entry(form, textvariable=self.hotkey_var, width=22).grid(row=1, column=3, sticky="w", padx=5)
        ttk.Label(form, text="Desktop:").grid(row=2, column=0, sticky="w")
        ttk.OptionMenu(form, self.desktop_var, "auto", "auto", "cinnamon", "gnome", "mate", "xfce").grid(row=2, column=1, sticky="w", padx=5)
        ttk.Label(form, text="Effect:").grid(row=2, column=2, sticky="w", padx=(20, 0))
        self.effect_menu = ttk.OptionMenu(form, self.effect_var, EFFECT_CHOICES[0], *EFFECT_CHOICES)
        self.effect_menu.grid(row=2, column=3, sticky="w", padx=5)
        ttk.Label(form, text="Letterbox bars:").grid(row=3, column=0, sticky="w", pady=(5, 0))
        ttk.OptionMenu(form, self.bar_color_var, "black", "black", "auto").grid(row=3, column=1, sticky="w", padx=5, pady=(5, 0))

        folders = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        folders.pack(fill=tk.BOTH, expand=True, pady=8)

        shared_frame = ttk.LabelFrame(folders, text="Shared folders / span folders", padding=8)
        self.shared_text = tk.Text(shared_frame, height=6, width=40)
        self.shared_text.pack(fill=tk.BOTH, expand=True)
        shared_buttons = ttk.Frame(shared_frame)
        shared_buttons.pack(fill=tk.X, pady=4)
        ttk.Button(shared_buttons, text="Add folder...", command=self._add_shared_folder).pack(side=tk.LEFT)
        ttk.Button(shared_buttons, text="Browse hard drives...", command=self._add_shared_folder_from_root).pack(side=tk.LEFT, padx=4)
        folders.add(shared_frame, weight=1)

        monitor_frame = ttk.LabelFrame(folders, text="Per-monitor folders", padding=8)
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
        folders.add(monitor_frame, weight=1)

        working = ttk.LabelFrame(root, text="Working files", padding=(8, 5))
        working.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(working, text="Generated wallpapers and library index:").grid(row=0, column=0, sticky="w")
        self.working_directory_entry = ttk.Entry(working, textvariable=self.working_directory_var, width=19)
        self.working_directory_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.working_browse_button = ttk.Button(working, text="Browse...", command=self._browse_working_directory)
        self.working_browse_button.grid(row=0, column=2, padx=2)
        self.working_create_button = ttk.Button(working, text="Create Folder...", command=self._create_working_directory)
        self.working_create_button.grid(row=0, column=3, padx=2)
        self.working_use_button = ttk.Button(working, text="Use Folder...", command=self._use_working_directory)
        self.working_use_button.grid(row=0, column=4, padx=2)
        self.working_cancel_button = ttk.Button(working, text="Cancel Move", command=self._cancel_working_migration)
        self.working_cancel_button.grid(row=0, column=5, padx=(2, 0))
        self.working_cancel_button.state(["disabled"])
        ttk.Label(working, textvariable=self.working_status_var, anchor="w").grid(
            row=1,
            column=0,
            columnspan=6,
            sticky="ew",
            pady=(4, 0),
        )
        working.columnconfigure(1, weight=1)

        maintenance = ttk.Frame(root)
        maintenance.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(maintenance, text="Application updates:").pack(side=tk.LEFT, padx=(3, 6))
        self.update_button = ttk.Button(maintenance, text="Check for Updates...", command=self._check_for_updates)
        self.update_button.pack(side=tk.LEFT, padx=3)
        self.rollback_button = ttk.Button(maintenance, text="Roll Back...", command=self._rollback_update)
        self.rollback_button.pack(side=tk.LEFT, padx=3)
        ttk.Label(maintenance, textvariable=self.update_status_var).pack(side=tk.LEFT, padx=(8, 3))

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X)
        self.apply_button = ttk.Button(bottom, text="Apply Next Now", command=self._apply_next)
        self.apply_button.pack(side=tk.LEFT, padx=3)
        self.black_button = ttk.Button(bottom, text="Black Screen", command=self._black_screen)
        self.black_button.pack(side=tk.LEFT, padx=3)
        self.export_button = ttk.Button(bottom, text="Save Current Wallpaper...", command=self._export_current_wallpaper)
        self.export_button.pack(side=tk.LEFT, padx=3)
        self.close_button = ttk.Button(bottom, text="Close", command=self._request_close)
        self.close_button.pack(side=tk.RIGHT, padx=3)
        self.about_button = ttk.Button(bottom, text="About", command=self._show_about)
        self.about_button.pack(side=tk.RIGHT, padx=3)
        ttk.Label(bottom, text=f"Version {__version__}").pack(side=tk.RIGHT, padx=(3, 10))
        self._refresh_rollback_button()
        self._refresh_update_status()

    def _load_profile(self, name: str) -> None:
        profile = self.config_data.get_profile(name)
        self.interval_var.set(str(profile.interval_minutes))
        self.mode_var.set(profile.mode)
        self.recursive_var.set(profile.recursive)
        self.hotkey_var.set(profile.black_hotkey)
        self.desktop_var.set(profile.desktop)
        self.effect_var.set(profile.effect)
        self.bar_color_var.set(profile.bar_color)
        self.shared_text.delete("1.0", tk.END)
        self.shared_text.insert(tk.END, "\n".join(profile.shared_folders))
        self._write_monitor_folders({monitor: list(paths) for monitor, paths in profile.monitor_folders.items()})

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
        return Profile(
            name=name,
            interval_minutes=float(self.interval_var.get()),
            mode=self.mode_var.get(),
            recursive=self.recursive_var.get(),
            shared_folders=[p.strip() for p in self.shared_text.get("1.0", tk.END).splitlines() if p.strip()],
            monitor_folders={monitor: list(paths) for monitor, paths in self._current_monitor_folders().items()},
            black_hotkey=self.hotkey_var.get().strip() or "<Primary><Alt>b",
            desktop=self.desktop_var.get(),
            effect=self.effect_var.get(),
            bar_color=self.bar_color_var.get(),
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
        existing = [line.strip() for line in text_widget.get("1.0", tk.END).splitlines() if line.strip()]
        if value in existing:
            return
        current = text_widget.get("1.0", tk.END).strip()
        if current:
            text_widget.insert(tk.END, "\n" + value)
        else:
            text_widget.insert(tk.END, value)

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
        )

    def _refresh_worker_controls(self) -> None:
        busy = self._any_worker_busy()
        self.close_button.state(["disabled"] if busy else ["!disabled"])
        self.apply_button.configure(text="Applying..." if self._apply_busy else "Apply Next Now")
        self.apply_button.state(["disabled"] if busy else ["!disabled"])
        for button in (
            self.profile_new_button,
            self.profile_rename_button,
            self.profile_delete_button,
            self.profile_save_button,
            self.working_browse_button,
            self.working_create_button,
            self.working_use_button,
            self.black_button,
            self.export_button,
        ):
            button.state(["disabled"] if busy else ["!disabled"])
        self.working_cancel_button.state(["!disabled"] if self._migration_busy else ["disabled"])
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
            self.working_status_var.set(
                f"Active: {current} — source images remain in their original folders."
            )
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
                        self.working_status_var.set(
                            f"Active: {result.destination} — source images remain in their original folders."
                        )
                        messagebox.showinfo(
                            "Working folder changed",
                            (
                                f"MBS now uses:\n{result.destination}\n\n"
                                f"Previous generated files were retained at:\n{result.source}"
                            ),
                            parent=self,
                        )
                    continue
                if kind == "apply-progress":
                    count, _path = result
                    self.apply_button.configure(text=f"Scanning... {count}")
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
                        title = "Black screen" if kind == "black-done" else "Applied"
                        detail = (
                            f"Generated {result.wallpaper}; rotation is paused."
                            if kind == "black-done"
                            else f"Generated {result.wallpaper}"
                        )
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
        if self._optional_attr("_migration_busy", False) or self._optional_attr("_apply_busy", False):
            if self._optional_attr("_migration_busy", False):
                self._migration_cancel.set()
            if self._optional_attr("_apply_busy", False):
                self._apply_cancel.set()
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
        warning_text = ""
        if result.warnings:
            warning_text = "\n\n" + "\n".join(result.warnings)
        restart = messagebox.askyesno(
            title,
            (
                f"{summary}\n\n"
                "Restart Settings into the managed installation now? The running tray process will "
                "use the activated version after it is restarted or at your next login.\n\n"
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
