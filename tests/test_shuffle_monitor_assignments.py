"""Tests for the "Shuffle monitor assignments" action (per-monitor folder redistribution)."""

import random
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher import cli, service
from mint_background_switcher.config import Config, Profile, load_config, save_config
from mint_background_switcher.state import load_state


class _ReversingRng(random.Random):
    """Deterministic stand-in: only ``shuffle`` is used by the code under test."""

    def __init__(self):
        super().__init__(1)

    def shuffle(self, x, _random=None):
        x.reverse()


def _write_images(folder, count=4):
    folder.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        Image.new("RGB", (80 + idx * 10, 40 + idx * 5), (idx * 40, 0, 255 - idx * 40)).save(folder / f"img{idx}.png")


def _setup(monkeypatch, tmp_path: Path, *, monitor_folders=None, mode="per-monitor"):
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
    folder_a = image_dir / "a"
    folder_b = image_dir / "b"
    _write_images(folder_a)
    _write_images(folder_b)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0,B:100x80+100+0")
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(
                    name="P",
                    shared_folders=[str(image_dir)],
                    mode=mode,
                    desktop="unknown",
                    monitor_folders=monitor_folders
                    or {
                        "A": [str(folder_a)],
                        "B": [str(folder_b)],
                    },
                )
            },
        )
    )
    return folder_a, folder_b


def test_compute_shuffled_assignments_preserves_counts_and_pool():
    assigned = {"A": ["/x/f1", "/x/f2"], "B": ["/y/f3"], "C": ["/z/f4", "/z/f5", "/z/f6"]}
    shuffled, changed = service.compute_shuffled_assignments(assigned, _ReversingRng())

    assert sorted(shuffled) == ["A", "B", "C"]
    assert {monitor: len(folders) for monitor, folders in shuffled.items()} == {"A": 2, "B": 1, "C": 3}
    assert sorted(f for folders in shuffled.values() for f in folders) == sorted(
        f for folders in assigned.values() for f in folders
    )
    assert changed is True
    # The reversed pool is dealt in sorted monitor order.
    assert shuffled["A"] == ["/z/f6", "/z/f5"]
    assert shuffled["B"] == ["/z/f4"]
    assert shuffled["C"] == ["/y/f3", "/x/f2", "/x/f1"]


def test_compute_shuffled_assignments_reports_unchanged_mapping():
    # Two monitors sharing one identical folder list can only shuffle to themselves.
    assigned = {"A": ["/s/f"], "B": ["/s/f"]}
    shuffled, changed = service.compute_shuffled_assignments(assigned, _ReversingRng())
    assert shuffled == assigned
    assert changed is False


def test_shuffle_requires_two_assigned_monitors(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, monitor_folders={"A": ["/x"]})

    with pytest.raises(service.NoShufflableMonitorsError):
        service.shuffle_monitor_assignments()

    with pytest.raises(service.NoShufflableMonitorsError):
        service.shuffle_monitor_assignments(dry_run=True)


def test_shuffle_rejects_non_per_monitor_profiles(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, monitor_folders={"A": ["/x"], "B": ["/y"]}, mode="shared")

    with pytest.raises(service.ShuffleNotApplicableError):
        service.shuffle_monitor_assignments()

    with pytest.raises(service.ShuffleNotApplicableError):
        service.shuffle_monitor_assignments(dry_run=True)


def test_live_shuffle_rejects_mode_change_between_reads(monkeypatch, tmp_path):
    """The locked re-read must re-validate the layout, not trust the pre-lock snapshot."""
    folder_a, folder_b = _setup(monkeypatch, tmp_path)
    disk = Config(
        active_profile="P",
        profiles={
            "P": Profile(
                name="P",
                shared_folders=[str(tmp_path / "images")],
                mode="shared",
                desktop="unknown",
                monitor_folders={"A": [str(folder_a)], "B": [str(folder_b)]},
            )
        },
    )
    save_config(disk)
    pre_lock = Config(
        active_profile="P",
        profiles={
            "P": Profile(
                name="P",
                shared_folders=[str(tmp_path / "images")],
                mode="per-monitor",
                desktop="unknown",
                monitor_folders={"A": [str(folder_a)], "B": [str(folder_b)]},
            )
        },
    )
    monkeypatch.setattr(service, "load_config", lambda: pre_lock)

    with pytest.raises(service.ShuffleNotApplicableError):
        service.shuffle_monitor_assignments()

    # The on-disk config is untouched: still shared mode, original assignments.
    saved = load_config().get_profile("P")
    assert saved.mode == "shared"
    assert saved.monitor_folders == {"A": [str(folder_a)], "B": [str(folder_b)]}


def test_shuffle_persists_and_applies_a_new_wallpaper(monkeypatch, tmp_path):
    folder_a, folder_b = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(service.random, "SystemRandom", lambda: _ReversingRng())

    result = service.shuffle_monitor_assignments()

    assert result.action == "shuffle-monitor"
    assert result.applied is True
    assert result.wallpaper.is_file()
    assert result.shuffle_note.startswith("shuffled per-monitor folders (")
    config = load_config()
    new_map = config.get_profile("P").monitor_folders
    assert sorted(f for folders in new_map.values() for f in folders) == sorted([str(folder_a), str(folder_b)])
    assert {monitor: len(folders) for monitor, folders in new_map.items()} == {"A": 1, "B": 1}
    state = load_state()
    assert state.last_wallpaper == str(result.wallpaper)
    assert len(state.last_images) == 2


def test_shuffle_unchanged_mapping_applies_nothing(monkeypatch, tmp_path):
    folder_a, _ = _setup(monkeypatch, tmp_path)
    # Both monitors share one folder, so every shuffle is a no-op.
    shared = str(folder_a)
    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(
                    name="P",
                    shared_folders=[shared],
                    mode="per-monitor",
                    desktop="unknown",
                    monitor_folders={"A": [shared], "B": [shared]},
                )
            },
        )
    )
    state_before = load_state().to_dict()

    result = service.shuffle_monitor_assignments()

    assert result.action == "shuffle-monitor"
    assert result.applied is False
    assert "unchanged" in result.shuffle_note
    assert load_config().get_profile("P").monitor_folders == {"A": [shared], "B": [shared]}
    assert load_state().to_dict() == state_before


def test_shuffle_dry_run_changes_nothing(monkeypatch, tmp_path):
    folder_a, folder_b = _setup(monkeypatch, tmp_path)
    profile_before = load_config().get_profile("P").to_dict()
    state_before = load_state().to_dict()

    result = service.shuffle_monitor_assignments(dry_run=True, rng=_ReversingRng())

    assert result.applied is False
    assert result.shuffle_note.startswith("planned: shuffled per-monitor folders (")
    assert f"A: {folder_a} -> {folder_b}" in result.shuffle_note
    assert f"B: {folder_b} -> {folder_a}" in result.shuffle_note
    assert not result.wallpaper.is_file()
    assert load_config().get_profile("P").to_dict() == profile_before
    assert load_state().to_dict() == state_before


def test_cli_shuffle_monitor_dry_run(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)

    code = cli.main(["shuffle-monitor", "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert "action=shuffle-monitor" in out
    assert "applied=False" in out
    assert "shuffle=" in out


def test_cli_shuffle_monitor_applies_and_reports_mapping(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(service.random, "SystemRandom", lambda: _ReversingRng())

    code = cli.main(["shuffle-monitor"])

    out = capsys.readouterr().out
    assert code == 0
    assert "action=shuffle-monitor" in out
    assert "applied=True" in out
    assert "shuffle=shuffled per-monitor folders (" in out
    new_map = load_config().get_profile("P").monitor_folders
    assert {monitor: len(folders) for monitor, folders in new_map.items()} == {"A": 1, "B": 1}


def test_cli_shuffle_monitor_reports_not_applicable(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, monitor_folders={"A": ["/x"], "B": ["/y"]}, mode="shared")

    code = cli.main(["shuffle-monitor", "--dry-run"])

    err = capsys.readouterr().err
    assert code == 1
    assert "error: shuffling monitor assignments only applies to the Per-monitor layout" in err
