"""Tests for the per-profile optional post-switch command."""

from pathlib import Path

from PIL import Image

from mint_background_switcher import cli
from mint_background_switcher import service
from mint_background_switcher.config import (
    MAX_POST_SWITCH_COMMAND_LENGTH,
    Config,
    Profile,
    save_config,
)
from mint_background_switcher.desktop import LockscreenMirrorResult


def _write_images(folder, count=4):
    folder.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        Image.new("RGB", (80 + idx * 10, 40 + idx * 5), (idx * 40, 0, 255 - idx * 40)).save(
            folder / f"img{idx}.png"
        )


class _RecordingDesktopSetter:
    def __init__(self, dry_run: bool = False, solid_black: bool = False):
        self.dry_run = dry_run
        self.solid_black = solid_black
        self.calls = []

    def apply(self, image_path, desktop="auto"):
        self.calls.append(("apply", str(image_path), desktop, self.dry_run))
        return ["fake"]

    def apply_black(self, image_path=None, desktop="auto"):
        self.calls.append(("apply_black", None if image_path is None else str(image_path), desktop, self.dry_run))
        return ["fake-black"]

    def supports_solid_black(self, desktop="auto"):
        return self.solid_black

    def mirror_lockscreen(self, image_path, desktop="auto"):
        self.calls.append(("mirror_lockscreen", str(image_path), desktop, self.dry_run))
        return LockscreenMirrorResult("unsupported", "test stub: no per-user lock-screen setting")


def _setup(monkeypatch, tmp_path: Path, *, post_switch_command: str = "", images: int = 4):
    image_dir = tmp_path / "images"
    if images:
        _write_images(image_dir, images)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0")
    holder = {"setter": None}

    def factory(dry_run=False):
        setter = _RecordingDesktopSetter(dry_run=dry_run)
        holder["setter"] = setter
        return setter

    monkeypatch.setattr(service, "DesktopSetter", factory)
    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(
                    name="P",
                    shared_folders=[str(image_dir)],
                    desktop="unknown",
                    post_switch_command=post_switch_command,
                )
            },
        )
    )
    return holder


def _marker_script(tmp_path: Path, marker: Path) -> str:
    """An executable stand-in for the user's post-switch command.

    The hook executes with shlex.split and no shell, so the marker must be
    a real file rather than shell redirect syntax like `echo >> file`.
    """
    script = tmp_path / "marker.sh"
    script.write_text(f"#!/bin/sh\necho switched >> {marker}\n")
    script.chmod(0o755)
    return str(script)


# --- config coercion -----------------------------------------------------


def test_post_switch_command_defaults_to_empty():
    profile = Profile(name="P")
    assert profile.post_switch_command == ""


def test_post_switch_command_round_trips_through_dict():
    profile = Profile(name="P", post_switch_command="/bin/echo hello world")
    restored = Profile.from_dict("P", profile.to_dict())
    assert restored.post_switch_command == "/bin/echo hello world"


def test_post_switch_command_drops_over_long_values():
    profile = Profile.from_dict("P", {"post_switch_command": "x" * (MAX_POST_SWITCH_COMMAND_LENGTH + 1)})
    assert profile.post_switch_command == ""


def test_post_switch_command_drops_line_breaks():
    profile = Profile.from_dict("P", {"post_switch_command": "/bin/echo\nsecond line"})
    assert profile.post_switch_command == ""


def test_post_switch_command_allows_tabs_as_separators():
    profile = Profile.from_dict("P", {"post_switch_command": "/bin/echo\thello"})
    assert profile.post_switch_command == "/bin/echo\thello"


def test_post_switch_command_drops_non_string_values():
    profile = Profile.from_dict("P", {"post_switch_command": 42})
    assert profile.post_switch_command == ""


def test_post_switch_command_strips_surrounding_whitespace():
    profile = Profile.from_dict("P", {"post_switch_command": "  /bin/echo ok  "})
    assert profile.post_switch_command == "/bin/echo ok"


# --- run_post_switch_command (unit) ---------------------------------------


def test_run_post_switch_command_empty_is_noop():
    assert service.run_post_switch_command("") == ""
    assert service.run_post_switch_command("   ") == ""


def test_run_post_switch_command_success_is_silent(tmp_path):
    marker = tmp_path / "marker"
    assert service.run_post_switch_command(_marker_script(tmp_path, marker)) == ""
    assert marker.read_text().splitlines() == ["switched"]


def test_run_post_switch_command_failure_reports_exit_code_and_stderr(tmp_path):
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/sh\necho oops-to-stderr >&2\nexit 3\n")
    script.chmod(0o755)
    note = service.run_post_switch_command(str(script))
    assert "exit 3" in note
    assert "oops-to-stderr" in note


def test_run_post_switch_command_missing_binary_reports_not_found():
    note = service.run_post_switch_command("mbs-definitely-not-a-real-binary-xyz")
    assert "not found" in note


def test_run_post_switch_command_invalid_command_line_reports_invalid():
    note = service.run_post_switch_command("/bin/echo 'unbalanced")
    assert "not valid" in note


def test_run_post_switch_command_timeout_terminates_and_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "POST_SWITCH_TIMEOUT_SECONDS", 1)
    note = service.run_post_switch_command("sleep 5")
    assert "timed out after 1 s" in note


def test_run_post_switch_command_unexpected_error_is_contained(tmp_path):
    script = tmp_path / "badutf8.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stderr.buffer.write(b'\\xff\\xfe')\n"
        "sys.exit(2)\n"
    )
    script.chmod(0o755)
    note = service.run_post_switch_command(str(script))
    assert "unexpected error" in note


# --- switch_once integration ----------------------------------------------


def test_switch_once_runs_post_switch_command_after_applying(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    result = service.switch_once()

    assert result.applied is True
    assert result.post_switch_note == ""
    assert marker.read_text().splitlines() == ["switched"]


def test_switch_once_with_failing_command_still_applies_and_reports(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, post_switch_command="/bin/false")

    result = service.switch_once()

    assert result.applied is True
    assert "exit 1" in result.post_switch_note


def test_switch_once_dry_run_never_runs_the_command(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    result = service.switch_once(dry_run=True)

    assert result.applied is False
    assert not marker.exists()
    assert result.post_switch_note == ""


def test_switch_once_black_fallback_never_runs_the_command(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker), images=0)

    result = service.switch_once()

    assert result.action == "black-fallback"
    assert not marker.exists()
    assert result.post_switch_note == ""


def test_redraw_current_does_not_run_the_command(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    service.switch_once()
    service.redraw_current()

    assert marker.read_text().splitlines() == ["switched"]


def test_previous_wallpaper_does_not_run_the_command(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    service.switch_once()
    service.switch_once()
    service.previous_wallpaper()

    assert marker.read_text().splitlines() == ["switched", "switched"]


def test_black_screen_does_not_run_the_command(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    service.switch_once()
    service.black_screen()

    assert marker.read_text().splitlines() == ["switched"]


def test_resume_runs_the_command_like_a_normal_switch(monkeypatch, tmp_path):
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))

    service.switch_once()
    service.black_screen()
    service.resume()

    assert marker.read_text().splitlines() == ["switched", "switched"]


def test_switch_once_contains_settings_failure_at_the_hook(monkeypatch, tmp_path):
    """A settings read that breaks after the wallpaper applied must surface
    as a note, never as an exception out of switch_once (the wallpaper is
    already on the desktop by then)."""
    marker = tmp_path / "marker"
    _setup(monkeypatch, tmp_path, post_switch_command=_marker_script(tmp_path, marker))
    real_load = service.load_config
    calls = {"n": 0}

    def flaky_load():
        calls["n"] += 1
        if calls["n"] <= 2:
            return real_load()
        return Config(active_profile="P", profiles={})

    monkeypatch.setattr(service, "load_config", flaky_load)
    result = service.switch_once()

    assert result.applied is True
    assert result.post_switch_note == "Post-switch command was not run: the settings could not be read."
    assert not marker.exists()


# --- CLI output -------------------------------------------------------------


def test_cli_print_result_includes_post_switch_note(capsys):
    result = service.SwitchResult(
        "P",
        Path("/tmp/wall.png"),
        [],
        [],
        applied=True,
        action="next",
        lockscreen_note="",
        overlay_note="",
        post_switch_note="Post-switch command failed (exit 3): oops",
    )
    cli._print_result(result)
    out = capsys.readouterr().out
    assert "post_switch=Post-switch command failed (exit 3): oops" in out


def test_cli_print_result_omits_empty_post_switch_note(capsys):
    result = service.SwitchResult("P", Path("/tmp/wall.png"), [], [], applied=True, action="next")
    cli._print_result(result)
    assert "post_switch" not in capsys.readouterr().out
