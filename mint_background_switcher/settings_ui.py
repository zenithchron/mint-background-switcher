"""Simple Tk settings editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .config import Config, Profile, load_config, save_config
from .monitor import Monitor, detect_monitors
from .service import black_screen, switch_once


SETTINGS_WINDOW_TARGET_WIDTH = 1120
SETTINGS_WINDOW_TARGET_HEIGHT = 760
SETTINGS_WINDOW_MIN_WIDTH = 980
SETTINGS_WINDOW_MIN_HEIGHT = 680
SETTINGS_WINDOW_SCREEN_MARGIN_X = 80
SETTINGS_WINDOW_SCREEN_MARGIN_Y = 100


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
        self.title("Mint Background Switcher Settings")
        self.config_data: Config = load_config()
        self.profile_var = tk.StringVar(value=self.config_data.active_profile)
        self.interval_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar()
        self.hotkey_var = tk.StringVar()
        self.desktop_var = tk.StringVar()
        self.effect_var = tk.StringVar()
        self.monitor_folder_var = tk.StringVar()
        self.monitor_folders_data: dict[str, list[str]] = {}
        self.detected_monitors = detect_monitors()
        self._build()
        self._load_profile(self.profile_var.get())
        self._set_initial_window_geometry()

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
        ttk.Button(top, text="New", command=self._new_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Rename", command=self._rename_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Delete", command=self._delete_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="Save", command=self._save_current).pack(side=tk.RIGHT, padx=2)

        form = ttk.LabelFrame(root, text="Profile settings", padding=10)
        form.pack(fill=tk.X, pady=8)
        ttk.Label(form, text="Interval minutes:").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.interval_var, width=10).grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(form, text="Mode:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        ttk.OptionMenu(form, self.mode_var, "shared", "shared", "same", "per-monitor", "span").grid(row=0, column=3, sticky="w", padx=5)
        ttk.Checkbutton(form, text="Scan folders recursively", variable=self.recursive_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Label(form, text="Black screen hotkey:").grid(row=1, column=2, sticky="w", padx=(20, 0))
        ttk.Entry(form, textvariable=self.hotkey_var, width=22).grid(row=1, column=3, sticky="w", padx=5)
        ttk.Label(form, text="Desktop:").grid(row=2, column=0, sticky="w")
        ttk.OptionMenu(form, self.desktop_var, "auto", "auto", "cinnamon", "gnome", "mate", "xfce").grid(row=2, column=1, sticky="w", padx=5)
        ttk.Label(form, text="Effect:").grid(row=2, column=2, sticky="w", padx=(20, 0))
        ttk.OptionMenu(form, self.effect_var, "none", "none", "grayscale").grid(row=2, column=3, sticky="w", padx=5)

        folders = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        folders.pack(fill=tk.BOTH, expand=True, pady=8)

        shared_frame = ttk.LabelFrame(folders, text="Shared folders / span folders", padding=8)
        self.shared_text = tk.Text(shared_frame, height=12, width=40)
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
                "Click Add per-monitor folder, choose a folder, then pick the screen it should appear on.\n"
                "Current screens: " + (current_monitors or "none detected")
            ),
            justify=tk.LEFT,
        ).pack(anchor="w")
        ttk.Button(monitor_frame, text="Add per-monitor folder...", command=self._add_monitor_folder_from_root).pack(
            anchor="w", pady=(4, 2)
        )
        ttk.Button(monitor_frame, text="Remove per-monitor folder...", command=self._remove_monitor_folder_from_dialog).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(monitor_frame, text="Current assignments:").pack(anchor="w", pady=(6, 0))
        self.monitor_text = tk.Text(monitor_frame, height=12, width=48)
        self.monitor_text.pack(fill=tk.BOTH, expand=True)
        folders.add(monitor_frame, weight=1)

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Apply Next Now", command=self._apply_next).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="Black Screen", command=self._black_screen).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=3)

    def _load_profile(self, name: str) -> None:
        profile = self.config_data.get_profile(name)
        self.interval_var.set(str(profile.interval_minutes))
        self.mode_var.set(profile.mode)
        self.recursive_var.set(profile.recursive)
        self.hotkey_var.set(profile.black_hotkey)
        self.desktop_var.set(profile.desktop)
        self.effect_var.set(profile.effect)
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
        )

    def _save_current(self, show_success: bool = True) -> bool:
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

    def _apply_next(self) -> None:
        if not self._save_current(show_success=False):
            return
        try:
            result = switch_once(self.profile_var.get())
            messagebox.showinfo("Applied", f"Generated {result.wallpaper}")
        except Exception as exc:
            messagebox.showerror("Apply failed", str(exc))

    def _black_screen(self) -> None:
        if not self._save_current(show_success=False):
            return
        try:
            result = black_screen(self.profile_var.get())
            messagebox.showinfo("Black screen", f"Generated {result.wallpaper}; rotation is paused.")
        except Exception as exc:
            messagebox.showerror("Black screen failed", str(exc))


def main() -> None:
    app = SettingsApp()
    app.mainloop()
