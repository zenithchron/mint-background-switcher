"""Optional GTK/AppIndicator tray icon."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import subprocess
import sys
import threading
import time

from .autostart import disable_autostart, enable_autostart
from .config import load_config, save_config
from .hotkeys import source_wrapper_argv
from .service import SwitchCancelled, black_screen, pause, switch_once
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


class RotationRunner:
    """Run one live rotation off the GTK thread and coalesce duplicate requests."""

    def __init__(
        self,
        idle_add: Callable[..., object],
        *,
        operation: Callable[..., object] = switch_once,
        error_handler: Callable[[BaseException], object] | None = None,
    ) -> None:
        self._idle_add = idle_add
        self._operation = operation
        self._error_handler = error_handler or (lambda _error: None)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._pending: tuple[str | None, bool] | None = None
        self._actions: deque[Callable[[], object]] = deque()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None

    def request(self, profile_name: str | None = None, *, clear_black: bool = True) -> bool:
        with self._lock:
            if self._thread is not None:
                self._pending = (profile_name, clear_black)
                return False
            self._start_locked(profile_name, clear_black)
            return True

    def _start_locked(self, profile_name: str | None, clear_black: bool) -> None:
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run,
            args=(profile_name, clear_black, cancel_event, None),
            name="mbs-wallpaper-rotation",
            daemon=False,
        )
        self._cancel_event = cancel_event
        self._thread = thread
        self._last_thread = thread
        thread.start()

    def submit(self, action: Callable[[], object]) -> bool:
        """Serialize a non-rotation state action with current and pending rotations."""

        with self._lock:
            if self._thread is not None:
                self._actions.append(action)
                return False
            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(None, True, cancel_event, action),
                name="mbs-tray-action",
                daemon=False,
            )
            self._cancel_event = cancel_event
            self._thread = thread
            self._last_thread = thread
            thread.start()
            return True

    def _run(
        self,
        profile_name: str | None,
        clear_black: bool,
        cancel_event: threading.Event,
        action: Callable[[], object] | None,
    ) -> None:
        current = (profile_name, clear_black)
        current_action = action
        while True:
            try:
                if current_action is None:
                    self._operation(
                        current[0],
                        clear_black=current[1],
                        cancelled=cancel_event.is_set,
                    )
                else:
                    current_action()
            except BaseException as exc:
                expected_cancel = current_action is None and (
                    cancel_event.is_set() or isinstance(exc, SwitchCancelled)
                )
                if not expected_cancel:
                    self._idle_add(self._deliver_error, exc)

            with self._lock:
                if self._actions:
                    current_action = self._actions.popleft()
                    cancel_event = threading.Event()
                    self._cancel_event = cancel_event
                    continue
                pending = self._pending
                self._pending = None
                if pending is None:
                    self._cancel_event = None
                    self._thread = None
                    break
                current = pending
                current_action = None
                cancel_event = threading.Event()
                self._cancel_event = cancel_event
        self._idle_add(self._completed)

    def _deliver_error(self, error: BaseException) -> bool:
        self._error_handler(error)
        return False

    def _completed(self) -> bool:
        return False

    def cancel(self) -> None:
        with self._lock:
            self._pending = None
            if self._cancel_event is not None:
                self._cancel_event.set()

    def wait(self, *, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                thread = self._thread or self._last_thread
            if thread is None or thread is threading.current_thread():
                return
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
            if not thread.is_alive():
                with self._lock:
                    if self._last_thread is thread:
                        self._last_thread = None
                return
            if deadline is not None and time.monotonic() >= deadline:
                return


class TrayApp:
    def __init__(self) -> None:
        self.Gtk, self.GLib, self.AppIndicator = _load_gtk()
        icon_name = choose_tray_icon(self.Gtk)
        self.timer_id: int | None = None
        self.rotation_runner = RotationRunner(self.GLib.idle_add, error_handler=self._report_error)
        self._settings_process: subprocess.Popen | None = None
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
            self.rotation_runner.request()
        self._schedule_timer()
        return False

    def _next(self, *_):
        self.rotation_runner.request()

    def _pause(self, *_):
        self.rotation_runner.cancel()
        self._run_action(pause)

    def _resume(self, *_):
        self.rotation_runner.request(clear_black=True)

    def _black(self, *_):
        self.rotation_runner.cancel()
        self._run_action(black_screen)

    def _profile(self, _item, profile_name: str):
        cfg = load_config()
        cfg.active_profile = profile_name
        save_config(cfg)
        self.rotation_runner.request(profile_name, clear_black=True)
        self._schedule_timer()

    def _settings(self, *_):
        if self._settings_process is not None and self._settings_process.poll() is None:
            return
        try:
            self._settings_process = subprocess.Popen(
                source_wrapper_argv() + ["settings"],
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            self._report_error(exc)
            return
        self.GLib.timeout_add_seconds(1, self._poll_settings)

    def _poll_settings(self) -> bool:
        if self._settings_process is not None and self._settings_process.poll() is None:
            return True
        self._settings_process = None
        self._build_menu()
        self._schedule_timer()
        return False

    def _report_error(self, error: BaseException) -> bool:
        print(f"Mint Background Switcher tray error: {error}", file=sys.stderr, flush=True)
        return False

    def _run_action(self, action: Callable[[], object]) -> None:
        self.rotation_runner.submit(action)

    def _quit(self, *_):
        if self.timer_id:
            self.GLib.source_remove(self.timer_id)
        self.rotation_runner.cancel()
        self.Gtk.main_quit()

    def run(self) -> None:
        self.Gtk.main()


def main() -> None:
    TrayApp().run()
