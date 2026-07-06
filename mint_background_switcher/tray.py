"""Optional GTK/AppIndicator tray icon."""

from __future__ import annotations

import sys

from .autostart import disable_autostart, enable_autostart
from .config import load_config, save_config
from .service import black_screen, pause, resume, switch_once
from .state import load_state

TRAY_ICON_CANDIDATES = (
    "view-preview-symbolic",          # eye-shaped, rendered monochrome by Mint themes
    "camera-photo-symbolic",
    "image-x-generic-symbolic",
    "preferences-desktop-wallpaper-symbolic",
    "preferences-desktop-wallpaper",
)


def choose_tray_icon(Gtk) -> str:
    """Pick a theme icon that should render like the other white tray icons."""
    try:
        theme = Gtk.IconTheme.get_default()
        if theme is not None:
            for icon_name in TRAY_ICON_CANDIDATES:
                if theme.has_icon(icon_name):
                    return icon_name
    except Exception:
        pass
    return TRAY_ICON_CANDIDATES[0]


def _load_gtk():
    try:
        import gi  # type: ignore
        gi.require_version("Gtk", "3.0")
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore
        except Exception:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as AppIndicator  # type: ignore
        from gi.repository import GLib, Gtk  # type: ignore
        return Gtk, GLib, AppIndicator
    except Exception as exc:
        raise RuntimeError(
            "Tray mode needs GTK/AppIndicator Python bindings. On Mint/Ubuntu try: "
            "sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1"
        ) from exc


class TrayApp:
    def __init__(self) -> None:
        self.Gtk, self.GLib, self.AppIndicator = _load_gtk()
        icon_name = choose_tray_icon(self.Gtk)
        self.timer_id: int | None = None
        self.indicator = self.AppIndicator.Indicator.new(
            "mint-background-switcher",
            icon_name,
            self.AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        try:
            self.indicator.set_icon_full(icon_name, "Mint Background Switcher")
        except Exception:
            pass
        self.indicator.set_status(self.AppIndicator.IndicatorStatus.ACTIVE)
        self._build_menu()
        self._schedule_timer()

    def _build_menu(self) -> None:
        Gtk = self.Gtk
        menu = Gtk.Menu()
        item_next = Gtk.MenuItem(label="Next")
        item_next.connect("activate", self._next)
        menu.append(item_next)

        item_pause = Gtk.MenuItem(label="Pause")
        item_pause.connect("activate", self._pause)
        menu.append(item_pause)

        item_resume = Gtk.MenuItem(label="Resume")
        item_resume.connect("activate", self._resume)
        menu.append(item_resume)

        item_black = Gtk.MenuItem(label="Black Screen")
        item_black.connect("activate", self._black)
        menu.append(item_black)

        profiles_item = Gtk.MenuItem(label="Profiles")
        profiles_menu = Gtk.Menu()
        cfg = load_config()
        for profile_name in sorted(cfg.profiles):
            pitem = Gtk.MenuItem(label=profile_name)
            pitem.connect("activate", self._profile, profile_name)
            profiles_menu.append(pitem)
        profiles_item.set_submenu(profiles_menu)
        menu.append(profiles_item)

        item_settings = Gtk.MenuItem(label="Open Settings")
        item_settings.connect("activate", self._settings)
        menu.append(item_settings)

        item_autostart = Gtk.MenuItem(label="Enable Safe Start at Login")
        item_autostart.connect("activate", lambda *_: enable_autostart())
        menu.append(item_autostart)

        item_autostart_off = Gtk.MenuItem(label="Disable Start at Login")
        item_autostart_off.connect("activate", lambda *_: disable_autostart())
        menu.append(item_autostart_off)

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._quit)
        menu.append(item_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _schedule_timer(self) -> None:
        if self.timer_id:
            self.GLib.source_remove(self.timer_id)
        cfg = load_config()
        interval_seconds = int(max(cfg.get_profile().interval_minutes * 60, 5))
        self.timer_id = self.GLib.timeout_add_seconds(interval_seconds, self._timer_tick)

    def _timer_tick(self):
        state = load_state()
        if not state.paused and not state.black_screen:
            try:
                switch_once()
            except Exception as exc:
                print(f"Mint Background Switcher tray error: {exc}", file=sys.stderr, flush=True)
        self._schedule_timer()
        return False

    def _next(self, *_):
        switch_once()

    def _pause(self, *_):
        pause()

    def _resume(self, *_):
        resume()

    def _black(self, *_):
        black_screen()

    def _profile(self, _item, profile_name: str):
        cfg = load_config()
        cfg.active_profile = profile_name
        save_config(cfg)
        resume(profile_name)
        self._schedule_timer()

    def _settings(self, *_):
        try:
            from .settings_ui import main as settings_main
        except ImportError as exc:
            print("Settings editor requires Tkinter. On Mint/Ubuntu install python3-tk.", file=sys.stderr)
            return

        settings_main()
        self._build_menu()
        self._schedule_timer()

    def _quit(self, *_):
        if self.timer_id:
            self.GLib.source_remove(self.timer_id)
        self.Gtk.main_quit()

    def run(self) -> None:
        self.Gtk.main()


def main() -> None:
    TrayApp().run()
