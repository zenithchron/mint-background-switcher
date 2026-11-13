"""Tests for the "Previous wallpaper" action (per-profile history stack)."""

from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher import cli
from mint_background_switcher import hotkeys
from mint_background_switcher import service
from mint_background_switcher.config import (
    DEFAULT_PREVIOUS_HOTKEY,
    Config,
    Profile,
    load_config,
    save_config,
)
from mint_background_switcher.state import (
    RuntimeState,
    WALLPAPER_HISTORY_LIMIT,
    load_state,
)
from mint_background_switcher.working_storage import migrate_working_directory


def _write_images(folder, count=4):
    folder.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        Image.new("RGB", (80 + idx * 10, 40 + idx * 5), (idx * 40, 0, 255 - idx * 40)).save(folder / f"img{idx}.png")


def _setup(monkeypatch, tmp_path: Path) -> None:
    class _FakeDesktopSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def apply(self, *_args, **_kwargs):
            return ["fake"]

        def apply_black(self, *_args, **_kwargs):
            return ["fake-black"]

        def supports_solid_black(self, *_args, **_kwargs):
            return False

    image_dir = tmp_path / "images"
    _write_images(image_dir)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0")
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(
        Config(
            active_profile="P",
            profiles={"P": Profile(name="P", shared_folders=[str(image_dir)], desktop="unknown")},
        )
    )


def _switches(monkeypatch, tmp_path: Path, count: int = 2):
    _setup(monkeypatch, tmp_path)
    return [service.switch_once() for _ in range(count)]


def test_previous_restores_the_displaced_wallpaper(monkeypatch, tmp_path):
    first, second = _switches(monkeypatch, tmp_path, 2)

    result = service.previous_wallpaper()

    assert result.action == "previous"
    assert result.applied is True
    # The restored bytes are exactly what the first switch applied.
    assert result.wallpaper.read_bytes() == first.wallpaper.read_bytes()
    state = load_state()
    assert state.last_wallpaper == str(result.wallpaper)
    assert state.last_images == first.images
    # The consumed snapshot left the stack.
    assert state.wallpaper_history == {}


def test_previous_walks_back_one_step_at_a_time(monkeypatch, tmp_path):
    first, second, third = _switches(monkeypatch, tmp_path, 3)

    restored_second = service.previous_wallpaper()
    restored_first = service.previous_wallpaper()

    assert restored_second.wallpaper.read_bytes() == second.wallpaper.read_bytes()
    assert restored_first.wallpaper.read_bytes() == first.wallpaper.read_bytes()

    with pytest.raises(service.NoPreviousWallpaperError):
        service.previous_wallpaper()


def test_previous_without_history_raises_in_live_and_dry_run(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)

    with pytest.raises(service.NoPreviousWallpaperError):
        service.previous_wallpaper()
    with pytest.raises(service.NoPreviousWallpaperError):
        service.previous_wallpaper(dry_run=True)


def test_previous_dry_run_is_read_only(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 2)
    before = load_state().to_dict()
    snapshots_before = {
        entry["wallpaper"] for entry in load_state().wallpaper_history["P"]
    }

    result = service.previous_wallpaper(dry_run=True)

    assert result.applied is False
    assert result.action == "previous"
    assert load_state().to_dict() == before
    after = {entry["wallpaper"] for entry in load_state().wallpaper_history["P"]}
    assert after == snapshots_before


def test_previous_history_is_capped(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    for _ in range(WALLPAPER_HISTORY_LIMIT + 3):
        service.switch_once()

    history = load_state().wallpaper_history["P"]
    assert len(history) == WALLPAPER_HISTORY_LIMIT
    # Slots stay contiguous from prev-0.
    for index, entry in enumerate(history):
        name = Path(entry["wallpaper"]).name
        assert name == f"P-prev-{index}.png"


def test_previous_skips_snapshot_with_missing_file(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 3)
    # Delete the newest snapshot; "previous" must fall through to the older one.
    state = load_state()
    entries = state.wallpaper_history["P"]
    expected_bytes = Path(entries[1]["wallpaper"]).read_bytes()
    Path(entries[0]["wallpaper"]).unlink()

    result = service.previous_wallpaper()

    assert result.wallpaper.read_bytes() == expected_bytes
    # The consumed survivor left the stack.
    assert load_state().wallpaper_history.get("P", []) == []


def test_black_screen_pushes_history_and_previous_restores(monkeypatch, tmp_path):
    (first,) = _switches(monkeypatch, tmp_path, 1)
    service.black_screen()

    state = load_state()
    assert state.black_screen is True
    assert len(state.wallpaper_history["P"]) == 1

    result = service.previous_wallpaper()

    assert result.applied is True
    assert result.wallpaper.read_bytes() == first.wallpaper.read_bytes()
    state = load_state()
    assert state.black_screen is False
    assert state.paused is False
    assert state.last_wallpaper == str(result.wallpaper)


def test_previous_after_black_screen_with_empty_history_raises(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    service.black_screen()
    state = load_state()
    # Nothing was ever applied, so the black screen has no predecessor to record.
    assert state.wallpaper_history.get("P", []) == []
    with pytest.raises(service.NoPreviousWallpaperError):
        service.previous_wallpaper()


def test_history_survives_state_round_trip():
    state = RuntimeState()
    state.wallpaper_history["P"] = [
        {"wallpaper": "/w/P-prev-0.png", "images": ["/a/1.png"]},
        {"wallpaper": "/w/P-prev-1.png", "images": ["/a/2.png", "/a/3.png"]},
    ]

    restored = RuntimeState.from_dict(state.to_dict())

    assert restored.wallpaper_history == state.wallpaper_history


def test_history_parse_drops_invalid_entries():
    state = RuntimeState.from_dict(
        {
            "wallpaper_history": {
                "P": [
                    {"wallpaper": "/w/P-prev-0.png", "images": ["/a/1.png"]},
                    {"wallpaper": "", "images": ["/a/1.png"]},
                    {"wallpaper": "/w/P-prev-1.png", "images": []},
                    {"wallpaper": "/w/P-prev-2.png", "images": "not-a-list"},
                    "garbage",
                ]
            }
        }
    )

    assert state.wallpaper_history["P"] == [
        {"wallpaper": "/w/P-prev-0.png", "images": ["/a/1.png"]}
    ]


def test_profile_previous_hotkey_round_trip_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    profile = Profile(name="P")
    assert profile.previous_hotkey == DEFAULT_PREVIOUS_HOTKEY == "<Primary><Alt>Left"

    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(name="P", previous_hotkey="<Ctrl>Left"),
                "Q": Profile(name="Q"),
            },
        )
    )
    loaded = load_config()
    assert loaded.get_profile("P").previous_hotkey == "<Ctrl>Left"
    # Legacy configs without the key fall back to the default.
    assert loaded.get_profile("Q").previous_hotkey == DEFAULT_PREVIOUS_HOTKEY


def test_hotkey_action_registered_for_previous(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    commands = hotkeys.register_cinnamon_hotkey("previous", dry_run=True)

    assert hotkeys.HOTKEY_ACTIONS["previous"].custom_path in commands[0][4]
    assert "Mint Background Switcher: Previous" in commands[1][-1]
    assert "previous" in commands[2][-1]
    assert hotkeys.HOTKEY_ACTIONS["previous"].cli_command == "previous"


def test_cli_previous_command_reports_result(monkeypatch, tmp_path, capsys):
    _switches(monkeypatch, tmp_path, 2)

    assert cli.main(["previous"]) == 0
    out = capsys.readouterr().out
    assert "previous" in out


def test_cli_previous_without_history_fails(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)

    assert cli.main(["previous"]) == 1
    err = capsys.readouterr().err
    assert "no previous wallpaper" in err


def test_cli_previous_dry_run(monkeypatch, tmp_path, capsys):
    _switches(monkeypatch, tmp_path, 2)

    assert cli.main(["previous", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "previous" in out


def test_working_directory_migration_remaps_history(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    for _ in range(3):
        service.switch_once()
    old_last = load_state().last_wallpaper

    destination = tmp_path / "moved-wd"
    destination.mkdir()
    config = load_config()
    migrate_working_directory(config, destination)

    state = load_state()
    entries = state.wallpaper_history["P"]
    assert entries, "history should survive the migration"
    new_root = Path(entries[0]["wallpaper"]).parent
    assert new_root == destination
    assert all(Path(entry["wallpaper"]).is_file() for entry in entries)
    assert state.last_wallpaper == str(Path(destination) / Path(old_last).name)
    assert Path(state.last_wallpaper).is_file()

    # The restored wallpaper must come from the new location.
    result = service.previous_wallpaper()
    assert result.applied is True
    assert result.wallpaper.parent == destination


def test_previous_cancels_rotation_when_requested(monkeypatch, tmp_path):
    _switches(monkeypatch, tmp_path, 2)
    cancelled = {"flag": True}

    with pytest.raises(RuntimeError):
        service.previous_wallpaper(cancelled=lambda: cancelled["flag"])
