import gc
import os
import threading
import time
from types import SimpleNamespace

import pytest

from mint_background_switcher import settings_ui
from mint_background_switcher.monitor import Monitor


@pytest.fixture(autouse=True)
def _collect_destroyed_tk_objects_on_main_thread():
    """Keep repeated test-only Tk roots from being finalized by a worker thread."""

    yield
    gc.collect()


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Text:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def insert(self, _index, text):
        self.value += text

    def delete(self, *_args):
        self.value = ""


class _Combo:
    def configure(self, **_kwargs):
        pass


def _pump_until(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    assert predicate()


def test_settings_window_geometry_prefers_roomy_desktop_size():
    width, height, x, y, min_width, min_height = settings_ui._settings_window_geometry(2560, 1440, 850, 600)

    assert (width, height) == (settings_ui.SETTINGS_WINDOW_TARGET_WIDTH, settings_ui.SETTINGS_WINDOW_TARGET_HEIGHT)
    assert (min_width, min_height) == (settings_ui.SETTINGS_WINDOW_MIN_WIDTH, settings_ui.SETTINGS_WINDOW_MIN_HEIGHT)
    assert x == (2560 - width) // 2
    assert y == (1440 - height) // 3


def test_settings_window_geometry_centers_inside_selected_monitor():
    width, _height, x, _y, _min_width, _min_height = settings_ui._settings_window_geometry(
        5120,
        1440,
        942,
        595,
        monitor_rect=(0, 0, 2560, 1440),
    )

    assert x == 720
    assert x < 2560
    assert x + width < 2560


def test_settings_window_monitor_rect_uses_pointer_then_primary_then_leftmost():
    left = Monitor("Left", 2560, 1440, 0, 0, logical_width=2560, logical_height=1440)
    right = Monitor("Right", 2560, 1440, 2560, 0, logical_width=2560, logical_height=1440, logical_x=2560)
    primary = Monitor(
        "Primary",
        2560,
        1440,
        2560,
        0,
        primary=True,
        logical_width=2560,
        logical_height=1440,
        logical_x=2560,
    )

    assert settings_ui._monitor_window_rect(5120, 1440, [left, right], 3000, 100) == (2560, 0, 2560, 1440)
    assert settings_ui._monitor_window_rect(5120, 1440, [left, primary], None, None) == (2560, 0, 2560, 1440)
    assert settings_ui._monitor_window_rect(5120, 1440, [right, left], None, None) == (0, 0, 2560, 1440)


def test_settings_window_geometry_keeps_1024x768_screens_usable():
    width, height, x, y, min_width, min_height = settings_ui._settings_window_geometry(1024, 768, 1200, 900)

    assert width == 944
    assert height == 668
    assert (min_width, min_height) == (944, 668)
    assert x == 40
    assert y == 33


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_effect_menu_exposes_vignette_and_is_visible(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        menu = app.nametowidget(app.effect_menu["menu"])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        saved_effects = []
        messages = []
        monkeypatch.setattr(
            settings_ui,
            "save_config",
            lambda config: saved_effects.append(config.get_profile("Default").effect),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )

        assert "vignette" in labels
        assert app.effect_menu.winfo_ismapped()
        assert app.effect_menu.winfo_width() > 1
        menu.invoke(labels.index("vignette"))
        assert app.effect_var.get() == "vignette"
        assert app._save_current() is True
        assert saved_effects == ["vignette"]
        assert messages and messages[-1][0] == "Saved"
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_effect_menu_exposes_calendar_and_applies_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        menu = app.nametowidget(app.effect_menu["menu"])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        saved_effects = []
        applied_profiles = []
        messages = []
        monkeypatch.setattr(
            settings_ui,
            "save_config",
            lambda config: saved_effects.append(config.get_profile("Default").effect),
        )
        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda profile, **_kwargs: applied_profiles.append(profile)
            or SimpleNamespace(wallpaper="/tmp/calendar-preview.png"),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )

        assert "calendar" in labels
        assert app.effect_menu.winfo_ismapped()
        assert app.effect_menu.winfo_width() > 1
        menu.invoke(labels.index("calendar"))
        assert app.effect_var.get() == "calendar"
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_effects == ["calendar"]
        assert applied_profiles == ["Default"]
        assert messages and messages[-1][0] == "Applied"
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_effect_menu_exposes_invert_and_applies_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        menu = app.nametowidget(app.effect_menu["menu"])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        saved_effects = []
        applied_profiles = []
        messages = []
        errors = []
        monkeypatch.setattr(
            settings_ui,
            "save_config",
            lambda config: saved_effects.append(config.get_profile("Default").effect),
        )
        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda profile, **_kwargs: applied_profiles.append(profile)
            or SimpleNamespace(wallpaper="invert-preview.png"),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showerror",
            lambda title, message, **_kwargs: errors.append((title, message)),
        )

        assert "invert" in labels
        assert app.effect_menu.winfo_ismapped()
        assert app.effect_menu.winfo_width() > 1
        menu.invoke(labels.index("invert"))
        assert app.effect_var.get() == "invert"
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_effects == ["invert"]
        assert applied_profiles == ["Default"]
        assert messages and messages[-1][0] == "Applied"

        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda _profile, **_kwargs: (_ for _ in ()).throw(RuntimeError("invert preview failed")),
        )
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_effects == ["invert", "invert"]
        assert errors == [("Apply failed", "invert preview failed")]
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_mode_menu_exposes_montage_and_applies_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        menu = app.nametowidget(app.mode_menu["menu"])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        saved_modes = []
        applied_profiles = []
        messages = []
        errors = []
        monkeypatch.setattr(
            settings_ui,
            "save_config",
            lambda config: saved_modes.append(config.get_profile("Default").mode),
        )
        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda profile, **_kwargs: applied_profiles.append(profile)
            or SimpleNamespace(wallpaper="/tmp/montage-preview.png"),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showerror",
            lambda title, message, **_kwargs: errors.append((title, message)),
        )

        assert "montage" in labels
        assert app.mode_menu.winfo_ismapped()
        assert app.mode_menu.winfo_width() > 1
        menu.invoke(labels.index("montage"))
        assert app.mode_var.get() == "montage"
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_modes == ["montage"]
        assert applied_profiles == ["Default"]
        assert messages and messages[-1][0] == "Applied"

        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda _profile, **_kwargs: (_ for _ in ()).throw(RuntimeError("preview failed")),
        )
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_modes == ["montage", "montage"]
        assert errors == [("Apply failed", "preview failed")]
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_black_screen_worker_keeps_tk_responsive_and_reports_on_tk_thread(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    release = threading.Event()
    try:
        monkeypatch.setattr(app, "_save_current", lambda show_success=True: True)
        started = threading.Event()
        worker_threads = []
        messages = []
        errors = []
        main_thread = threading.get_ident()

        def delayed_black(_profile, *, cancelled):
            worker_threads.append(threading.get_ident())
            started.set()
            while not release.wait(0.01):
                if cancelled():
                    raise settings_ui.SwitchCancelled("cancelled")
            return SimpleNamespace(wallpaper="/tmp/black.png")

        monkeypatch.setattr(settings_ui, "black_screen", delayed_black)
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append(
                (title, message, threading.get_ident())
            ),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showerror",
            lambda title, message, **_kwargs: errors.append((title, message)),
        )

        app._black_screen()
        assert started.wait(2)
        heartbeat = []
        app.after(20, lambda: heartbeat.append(time.monotonic()))
        _pump_until(app, lambda: bool(heartbeat), timeout=1)
        assert app._apply_busy is True
        assert len(worker_threads) == 1
        assert worker_threads[0] != main_thread

        release.set()
        _pump_until(app, lambda: not app._apply_busy)
        assert errors == []
        assert messages[-1][0] == "Black screen"
        assert messages[-1][2] == main_thread
        assert app._apply_worker is None
    finally:
        release.set()
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_black_screen_close_requests_cancellation_and_joins_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        monkeypatch.setattr(app, "_save_current", lambda show_success=True: True)
        started = threading.Event()
        cancellation_seen = threading.Event()
        errors = []

        def cancellable_black(_profile, *, cancelled):
            started.set()
            while True:
                if cancelled():
                    cancellation_seen.set()
                    raise settings_ui.SwitchCancelled("cancelled")
                time.sleep(0.01)

        monkeypatch.setattr(settings_ui, "black_screen", cancellable_black)
        monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showerror",
            lambda title, message, **_kwargs: errors.append((title, message)),
        )

        app._black_screen()
        assert started.wait(2)
        app._request_close()
        _pump_until(app, lambda: not app._apply_busy)

        assert cancellation_seen.is_set()
        assert errors == []
        assert app._apply_worker is None
        assert app.winfo_exists()
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_mode_menu_exposes_postcard_and_applies_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        menu = app.nametowidget(app.mode_menu["menu"])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        saved_modes = []
        applied_profiles = []
        messages = []
        errors = []
        monkeypatch.setattr(
            settings_ui,
            "save_config",
            lambda config: saved_modes.append(config.get_profile("Default").mode),
        )
        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda profile, **_kwargs: applied_profiles.append(profile)
            or SimpleNamespace(wallpaper="/tmp/postcard-preview.png"),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showinfo",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )
        monkeypatch.setattr(
            settings_ui.messagebox,
            "showerror",
            lambda title, message, **_kwargs: errors.append((title, message)),
        )

        assert "postcard" in labels
        assert app.mode_menu.winfo_ismapped()
        assert app.mode_menu.winfo_width() > 1
        menu.invoke(labels.index("postcard"))
        assert app.mode_var.get() == "postcard"
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_modes == ["postcard"]
        assert applied_profiles == ["Default"]
        assert messages and messages[-1][0] == "Applied"

        monkeypatch.setattr(
            settings_ui,
            "switch_once",
            lambda _profile, **_kwargs: (_ for _ in ()).throw(RuntimeError("postcard preview failed")),
        )
        app._apply_next()
        _pump_until(app, lambda: not app._apply_busy)
        assert saved_modes == ["postcard", "postcard"]
        assert errors == [("Apply failed", "postcard preview failed")]
    finally:
        app.destroy()


def test_save_current_returns_false_on_validation_failure(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda *_args: None)
    monkeypatch.setattr(settings_ui, "save_config", lambda _cfg: (_ for _ in ()).throw(AssertionError("should not save")))

    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "profile_var", _Var("P"))
    setattr(dummy, "interval_var", _Var("not-a-number"))
    setattr(dummy, "mode_var", _Var("shared"))
    setattr(dummy, "recursive_var", _Var(True))
    setattr(dummy, "hotkey_var", _Var("<Primary><Alt>b"))
    setattr(dummy, "desktop_var", _Var("auto"))
    setattr(dummy, "effect_var", _Var("none"))
    setattr(dummy, "bar_color_var", _Var("black"))
    setattr(dummy, "shared_text", _Text("/tmp/images"))
    setattr(dummy, "monitor_text", _Text(""))
    setattr(dummy, "config_data", settings_ui.Config(active_profile="P", profiles={}))
    setattr(dummy, "profile_combo", _Combo())

    assert settings_ui.SettingsApp._save_current(dummy, show_success=False) is False
    assert errors and errors[0][0] == "Save failed"


def test_apply_next_aborts_when_save_fails(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "profile_var", _Var("P"))
    setattr(dummy, "_save_current", lambda **_kwargs: False)
    monkeypatch.setattr(settings_ui, "switch_once", fail_if_called)

    settings_ui.SettingsApp._apply_next(dummy)

    assert called is False


def test_export_current_wallpaper_uses_png_dialog_and_service(monkeypatch, tmp_path):
    destination = tmp_path / "current-background.png"
    dialogs = []
    saves = []
    messages = []
    dummy = object.__new__(settings_ui.SettingsApp)

    monkeypatch.setattr(
        settings_ui.filedialog,
        "asksaveasfilename",
        lambda **kwargs: dialogs.append(kwargs) or str(destination),
    )
    monkeypatch.setattr(
        settings_ui,
        "save_current_wallpaper",
        lambda path, *, overwrite=False: saves.append((path, overwrite)) or destination,
    )
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )

    settings_ui.SettingsApp._export_current_wallpaper(dummy)

    assert dialogs[0]["parent"] is dummy
    assert dialogs[0]["defaultextension"] == ".png"
    assert dialogs[0]["initialfile"].endswith(".png")
    assert dialogs[0]["confirmoverwrite"] is False
    assert ("PNG image", "*.png") in dialogs[0]["filetypes"]
    assert saves == [(destination, False)]
    assert messages and messages[0][0] == "Wallpaper saved"
    assert str(destination) in messages[0][1]


def test_export_current_wallpaper_confirms_file_created_after_dialog(monkeypatch, tmp_path):
    destination = tmp_path / "raced.png"
    saves = []
    confirmations = []
    dummy = object.__new__(settings_ui.SettingsApp)

    def fake_save(path, *, overwrite=False):
        saves.append((path, overwrite))
        if not overwrite:
            destination.write_bytes(b"created after the dialog returned")
            raise FileExistsError(f"Destination already exists: {destination}")
        destination.write_bytes(b"replacement")
        return destination

    monkeypatch.setattr(settings_ui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination))
    monkeypatch.setattr(settings_ui, "save_current_wallpaper", fake_save)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: confirmations.append((title, message, kwargs)) or True,
    )
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda *_args, **_kwargs: None)

    settings_ui.SettingsApp._export_current_wallpaper(dummy)

    assert saves == [(destination, False), (destination, True)]
    assert confirmations and confirmations[0][0] == "Replace existing file?"
    assert str(destination) in confirmations[0][1]
    assert confirmations[0][2]["parent"] is dummy
    assert destination.read_bytes() == b"replacement"


def test_export_current_wallpaper_declining_overwrite_preserves_file(monkeypatch, tmp_path):
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"keep me")
    saves = []
    dummy = object.__new__(settings_ui.SettingsApp)

    def fake_save(path, *, overwrite=False):
        saves.append((path, overwrite))
        if overwrite:
            raise AssertionError("declining replacement must not force an overwrite")
        raise FileExistsError(f"Destination already exists: {destination}")

    monkeypatch.setattr(settings_ui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination))
    monkeypatch.setattr(settings_ui, "save_current_wallpaper", fake_save)
    monkeypatch.setattr(settings_ui.messagebox, "askyesno", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("declined replacement is not a save")),
    )

    settings_ui.SettingsApp._export_current_wallpaper(dummy)

    assert saves == [(destination, False)]
    assert destination.read_bytes() == b"keep me"


def test_export_current_wallpaper_cancel_is_side_effect_free(monkeypatch):
    dummy = object.__new__(settings_ui.SettingsApp)
    monkeypatch.setattr(settings_ui.filedialog, "asksaveasfilename", lambda **_kwargs: "")
    monkeypatch.setattr(
        settings_ui,
        "save_current_wallpaper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancel must not export")),
    )

    settings_ui.SettingsApp._export_current_wallpaper(dummy)


def test_export_current_wallpaper_reports_service_errors(monkeypatch, tmp_path):
    destination = tmp_path / "current.png"
    errors = []
    dummy = object.__new__(settings_ui.SettingsApp)
    monkeypatch.setattr(settings_ui.filedialog, "asksaveasfilename", lambda **_kwargs: str(destination))
    monkeypatch.setattr(
        settings_ui,
        "save_current_wallpaper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("nothing to save")),
    )
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showerror",
        lambda title, message, **kwargs: errors.append((title, message, kwargs)),
    )

    settings_ui.SettingsApp._export_current_wallpaper(dummy)

    assert errors and errors[0][0] == "Save current wallpaper failed"
    assert "nothing to save" in errors[0][1]


def test_about_dialog_reports_version_and_project(monkeypatch):
    messages = []
    dummy = object.__new__(settings_ui.SettingsApp)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )

    settings_ui.SettingsApp._show_about(dummy)

    assert messages and messages[0][0] == "About Mint Background Switcher"
    assert f"Version {settings_ui.__version__}" in messages[0][1]
    assert settings_ui.PROJECT_URL in messages[0][1]
    assert messages[0][2]["parent"] is dummy


def test_shared_hard_drive_browse_adds_unique_folder():
    calls = []

    def fake_ask_folder(**kwargs):
        calls.append(kwargs)
        return "/media/example/Photos"

    dummy = object.__new__(settings_ui.SettingsApp)
    shared_text = _Text("/tmp/example/Pictures")
    setattr(dummy, "shared_text", shared_text)
    setattr(dummy, "_ask_folder", fake_ask_folder)

    settings_ui.SettingsApp._add_shared_folder_from_root(dummy)
    settings_ui.SettingsApp._add_shared_folder_from_root(dummy)

    assert calls[0]["initialdir"] == "/"
    assert calls[0]["title"]
    assert shared_text.value.splitlines() == ["/tmp/example/Pictures", "/media/example/Photos"]


def test_monitor_folder_flow_browses_then_asks_for_screen():
    events = []
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("DP-1=/old/dp\nHDMI-1=/old/hdmi")
    setattr(dummy, "monitor_folder_var", _Var("DP-1"))
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "_ask_folder", lambda **_kwargs: events.append("folder") or "/mnt/wallpapers")
    setattr(dummy, "_choose_monitor_for_folder", lambda folder: events.append(("screen", folder)) or "HDMI-1")

    settings_ui.SettingsApp._add_monitor_folder_from_root(dummy)

    lines = monitor_text.value.splitlines()
    assert events == ["folder", ("screen", "/mnt/wallpapers")]
    assert "DP-1=/old/dp" in lines
    assert "HDMI-1=/old/hdmi;/mnt/wallpapers" in lines
    assert dummy.monitor_folder_var.get() == "HDMI-1"


def test_monitor_hard_drive_browse_shows_error_for_malformed_text(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("not-a-valid-monitor-line")
    setattr(dummy, "monitor_folder_var", _Var("HDMI-1"))
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "_ask_folder", lambda **_kwargs: "/mnt/wallpapers")
    setattr(dummy, "_choose_monitor_for_folder", lambda folder: "HDMI-1")

    settings_ui.SettingsApp._add_monitor_folder_from_root(dummy)

    assert errors and errors[0][0] == "Could not add folder"
    assert monitor_text.value == "not-a-valid-monitor-line"


def test_remove_monitor_folder_removes_only_selected_assignment():
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {"DP-1": ["/a", "/b"], "HDMI-1": ["/c"]})

    settings_ui.SettingsApp._remove_monitor_folder(dummy, "DP-1", "/a")

    assert dummy.monitor_folders_data == {"DP-1": ["/b"], "HDMI-1": ["/c"]}
    assert monitor_text.value.splitlines() == ["DP-1=/b", "HDMI-1=/c"]


def test_remove_monitor_folder_dialog_can_delete_last_assignment():
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {"DP-1": ["/a"], "HDMI-1": ["/c"]})
    setattr(dummy, "_choose_monitor_folder_to_remove", lambda: ("DP-1", "/a"))

    settings_ui.SettingsApp._remove_monitor_folder_from_dialog(dummy)

    assert dummy.monitor_folders_data == {"HDMI-1": ["/c"]}
    assert monitor_text.value.splitlines() == ["HDMI-1=/c"]


def test_remove_monitor_folder_dialog_shows_message_when_empty(monkeypatch):
    messages = []
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda title, message: messages.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {})

    assert settings_ui.SettingsApp._choose_monitor_folder_to_remove(dummy) is None
    assert messages and messages[0][0] == "No per-monitor folders"


def test_new_profile_prompts_for_name_and_saves(monkeypatch):
    saved = []
    loaded = []
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Default", profiles={"Default": settings_ui.Profile(name="Default")}))
    setattr(dummy, "profile_var", _Var("Default"))
    setattr(dummy, "profile_combo", _Combo())
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: "Travel")
    setattr(dummy, "_load_profile", lambda name: loaded.append(name))

    settings_ui.SettingsApp._new_profile(dummy)

    assert "Travel" in dummy.config_data.profiles
    assert dummy.config_data.active_profile == "Travel"
    assert dummy.profile_var.get() == "Travel"
    assert saved == ["Travel"]
    assert loaded == ["Travel"]


def test_rename_profile_preserves_current_form_settings_and_saves(monkeypatch):
    saved = []
    loaded = []
    errors = []
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    old_profile = settings_ui.Profile(
        name="Old",
        mode="shared",
        shared_folders=["/old-shared"],
        monitor_folders={"DP-1": ["/old"]},
        desktop="cinnamon",
    )
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Old", profiles={"Old": old_profile}))
    setattr(dummy, "profile_var", _Var("Old"))
    setattr(dummy, "profile_combo", _Combo())
    setattr(dummy, "interval_var", _Var("15"))
    setattr(dummy, "mode_var", _Var("per-monitor"))
    setattr(dummy, "recursive_var", _Var(False))
    setattr(dummy, "hotkey_var", _Var("<Primary><Alt>x"))
    setattr(dummy, "desktop_var", _Var("mate"))
    setattr(dummy, "effect_var", _Var("grayscale"))
    setattr(dummy, "bar_color_var", _Var("auto"))
    setattr(dummy, "shared_text", _Text("/new-shared\n"))
    setattr(dummy, "monitor_text", _Text(""))
    setattr(dummy, "monitor_folders_data", {"HDMI-1": ["/new-monitor"]})
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: "Travel")
    setattr(dummy, "_load_profile", lambda name: loaded.append(name))

    settings_ui.SettingsApp._rename_profile(dummy)

    assert errors == []
    assert "Old" not in dummy.config_data.profiles
    renamed = dummy.config_data.profiles["Travel"]
    assert renamed.name == "Travel"
    assert renamed.interval_minutes == 15.0
    assert renamed.mode == "per-monitor"
    assert renamed.recursive is False
    assert renamed.shared_folders == ["/new-shared"]
    assert renamed.monitor_folders == {"HDMI-1": ["/new-monitor"]}
    assert renamed.black_hotkey == "<Primary><Alt>x"
    assert renamed.desktop == "mate"
    assert renamed.effect == "grayscale"
    assert renamed.bar_color == "auto"
    assert dummy.profile_var.get() == "Travel"
    assert saved == ["Travel"]
    assert loaded == ["Travel"]


def test_rename_profile_cancel_has_no_save_side_effect(monkeypatch):
    saved = []
    dummy = object.__new__(settings_ui.SettingsApp)
    old_profile = settings_ui.Profile(name="Old", shared_folders=["/old"])
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Old", profiles={"Old": old_profile}))
    setattr(dummy, "profile_var", _Var("Old"))
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: None)
    setattr(dummy, "_save_current", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cancel should not save")))
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))

    settings_ui.SettingsApp._rename_profile(dummy)

    assert saved == []
    assert dummy.config_data.active_profile == "Old"
    assert dummy.config_data.profiles == {"Old": old_profile}


def test_blank_or_duplicate_profile_name_is_rejected(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="A", profiles={"A": settings_ui.Profile(name="A")}))

    assert settings_ui.SettingsApp._validated_profile_name(dummy, "  ") is None
    assert settings_ui.SettingsApp._validated_profile_name(dummy, "A") is None
    assert [title for title, _message in errors] == ["Invalid profile name", "Profile exists"]


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_exposes_working_folder_controls_at_1024x768(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(cache))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()

        assert app.working_directory_var.get() == str(cache.absolute())
        for widget in (
            app.working_directory_entry,
            app.working_browse_button,
            app.working_create_button,
            app.working_use_button,
            app.working_cancel_button,
            app.apply_button,
            app.black_button,
            app.export_button,
            app.about_button,
            app.close_button,
        ):
            assert widget.winfo_ismapped()
            assert widget.winfo_width() > 1
        assert "source images remain" in app.working_status_var.get().lower()
        assert app.winfo_x() >= 0
        assert app.winfo_y() >= 0
        assert app.winfo_x() + app.winfo_width() <= app.winfo_screenwidth()
        assert app.winfo_y() + app.winfo_height() <= app.winfo_screenheight()
        assert app.winfo_reqwidth() <= app.winfo_width()
        assert app.winfo_reqheight() <= app.winfo_height()
        assert app.close_button.winfo_rooty() + app.close_button.winfo_height() <= app.winfo_rooty() + app.winfo_height()
    finally:
        app.destroy()


def test_create_working_folder_explicitly_creates_one_child(monkeypatch, tmp_path):
    parent = tmp_path / "external"
    parent.mkdir()
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config())
    setattr(dummy, "working_directory_var", _Var(""))
    setattr(dummy, "working_status_var", _Var(""))
    setattr(dummy, "_ask_folder", lambda **_kwargs: str(parent))
    monkeypatch.setattr(settings_ui.simpledialog, "askstring", lambda *_args, **_kwargs: "MBS Working Files")

    settings_ui.SettingsApp._create_working_directory(dummy)

    created = parent / "MBS Working Files"
    assert created.is_dir()
    assert (created / settings_ui.MARKER_FILENAME).is_file()
    assert dummy.working_directory_var.get() == str(created.resolve())
    assert "created" in dummy.working_status_var.get().lower()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_typed_missing_working_folder_requires_confirmation_and_existing_parent(monkeypatch, tmp_path):
    source = tmp_path / "cache"
    parent = tmp_path / "external"
    parent.mkdir()
    target = parent / "Typed MBS Working Files"
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(source))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    confirmations = []
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: confirmations.append((title, message, kwargs)) or True,
    )
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda *_args, **_kwargs: None)
    app = settings_ui.SettingsApp()
    try:
        app.working_directory_var.set(str(target))
        app._use_working_directory()
        _pump_until(app, lambda: not app._migration_busy)

        assert target.is_dir()
        assert (target / settings_ui.MARKER_FILENAME).is_file()
        assert settings_ui.load_config().working_directory == str(target.resolve())
        assert len(confirmations) == 1
        assert "will be created" in confirmations[0][1]
    finally:
        app.destroy()


def test_typed_working_folder_with_missing_parent_is_rejected_without_confirmation(monkeypatch, tmp_path):
    target = tmp_path / "missing-parent" / "MBS"
    errors = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config())
    setattr(dummy, "working_directory_var", _Var(str(target)))
    setattr(dummy, "working_status_var", _Var(""))
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showerror",
        lambda title, message, **kwargs: errors.append((title, message, kwargs)),
    )
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("missing parent must not prompt")),
    )

    settings_ui.SettingsApp._use_working_directory(dummy)

    assert not target.exists()
    assert errors and errors[0][0] == "Working folder parent missing"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_working_folder_migration_runs_off_tk_thread_and_retains_source(monkeypatch, tmp_path):
    source = tmp_path / "cache"
    source.mkdir()
    active = source / "Default-active-0.png"
    active.write_bytes(b"generated wallpaper")
    target = tmp_path / "external" / "MBS"
    target.parent.mkdir()
    target.mkdir()
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(source))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    gate = threading.Event()
    real_migrate = settings_ui.migrate_working_directory
    messages = []

    def delayed_migration(*args, **kwargs):
        assert gate.wait(timeout=2)
        return real_migrate(*args, **kwargs)

    monkeypatch.setattr(settings_ui, "migrate_working_directory", delayed_migration)
    monkeypatch.setattr(settings_ui.messagebox, "askyesno", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )
    app = settings_ui.SettingsApp()
    try:
        app.working_directory_var.set(str(target))
        app._use_working_directory()
        app.update()

        assert app._migration_busy is True
        assert app._migration_worker is not None
        assert app._migration_worker.daemon is False
        assert app._migration_worker.is_alive()
        assert app.update_button.winfo_exists()

        gate.set()
        _pump_until(app, lambda: not app._migration_busy)

        assert settings_ui.load_config().working_directory == str(target.resolve())
        assert active.read_bytes() == b"generated wallpaper"
        assert (target / active.name).read_bytes() == b"generated wallpaper"
        assert messages and messages[-1][0] == "Working folder changed"
        assert "retained" in messages[-1][1].lower()
    finally:
        gate.set()
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_apply_next_runs_off_tk_thread(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    gate = threading.Event()
    infos = []

    def delayed_apply(_profile, **kwargs):
        kwargs["progress"](500, "/photos/500.jpg")
        assert gate.wait(timeout=2)
        return SimpleNamespace(wallpaper="/tmp/background.png")

    monkeypatch.setattr(settings_ui, "switch_once", delayed_apply)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: infos.append((title, message, kwargs)),
    )
    app = settings_ui.SettingsApp()
    try:
        app._apply_next()
        assert app.apply_button.cget("text") == "Applying..."
        app.update()
        assert app._apply_busy is True
        assert app._apply_worker is not None
        assert app._apply_worker.daemon is False
        assert app._apply_worker.is_alive()
        for button in (
            app.apply_button,
            app.black_button,
            app.export_button,
            app.profile_save_button,
            app.working_use_button,
            app.close_button,
        ):
            assert "disabled" in button.state()

        _pump_until(app, lambda: app.apply_button.cget("text") == "Scanning... 500")

        app._request_close()
        assert app._apply_cancel.is_set()
        assert app.winfo_exists()
        assert infos and infos[-1][0] == "Operation in progress"

        gate.set()
        _pump_until(app, lambda: not app._apply_busy)
        assert app.apply_button.cget("text") == "Apply Next Now"
        assert "disabled" not in app.black_button.state()
    finally:
        gate.set()
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_exposes_update_and_rollback_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        assert app.update_button.cget("text") == "Check for Updates..."
        assert app.update_button.winfo_ismapped()
        assert app.rollback_button.cget("text") == "Roll Back..."
        assert app.rollback_button.winfo_ismapped()
        assert "disabled" in app.rollback_button.state()
        assert "managed updates" in app.update_status_var.get().lower()
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_update_worker_keeps_tk_responsive_and_reports_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    gate = threading.Event()
    errors = []
    infos = []

    def fail_after_release():
        assert gate.wait(timeout=2)
        raise settings_ui.updater.UpdateError("network unavailable")

    monkeypatch.setattr(settings_ui.updater, "check_for_updates", lambda _version: fail_after_release())
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showerror",
        lambda title, message, **kwargs: errors.append((title, message, kwargs)),
    )
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: infos.append((title, message, kwargs)),
    )
    app = settings_ui.SettingsApp()
    try:
        app._check_for_updates()
        app.update()
        assert app.update_button.cget("text") == "Checking..."
        assert "disabled" in app.update_button.state()
        gate.set()
        deadline = time.monotonic() + 3
        while app._update_busy and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)
        assert app._update_busy is False
        assert "disabled" not in app.update_button.state()
        assert errors and errors[0][0] == "Update check failed"
        assert errors[0][1] == "network unavailable"
        assert infos == []
    finally:
        gate.set()
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_blocks_close_until_non_daemon_update_worker_finishes(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    gate = threading.Event()
    messages = []
    closed = []
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )
    app = settings_ui.SettingsApp()
    real_destroy = app.destroy
    monkeypatch.setattr(app, "destroy", lambda: closed.append(True))
    try:
        app._start_update_task(
            "Installing...",
            lambda: gate.wait(timeout=2),
            lambda _result: None,
            "Update failed",
        )
        worker = app._update_worker
        assert worker is not None
        assert worker.daemon is False
        assert worker.is_alive()
        assert "disabled" in app.close_button.state()

        app._request_close()

        assert closed == []
        assert messages and messages[0][0] == "Update in progress"
        assert messages[0][2]["parent"] is app

        gate.set()
        deadline = time.monotonic() + 3
        while app._update_busy and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)
        worker.join(timeout=1)
        assert app._update_busy is False
        assert app._update_worker is None
        assert "disabled" not in app.close_button.state()

        app._request_close()
        assert closed == [True]
    finally:
        gate.set()
        real_destroy()


def test_update_check_prompts_to_install_newer_release(monkeypatch):
    release = settings_ui.updater.ReleaseInfo(
        "0.1.12",
        "v0.1.12",
        "a" * 40,
        "https://github.com/example/archive.tar.gz",
    )
    check = settings_ui.updater.UpdateCheck("0.1.11", release)
    prompts = []
    installs = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "_install_checked_release", lambda selected: installs.append(selected))
    monkeypatch.setattr(settings_ui.updater, "is_managed_runtime", lambda: True)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: prompts.append((title, message, kwargs)) or True,
    )

    settings_ui.SettingsApp._handle_update_check(dummy, check)

    assert prompts and prompts[0][0] == "Update available"
    assert "0.1.11" in prompts[0][1] and "0.1.12" in prompts[0][1]
    assert prompts[0][2]["parent"] is dummy
    assert installs == [release]


def test_update_check_cancel_does_not_install(monkeypatch):
    release = settings_ui.updater.ReleaseInfo(
        "0.1.12",
        "v0.1.12",
        "a" * 40,
        "https://github.com/example/archive.tar.gz",
    )
    check = settings_ui.updater.UpdateCheck("0.1.11", release)
    installs = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "_install_checked_release", lambda selected: installs.append(selected))
    monkeypatch.setattr(settings_ui.updater, "is_managed_runtime", lambda: True)
    monkeypatch.setattr(settings_ui.messagebox, "askyesno", lambda *_args, **_kwargs: False)

    settings_ui.SettingsApp._handle_update_check(dummy, check)

    assert installs == []


def test_up_to_date_unmanaged_copy_offers_managed_install(monkeypatch):
    release = settings_ui.updater.ReleaseInfo(
        settings_ui.__version__,
        f"v{settings_ui.__version__}",
        "b" * 40,
        "https://github.com/example/archive.tar.gz",
    )
    check = settings_ui.updater.UpdateCheck(settings_ui.__version__, release)
    prompts = []
    installs = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "_install_checked_release", lambda selected: installs.append(selected))
    monkeypatch.setattr(settings_ui.updater, "is_managed_runtime", lambda: False)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: prompts.append((title, message, kwargs)) or True,
    )

    settings_ui.SettingsApp._handle_update_check(dummy, check)

    assert prompts and prompts[0][0] == "Set up managed updates"
    assert "managed copy" in prompts[0][1]
    assert installs == [release]


def test_up_to_date_managed_copy_reports_current_without_install(monkeypatch):
    release = settings_ui.updater.ReleaseInfo(
        settings_ui.__version__,
        f"v{settings_ui.__version__}",
        "c" * 40,
        "https://github.com/example/archive.tar.gz",
    )
    check = settings_ui.updater.UpdateCheck(settings_ui.__version__, release)
    messages = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(
        dummy,
        "_install_checked_release",
        lambda _selected: (_ for _ in ()).throw(AssertionError("up-to-date managed copy must not install")),
    )
    monkeypatch.setattr(settings_ui.updater, "is_managed_runtime", lambda: True)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )

    settings_ui.SettingsApp._handle_update_check(dummy, check)

    assert messages and messages[0][0] == "Up to date"
    assert settings_ui.__version__ in messages[0][1]
    assert messages[0][2]["parent"] is dummy


def test_successful_install_can_restart_into_managed_settings(monkeypatch, tmp_path):
    record = settings_ui.updater.InstallRecord("0.1.12", "d" * 40, "e" * 64, "2026-07-21T20:00:00+00:00", tmp_path)
    result = settings_ui.updater.InstallResult(record, None, tmp_path / "launcher")
    restarts = []
    prompts = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "_refresh_rollback_button", lambda: None)
    setattr(dummy, "_refresh_update_status", lambda: None)
    setattr(dummy, "_restart_managed_settings", lambda: restarts.append(True))
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: prompts.append((title, message, kwargs)) or True,
    )

    settings_ui.SettingsApp._handle_install_success(dummy, result)

    assert restarts == [True]
    assert prompts[0][0] == "Update installed"
    assert "unsaved profile changes" in prompts[0][1].lower()


def test_successful_rollback_reports_rollback_before_restart(monkeypatch, tmp_path):
    record = settings_ui.updater.InstallRecord("0.1.11", "f" * 40, "a" * 64, "2026-07-21T20:00:00+00:00", tmp_path)
    previous = settings_ui.updater.InstallRecord("0.1.12", "e" * 40, "b" * 64, "2026-07-21T21:00:00+00:00", tmp_path / "new")
    result = settings_ui.updater.InstallResult(record, previous, tmp_path / "launcher")
    prompts = []
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "_refresh_rollback_button", lambda: None)
    setattr(dummy, "_refresh_update_status", lambda: None)
    setattr(dummy, "_restart_managed_settings", lambda: None)
    monkeypatch.setattr(
        settings_ui.messagebox,
        "askyesno",
        lambda title, message, **kwargs: prompts.append((title, message, kwargs)) or False,
    )

    settings_ui.SettingsApp._handle_rollback_success(dummy, result)

    assert prompts[0][0] == "Rollback activated"
    assert "rolled back" in prompts[0][1].lower()
    assert "0.1.11" in prompts[0][1]
