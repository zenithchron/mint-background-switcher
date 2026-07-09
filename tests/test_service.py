import random
from pathlib import Path

from PIL import Image

from mint_background_switcher import service
from mint_background_switcher.config import Config, Profile, save_config
from mint_background_switcher.service import black_screen, resume, switch_once
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

    assert calls[:4] == [
        ("supports", "unknown"),
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
