"""Tests for the "Redraw Current" action (re-apply the active wallpaper)."""

from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher import cli
from mint_background_switcher import hotkeys
from mint_background_switcher import service
from mint_background_switcher.config import (
    DEFAULT_REDRAW_HOTKEY,
    Config,
    Profile,
    load_config,
    save_config,
)
from mint_background_switcher.desktop import LockscreenMirrorResult
from mint_background_switcher.state import load_state


def _write_images(folder, count=4):
    folder.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        Image.new("RGB", (80 + idx * 10, 40 + idx * 5), (idx * 40, 0, 255 - idx * 40)).save(folder / f"img{idx}.png")


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


def _setup(monkeypatch, tmp_path: Path, *, solid_black: bool = False, sequential: bool = False):
    image_dir = tmp_path / "images"
    _write_images(image_dir)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0")
    holder = {"setter": None}

    def factory(dry_run=False):
        setter = _RecordingDesktopSetter(dry_run=dry_run, solid_black=solid_black)
        holder["setter"] = setter
        return setter

    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", factory)
    save_config(
        Config(
            active_profile="P",
            profiles={"P": Profile(name="P", shared_folders=[str(image_dir)], desktop="unknown", sequential=sequential)},
        )
    )
    return holder


def _switches(monkeypatch, tmp_path: Path, count: int = 2, **kwargs):
    _setup(monkeypatch, tmp_path, **kwargs)
    return [service.switch_once() for _ in range(count)]


def test_redraw_reapplies_the_current_wallpaper_without_changing_state(monkeypatch, tmp_path):
    holder = _setup(monkeypatch, tmp_path)
    service.switch_once()
    service.switch_once()
    before = load_state().to_dict()

    result = service.redraw_current()

    assert result.action == "redraw-current"
    assert result.applied is True
    # The desktop received the current composed file via the normal apply path.
    assert holder["setter"].calls[-1] == ("apply", str(result.wallpaper), "unknown", False)
    assert result.images == load_state().last_images
    # Nothing changed: same current wallpaper, same pool position, same history.
    assert load_state().to_dict() == before


def test_redraw_does_not_advance_the_rotation(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, sequential=True)
    first = service.switch_once()
    service.redraw_current()
    second = service.switch_once()

    # Folder-order rotation: img0, then img1. A redraw must not consume img1.
    assert Path(first.images[0]).name == "img0.png"
    assert Path(second.images[0]).name == "img1.png"


def test_redraw_keeps_history_stack_untouched(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 3)
    history_before = [dict(entry) for entry in load_state().wallpaper_history["P"]]

    service.redraw_current()
    service.redraw_current()

    assert load_state().wallpaper_history["P"] == history_before


def test_redraw_dry_run_is_read_only(monkeypatch, tmp_path):
    holder = _setup(monkeypatch, tmp_path)
    service.switch_once()
    service.switch_once()
    before = load_state().to_dict()

    result = service.redraw_current(dry_run=True)

    assert result.applied is False
    assert result.action == "redraw-current"
    assert str(result.wallpaper) == load_state().last_wallpaper
    # The dry run reported the apply without touching state or real desktops.
    assert holder["setter"].calls[-1][3] is True
    assert load_state().to_dict() == before


def test_redraw_without_any_wallpaper_raises_in_live_and_dry_run(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)

    with pytest.raises(service.NoCurrentWallpaperError):
        service.redraw_current()
    with pytest.raises(service.NoCurrentWallpaperError):
        service.redraw_current(dry_run=True)


def test_redraw_with_missing_current_file_raises(monkeypatch, tmp_path):
    (first,) = _switches(monkeypatch, tmp_path, 1)
    Path(first.wallpaper).unlink()

    with pytest.raises(service.NoCurrentWallpaperError, match="missing"):
        service.redraw_current()
    with pytest.raises(service.NoCurrentWallpaperError, match="missing"):
        service.redraw_current(dry_run=True)


def test_redraw_reapplies_black_screen_when_active(monkeypatch, tmp_path):
    holder = _setup(monkeypatch, tmp_path)
    service.switch_once()
    black = service.black_screen()
    before = load_state().to_dict()
    assert before["black_screen"] is True

    result = service.redraw_current()

    assert result.action == "redraw-current"
    assert result.applied is True
    assert str(result.wallpaper) == str(black.wallpaper)
    # The non-solid-black desktop re-applies the composed black file.
    assert holder["setter"].calls[-1] == ("apply_black", str(black.wallpaper), "unknown", False)
    # The black screen stays active; redrawing it must not clear it or the pause.
    state = load_state()
    assert state.black_screen is True
    assert state.paused is True
    assert state.last_wallpaper == str(black.wallpaper)


def test_redraw_black_screen_uses_solid_black_on_supported_desktops(monkeypatch, tmp_path):
    holder = _setup(monkeypatch, tmp_path, solid_black=True)
    service.switch_once()
    service.black_screen()

    service.redraw_current()

    assert holder["setter"].calls[-1] == ("apply_black", None, "unknown", False)


def test_redraw_black_screen_with_missing_composite_raises(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 1)
    service.black_screen()
    state = load_state()
    assert state.last_wallpaper is not None
    Path(state.last_wallpaper).unlink()

    with pytest.raises(service.NoCurrentWallpaperError, match="black-screen file is missing"):
        service.redraw_current()


def test_redraw_profile_argument_selects_profile_settings(monkeypatch, tmp_path):
    holder = _setup(monkeypatch, tmp_path)
    service.switch_once()
    config = load_config()
    config.profiles["Q"] = Profile(name="Q", shared_folders=[], desktop="cinnamon")
    save_config(config)

    result = service.redraw_current("Q")

    assert result.profile == "Q"
    assert holder["setter"].calls[-1][2] == "cinnamon"


def test_profile_redraw_hotkey_round_trip_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    profile = Profile(name="P")
    assert profile.redraw_hotkey == DEFAULT_REDRAW_HOTKEY == "<Primary><Alt>r"

    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(name="P", redraw_hotkey="<Ctrl>r"),
                "Q": Profile(name="Q"),
            },
        )
    )
    loaded = load_config()
    assert loaded.get_profile("P").redraw_hotkey == "<Ctrl>r"
    # Legacy configs without the key fall back to the default.
    assert loaded.get_profile("Q").redraw_hotkey == DEFAULT_REDRAW_HOTKEY


def test_hotkey_action_registered_for_redraw(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    commands = hotkeys.register_cinnamon_hotkey("redraw", dry_run=True)

    assert hotkeys.HOTKEY_ACTIONS["redraw"].custom_path in commands[0][4]
    assert "Mint Background Switcher: Redraw Current" in commands[1][-1]
    assert "redraw-current" in commands[2][-1]
    assert hotkeys.HOTKEY_ACTIONS["redraw"].cli_command == "redraw-current"
    profile = load_config().get_profile()
    assert hotkeys.hotkey_binding_for(profile, "redraw") == DEFAULT_REDRAW_HOTKEY


def test_cli_redraw_current_command_reports_result(monkeypatch, tmp_path, capsys):
    _switches(monkeypatch, tmp_path, 2)

    assert cli.main(["redraw-current"]) == 0
    out = capsys.readouterr().out
    assert "redraw-current" in out


def test_cli_redraw_current_without_wallpaper_fails(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)

    assert cli.main(["redraw-current"]) == 1
    err = capsys.readouterr().err
    assert "no wallpaper has been applied" in err


def test_cli_redraw_current_dry_run(monkeypatch, tmp_path, capsys):
    _switches(monkeypatch, tmp_path, 2)

    assert cli.main(["redraw-current", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "applied=False" in out


def test_redraw_cancels_rotation_when_requested(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 2)
    cancelled = {"flag": True}

    with pytest.raises(RuntimeError):
        service.redraw_current(cancelled=lambda: cancelled["flag"])
