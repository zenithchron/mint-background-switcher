import os
import random
import threading
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher import service
from mint_background_switcher.config import Config, Profile, save_config
from mint_background_switcher.service import black_screen, resume, save_current_wallpaper, switch_once
from mint_background_switcher.state import RuntimeState, load_state, save_state


def _write_images(folder: Path, count: int = 4) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        Image.new("RGB", (80 + idx * 10, 40 + idx * 5), (idx * 40, 0, 255 - idx * 40)).save(folder / f"img{idx}.png")


def _setup_profile(monkeypatch, tmp_path: Path) -> None:
    class _FakeDesktopSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def apply(self, *_args, **_kwargs):
            return ["fake"]

        def apply_black(self, *_args, **_kwargs):
            return ["fake-black"]

        def supports_solid_black(self, *_args, **_kwargs):
            return False

    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    image_dir = tmp_path / "images"
    _write_images(image_dir)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MBS_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0,B:120x80+100+0")
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(
        Config(
            active_profile="P",
            profiles={"P": Profile(name="P", shared_folders=[str(image_dir)], desktop="unknown")},
        )
    )


def test_dry_run_next_black_and_resume_do_not_persist_state(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    original = RuntimeState(
        paused=True,
        black_screen=True,
        active_profile="P",
        remaining={"profile:P:shared": ["/tmp/sentinel.png"]},
        last_wallpaper="old.png",
        last_images=["old-image.png"],
    )
    save_state(original)
    before = load_state().to_dict()

    next_result = switch_once("P", dry_run=True, rng=random.Random(1))
    assert next_result.applied is False
    assert load_state().to_dict() == before

    black_result = black_screen("P", dry_run=True)
    assert black_result.applied is False
    assert black_result.wallpaper.name == "P-dry-run-black.png"
    assert black_result.wallpaper.exists()
    assert not (tmp_path / "cache" / "P-black.png").exists()
    assert load_state().to_dict() == before

    resume_result = resume("P", dry_run=True)
    assert resume_result.applied is False
    assert load_state().to_dict() == before


def test_solid_black_applies_before_generating_fallback(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    calls = []

    class _SolidBlackSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def supports_solid_black(self, desktop: str = "auto") -> bool:
            calls.append(("supports", desktop))
            return True

        def apply_black(self, image_path=None, desktop: str = "auto"):
            calls.append(("apply_black", image_path, desktop))
            return ["solid-black"]

    def fake_detect_monitors():
        calls.append(("detect_monitors",))
        return [service.Monitor("A", 100, 80, 0, 0)]

    def fake_compose_black(monitors, output_path):
        calls.append(("compose_black", len(monitors), Path(output_path).name))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"black")
        return Path(output_path)

    monkeypatch.setattr(service, "DesktopSetter", _SolidBlackSetter)
    monkeypatch.setattr(service, "detect_monitors", fake_detect_monitors)
    monkeypatch.setattr(service, "compose_black", fake_compose_black)

    result = black_screen("P", dry_run=False)

    assert calls[:5] == [
        ("supports", "unknown"),
        ("apply_black", None, "unknown"),
        ("apply_black", None, "unknown"),
        ("detect_monitors",),
        ("compose_black", 1, "P-black.png"),
    ]
    assert result.wallpaper.name == "P-black.png"
    assert load_state().black_screen is True


def test_live_next_uses_alternating_prebuilt_files(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)

    first = switch_once("P", dry_run=False, rng=random.Random(3))
    first_state = load_state()
    second = switch_once("P", dry_run=False, rng=random.Random(4))
    second_state = load_state()
    preview = switch_once("P", dry_run=True, rng=random.Random(5))

    assert first.wallpaper.name == "P-active-1.png"
    assert second.wallpaper.name == "P-active-0.png"
    assert first.wallpaper != second.wallpaper
    assert first_state.wallpaper_slot == 1
    assert second_state.wallpaper_slot == 0
    assert preview.wallpaper.name == "P-dry-run.png"
    assert load_state().wallpaper_slot == second_state.wallpaper_slot


def test_save_current_wallpaper_copies_composite_without_changing_state(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    current = switch_once("P", dry_run=False, rng=random.Random(3))
    before = load_state().to_dict()
    destination = tmp_path / "saved" / "desktop.png"

    saved = save_current_wallpaper(destination)

    assert saved == destination.resolve()
    assert saved.read_bytes() == current.wallpaper.read_bytes()
    assert load_state().to_dict() == before


def test_save_current_wallpaper_requires_force_to_overwrite(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    current = switch_once("P", dry_run=False, rng=random.Random(3))
    destination = tmp_path / "desktop.png"
    destination.write_bytes(b"existing")
    destination.chmod(0o600)

    with pytest.raises(FileExistsError, match="Destination already exists"):
        save_current_wallpaper(destination)

    staged_modes = []
    original_copyfileobj = service.shutil.copyfileobj

    def observe_staged_mode(source_file, destination_file):
        staged_modes.append(os.fstat(destination_file.fileno()).st_mode & 0o777)
        original_copyfileobj(source_file, destination_file)

    monkeypatch.setattr(service.shutil, "copyfileobj", observe_staged_mode)
    saved = save_current_wallpaper(destination, overwrite=True)
    assert staged_modes == [0o600]
    assert saved.read_bytes() == current.wallpaper.read_bytes()
    assert saved.stat().st_mode & 0o777 == 0o600


def test_save_current_wallpaper_new_file_respects_umask(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    switch_once("P", dry_run=False, rng=random.Random(3))
    destination = tmp_path / "desktop.png"

    previous_umask = os.umask(0o077)
    try:
        saved = save_current_wallpaper(destination)
    finally:
        os.umask(previous_umask)

    assert saved.stat().st_mode & 0o777 == 0o600


def test_save_current_wallpaper_requires_explicit_png_file(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    switch_once("P", dry_run=False, rng=random.Random(3))
    directory = tmp_path / "exports.png"
    directory.mkdir()

    with pytest.raises(ValueError, match="must use a .png extension"):
        save_current_wallpaper(tmp_path / "desktop.jpg")
    with pytest.raises(ValueError, match="not a directory"):
        save_current_wallpaper(directory)


def test_save_current_wallpaper_rejects_symlink_without_touching_target(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    switch_once("P", dry_run=False, rng=random.Random(3))
    target = tmp_path / "unrelated.png"
    target.write_bytes(b"unrelated")
    destination = tmp_path / "desktop.png"
    destination.symlink_to(target)

    with pytest.raises(ValueError, match="must not be a symbolic link"):
        save_current_wallpaper(destination, overwrite=True)

    assert destination.is_symlink()
    assert target.read_bytes() == b"unrelated"


def test_save_current_wallpaper_copy_failure_preserves_destination(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    switch_once("P", dry_run=False, rng=random.Random(3))
    destination = tmp_path / "desktop.png"
    destination.write_bytes(b"existing")

    def fail_mid_copy(source_file, destination_file):
        destination_file.write(source_file.read(8))
        raise OSError("simulated copy failure")

    monkeypatch.setattr(service.shutil, "copyfileobj", fail_mid_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        save_current_wallpaper(destination, overwrite=True)

    assert destination.read_bytes() == b"existing"
    assert list(tmp_path.glob(".desktop.png.*.tmp")) == []


def test_save_current_wallpaper_holds_rotation_lock_until_snapshot_is_staged(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    current = switch_once("P", dry_run=False, rng=random.Random(3))
    expected = current.wallpaper.read_bytes()
    destination = tmp_path / "desktop.png"
    copy_started = threading.Event()
    allow_copy_to_finish = threading.Event()
    rotation_started = threading.Event()
    rotation_finished = threading.Event()
    errors: list[BaseException] = []
    original_copyfileobj = service.shutil.copyfileobj

    def delayed_copy(source_file, destination_file):
        destination_file.write(source_file.read(8))
        copy_started.set()
        if not allow_copy_to_finish.wait(timeout=2):
            raise TimeoutError("test did not release staged copy")
        original_copyfileobj(source_file, destination_file)

    def save_worker():
        try:
            save_current_wallpaper(destination)
        except BaseException as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)

    def rotate_worker():
        rotation_started.set()
        try:
            switch_once("P", dry_run=False, rng=random.Random(4))
            switch_once("P", dry_run=False, rng=random.Random(5))
        except BaseException as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)
        finally:
            rotation_finished.set()

    monkeypatch.setattr(service.shutil, "copyfileobj", delayed_copy)
    save_thread = threading.Thread(target=save_worker)
    rotate_thread = threading.Thread(target=rotate_worker)
    save_thread.start()
    assert copy_started.wait(timeout=2)
    rotate_thread.start()
    assert rotation_started.wait(timeout=2)

    assert not rotation_finished.wait(timeout=0.1)
    allow_copy_to_finish.set()
    save_thread.join(timeout=3)
    rotate_thread.join(timeout=3)

    assert not save_thread.is_alive()
    assert not rotate_thread.is_alive()
    assert errors == []
    assert destination.read_bytes() == expected


def test_save_current_wallpaper_serializes_with_black_screen(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    current = black_screen("P", dry_run=False)
    expected = current.wallpaper.read_bytes()
    destination = tmp_path / "desktop.png"
    copy_started = threading.Event()
    allow_copy_to_finish = threading.Event()
    black_invoked = threading.Event()
    solid_black_applied = threading.Event()
    compose_started = threading.Event()
    errors: list[BaseException] = []
    solid_black_calls = []
    original_copyfileobj = service.shutil.copyfileobj

    class _SolidBlackSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def supports_solid_black(self, desktop: str = "auto") -> bool:
            return True

        def apply_black(self, image_path=None, desktop: str = "auto"):
            solid_black_calls.append((image_path, desktop))
            if image_path is None:
                solid_black_applied.set()
            return ["solid-black"]

    def delayed_copy(source_file, destination_file):
        destination_file.write(source_file.read(8))
        copy_started.set()
        if not allow_copy_to_finish.wait(timeout=2):
            raise TimeoutError("test did not release staged copy")
        original_copyfileobj(source_file, destination_file)

    def replacement_black(monitors, output_path):
        compose_started.set()
        Path(output_path).write_bytes(b"replacement-black-wallpaper")
        return Path(output_path)

    def save_worker():
        try:
            save_current_wallpaper(destination)
        except BaseException as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)

    def black_worker():
        black_invoked.set()
        try:
            black_screen("P", dry_run=False)
        except BaseException as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)

    monkeypatch.setattr(service.shutil, "copyfileobj", delayed_copy)
    monkeypatch.setattr(service, "compose_black", replacement_black)
    monkeypatch.setattr(service, "DesktopSetter", _SolidBlackSetter)
    save_thread = threading.Thread(target=save_worker)
    black_thread = threading.Thread(target=black_worker)
    save_thread.start()
    assert copy_started.wait(timeout=2)
    black_thread.start()
    assert black_invoked.wait(timeout=2)
    assert solid_black_applied.wait(timeout=0.5)

    assert solid_black_calls == [(None, "unknown")]
    assert not compose_started.wait(timeout=0.1)
    allow_copy_to_finish.set()
    save_thread.join(timeout=3)
    black_thread.join(timeout=3)

    assert not save_thread.is_alive()
    assert not black_thread.is_alive()
    assert errors == []
    assert solid_black_calls == [(None, "unknown"), (None, "unknown")]
    assert destination.read_bytes() == expected


def test_save_current_wallpaper_rejects_missing_source(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    missing = tmp_path / "missing.png"
    save_state(RuntimeState(last_wallpaper=str(missing)))

    with pytest.raises(FileNotFoundError, match="Current wallpaper file is missing"):
        save_current_wallpaper(tmp_path / "desktop.png")


def test_save_current_wallpaper_rejects_special_destination(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    switch_once("P", dry_run=False, rng=random.Random(3))
    destination = tmp_path / "desktop.png"
    os.mkfifo(destination)

    with pytest.raises(ValueError, match="must be a regular file"):
        save_current_wallpaper(destination, overwrite=True)


def test_save_current_wallpaper_rejects_cache_file_as_destination(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    current = switch_once("P", dry_run=False, rng=random.Random(3))
    before = current.wallpaper.read_bytes()

    with pytest.raises(ValueError, match="must differ from the current cache file"):
        save_current_wallpaper(current.wallpaper, overwrite=True)

    assert current.wallpaper.read_bytes() == before


def test_save_current_wallpaper_requires_live_wallpaper(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="run 'next' first"):
        save_current_wallpaper(tmp_path / "desktop.png")


def test_same_mode_uses_one_shared_image_for_every_monitor(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    cfg = service.load_config()
    cfg.get_profile("P").mode = "same"
    save_config(cfg)
    captured = {}

    def fake_compose_per_monitor(monitors, image_by_monitor, output_path):
        captured["monitors"] = [monitor.name for monitor in monitors]
        captured["image_by_monitor"] = dict(image_by_monitor)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"same")
        return Path(output_path)

    monkeypatch.setattr(service, "compose_per_monitor", fake_compose_per_monitor)

    result = switch_once("P", dry_run=False, rng=random.Random(7))
    state = load_state()

    assert result.action == "next"
    assert len(result.images) == 1
    assert captured["monitors"] == ["A", "B"]
    assert captured["image_by_monitor"] == {"A": result.images[0], "B": result.images[0]}
    assert "profile:P:same" in state.remaining


def test_live_black_screen_stays_paused_until_live_next(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    black_screen("P", dry_run=False)
    state = load_state()
    assert state.black_screen is True
    assert state.paused is True

    switch_once("P", dry_run=False, rng=random.Random(2))
    state = load_state()
    assert state.black_screen is False
    assert state.paused is False
    assert state.last_images


def test_missing_shared_folder_uses_nonsticky_black_fallback(monkeypatch, tmp_path: Path):
    calls = []

    class _FakeDesktopSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def apply(self, *_args, **_kwargs):
            calls.append(("apply",))

        def apply_black(self, image_path, desktop: str = "auto"):
            calls.append(("apply_black", Path(image_path).name, desktop, self.dry_run))

    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0")
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(
        Config(
            active_profile="P",
            profiles={"P": Profile(name="P", shared_folders=[str(tmp_path / "missing")], desktop="unknown")},
        )
    )
    save_state(RuntimeState(paused=True, black_screen=True, active_profile="P"))

    result = switch_once("P", dry_run=False, rng=random.Random(2))
    state = load_state()

    assert result.action == "black-fallback"
    assert result.images == []
    assert result.wallpaper.name == "P-active-1.png"
    assert result.wallpaper.exists()
    assert calls == [("apply_black", "P-active-1.png", "unknown", False)]
    assert state.black_screen is False
    assert state.paused is False
    assert state.last_images == []


def test_missing_per_monitor_folder_falls_back_without_consuming_queues(monkeypatch, tmp_path: Path):
    calls = []

    class _FakeDesktopSetter:
        def __init__(self, dry_run: bool = False):
            self.dry_run = dry_run

        def apply(self, *_args, **_kwargs):
            calls.append(("apply",))

        def apply_black(self, image_path, desktop: str = "auto"):
            calls.append(("apply_black", Path(image_path).name, desktop, self.dry_run))

    image_dir = tmp_path / "images"
    _write_images(image_dir, count=1)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", "A:100x80+0+0,B:120x80+100+0")
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(
                    name="P",
                    mode="per-monitor",
                    monitor_folders={"A": [str(image_dir)], "B": [str(tmp_path / "missing-drive")]},
                    desktop="unknown",
                )
            },
        )
    )

    result = switch_once("P", dry_run=False, rng=random.Random(2))
    state = load_state()

    assert result.action == "black-fallback"
    assert result.images == []
    assert calls == [("apply_black", "P-active-1.png", "unknown", False)]
    assert state.remaining == {}


def test_dry_run_black_fallback_does_not_persist_state(monkeypatch, tmp_path: Path):
    _setup_profile(monkeypatch, tmp_path)
    cfg = service.load_config()
    profile = cfg.get_profile("P")
    profile.shared_folders = [str(tmp_path / "missing")]
    save_config(cfg)
    original = RuntimeState(
        paused=True,
        black_screen=True,
        active_profile="P",
        remaining={"profile:P:shared": ["/tmp/sentinel.png"]},
        last_wallpaper="old.png",
        last_images=["old-image.png"],
    )
    save_state(original)
    before = load_state().to_dict()

    result = switch_once("P", dry_run=True, rng=random.Random(2))

    assert result.action == "black-fallback"
    assert result.applied is False
    assert result.wallpaper.name == "P-dry-run.png"
    assert result.wallpaper.exists()
    assert load_state().to_dict() == before
