import threading

from mint_background_switcher import tray as tray_module
from mint_background_switcher.service import SwitchCancelled
from mint_background_switcher.tray import RotationRunner, TRAY_ICON_CANDIDATES, TrayApp, choose_tray_icon


class _Theme:
    def __init__(self, available):
        self.available = set(available)

    def has_icon(self, icon_name):
        return icon_name in self.available


class _Gtk:
    class IconTheme:
        @staticmethod
        def get_default():
            return _Theme({"image-x-generic-symbolic"})


class _NoThemeGtk:
    class IconTheme:
        @staticmethod
        def get_default():
            return None


def test_choose_tray_icon_prefers_symbolic_monochrome_icon():
    assert choose_tray_icon(_Gtk) == "image-x-generic-symbolic"


def test_choose_tray_icon_falls_back_to_eye_symbolic():
    assert choose_tray_icon(_NoThemeGtk) == TRAY_ICON_CANDIDATES[0]
    assert TRAY_ICON_CANDIDATES[0] == "view-preview-symbolic"


def test_rotation_runner_returns_immediately_and_coalesces_next_requests():
    first_started = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    calls = []

    def operation(profile_name, *, clear_black, cancelled):
        calls.append((profile_name, clear_black, cancelled))
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(2)
        else:
            second_finished.set()

    runner = RotationRunner(lambda callback, *args: callback(*args), operation=operation)

    assert runner.request("P") is True
    assert first_started.wait(2)
    assert runner.request("P") is False
    assert len(calls) == 1
    release_first.set()
    assert second_finished.wait(2)
    runner.wait(timeout=2)

    assert len(calls) == 2
    assert runner.busy is False


def test_rotation_runner_cancels_without_reporting_expected_error():
    started = threading.Event()
    noticed_cancel = threading.Event()
    errors = []

    def operation(_profile_name, *, clear_black, cancelled):
        assert clear_black is True
        started.set()
        assert noticed_cancel.wait(2)
        if cancelled():
            raise SwitchCancelled("cancelled")

    runner = RotationRunner(
        lambda callback, *args: callback(*args),
        operation=operation,
        error_handler=errors.append,
    )
    runner.request()
    assert started.wait(2)
    runner.cancel()
    noticed_cancel.set()
    runner.wait(timeout=2)

    assert errors == []
    assert runner.busy is False


def test_rotation_runner_serializes_actions_before_later_rotation_requests():
    first_started = threading.Event()
    release_first = threading.Event()
    completed = threading.Event()
    calls = []

    def operation(profile_name, *, clear_black, cancelled):
        calls.append(("rotation", profile_name, clear_black))
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(2)
            assert cancelled()
        else:
            completed.set()

    runner = RotationRunner(lambda callback, *args: callback(*args), operation=operation)
    runner.request("first")
    assert first_started.wait(2)
    runner.cancel()
    runner.submit(lambda: calls.append(("pause",)))
    runner.request("after-pause")
    release_first.set()
    assert completed.wait(2)
    runner.wait(timeout=2)

    assert calls == [
        ("rotation", "first", True),
        ("pause",),
        ("rotation", "after-pause", True),
    ]


def test_open_settings_launches_independent_process(monkeypatch):
    calls = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeProcess()

    class FakeGLib:
        @staticmethod
        def timeout_add_seconds(_seconds, _callback):
            return 1

    app = TrayApp.__new__(TrayApp)
    app.GLib = FakeGLib()
    app._settings_process = None
    monkeypatch.setattr(tray_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tray_module, "source_wrapper_argv", lambda: ["/managed/mbs"])

    app._settings()

    assert calls == [
        (
            ["/managed/mbs", "settings"],
            {"close_fds": True, "start_new_session": True},
        )
    ]
