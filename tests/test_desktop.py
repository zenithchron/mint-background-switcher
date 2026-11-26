import subprocess
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher import desktop
from mint_background_switcher.desktop import DesktopSetter


def test_dry_run_apply_does_not_require_desktop_backend(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))

    assert DesktopSetter(dry_run=True).apply(image, "auto") == ["dry-run:auto"]


def test_cinnamon_apply_skips_unchanged_options_and_sets_new_uri(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    commands = []

    def fake_check_output(args, **_kwargs):
        assert args[:2] == ["gsettings", "get"]
        key = args[-1]
        if key == "picture-options":
            return "'spanned'\n"
        return "'old'\n"

    def fake_run(args, **_kwargs):
        commands.append(args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    assert DesktopSetter().apply(image, "cinnamon") == ["cinnamon"]

    assert [cmd[3] for cmd in commands] == ["picture-uri"]
    assert commands[0][-1] == desktop.file_uri(image)


def test_gnome_apply_sets_uris_before_revealing_wallpaper(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    commands = []

    def fake_check_output(args, **_kwargs):
        return "'old'\n"

    def fake_run(args, **_kwargs):
        commands.append(args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    assert DesktopSetter().apply(image, "gnome") == ["gnome"]

    assert [cmd[3] for cmd in commands] == ["picture-uri", "picture-uri-dark", "picture-options"]
    assert commands[0][-1] == desktop.file_uri(image)
    assert commands[1][-1] == desktop.file_uri(image)
    assert commands[2][-1] == "spanned"


def test_cinnamon_black_uses_color_mode_without_picture_uri(monkeypatch, tmp_path: Path):
    image = tmp_path / "black.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    commands = []

    def fake_check_output(args, **_kwargs):
        key = args[-1]
        values = {
            "background-transition": "'blend'\n",
            "background-fade": "true\n",
            "primary-color": "'#ffffff'\n",
            "secondary-color": "'#ffffff'\n",
            "color-shading-type": "'vertical'\n",
            "picture-options": "'spanned'\n",
        }
        return values.get(key, "''\n")

    def fake_run(args, **_kwargs):
        commands.append(args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    assert DesktopSetter().apply_black(image, "cinnamon") == ["cinnamon-black"]

    keys = [cmd[3] for cmd in commands]
    assert keys == [
        "primary-color",
        "secondary-color",
        "color-shading-type",
        "picture-options",
    ]
    assert "picture-uri" not in keys
    assert commands[-1][-1] == "none"


def test_mate_apply_disables_background_fade(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    commands = []

    def fake_check_output(args, **_kwargs):
        key = args[-1]
        if key == "background-fade":
            return "true\n"
        return "'old'\n"

    def fake_run(args, **_kwargs):
        commands.append(args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    assert DesktopSetter().apply(image, "mate") == ["mate"]

    assert commands[0][3:] == ["background-fade", "false"]
    assert [cmd[3] for cmd in commands] == ["background-fade", "picture-options", "picture-filename"]


def test_dry_run_apply_validates_output_exists(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        DesktopSetter(dry_run=True).apply(tmp_path / "missing.png", "auto")


def test_dry_run_black_validates_output_exists(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        DesktopSetter(dry_run=True).apply_black(tmp_path / "missing.png", "auto")


def test_gnome_mirror_lockscreen_writes_screensaver_schema(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    commands = []

    def fake_check_output(args, **_kwargs):
        return "'old'\n"

    def fake_run(args, **_kwargs):
        commands.append(args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    result = DesktopSetter().mirror_lockscreen(image, "gnome")

    assert result.status == desktop.LOCKSCREEN_MIRRORED
    assert [cmd[3] for cmd in commands] == ["picture-uri", "picture-uri-dark", "picture-options"]
    assert commands[0][:3] == ["gsettings", "set", "org.gnome.desktop.screensaver"]
    assert commands[0][-1] == desktop.file_uri(image)
    assert commands[2][-1] == "spanned"


def test_cinnamon_mirror_lockscreen_is_automatic_without_writes(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(
        desktop.subprocess,
        "check_output",
        lambda *_a, **_k: pytest.fail("Cinnamon mirroring must not read gsettings"),
    )
    monkeypatch.setattr(desktop.subprocess, "run", lambda *_a, **_k: pytest.fail("Cinnamon mirroring must not write gsettings"))

    result = DesktopSetter().mirror_lockscreen(image, "cinnamon")

    assert result.status == desktop.LOCKSCREEN_AUTOMATIC
    assert "Cinnamon" in result.detail


def test_mate_mirror_lockscreen_reports_unsupported_without_writes(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "run", lambda *_a, **_k: pytest.fail("unsupported desktops must not write gsettings"))

    result = DesktopSetter().mirror_lockscreen(image, "mate")

    assert result.status == desktop.LOCKSCREEN_UNSUPPORTED
    assert "keeps its own lock screen" in result.detail


def test_gnome_mirror_lockscreen_reports_failure_instead_of_raising(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)

    def fake_run(args, **_kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "check_output", lambda *_a, **_k: "'old'\n")
    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    result = DesktopSetter().mirror_lockscreen(image, "gnome")

    assert result.status == desktop.LOCKSCREEN_FAILED
    assert "Could not update the GNOME lock screen" in result.detail


def test_gnome_mirror_lockscreen_missing_gsettings_reports_failure(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: None)

    result = DesktopSetter().mirror_lockscreen(image, "gnome")

    assert result.status == desktop.LOCKSCREEN_FAILED
    assert "gsettings is not available" in result.detail


def test_dry_run_gnome_mirror_lockscreen_reports_dry_run_without_writes(monkeypatch, tmp_path: Path):
    image = tmp_path / "wall.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(image)
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)
    monkeypatch.setattr(desktop.subprocess, "run", lambda *_a, **_k: pytest.fail("dry run must not write"))

    result = DesktopSetter(dry_run=True).mirror_lockscreen(image, "gnome")

    assert result.status == desktop.LOCKSCREEN_DRY_RUN


def test_dry_run_mirror_lockscreen_missing_image_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        DesktopSetter(dry_run=True).mirror_lockscreen(tmp_path / "missing.png", "gnome")


def _fade_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    old = tmp_path / "old.png"
    new = tmp_path / "new.png"
    Image.new("RGB", (12, 12), (20, 20, 20)).save(old)
    Image.new("RGB", (12, 12), (230, 230, 230)).save(new)
    return old, new


def _cinnamon_gsettings_harness(monkeypatch) -> list:
    commands = []
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: "/usr/bin/gsettings" if cmd == "gsettings" else None)

    def fake_check_output(args, **_kwargs):
        assert args[:2] == ["gsettings", "get"]
        if args[-1] == "picture-options":
            return "'spanned'\n"
        return "'old'\n"

    monkeypatch.setattr(desktop.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(desktop.subprocess, "run", lambda args, **_kwargs: commands.append(args))
    return commands


def _picture_uri_sets(commands: list) -> list[str]:
    return [
        args[-1]
        for args in commands
        if len(args) >= 4 and args[:2] == ["gsettings", "set"] and args[-2] == "picture-uri"
    ]


def test_apply_with_fade_dry_run_applies_plain_without_frames(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)

    assert DesktopSetter(dry_run=True).apply_with_fade(new, old, 2.0, "cinnamon") == ["dry-run:cinnamon"]
    assert commands == []


def test_apply_with_fade_disabled_applies_plain(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)

    assert DesktopSetter().apply_with_fade(new, old, 0.0, "cinnamon") == ["cinnamon"]
    assert _picture_uri_sets(commands) == [desktop.file_uri(new)]


def test_apply_with_fade_missing_old_picture_applies_plain(monkeypatch, tmp_path: Path):
    _old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)

    assert DesktopSetter().apply_with_fade(new, tmp_path / "gone.png", 2.0, "cinnamon") == ["cinnamon"]
    assert _picture_uri_sets(commands) == [desktop.file_uri(new)]


def test_apply_with_fade_same_picture_applies_plain(monkeypatch, tmp_path: Path):
    _old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)

    assert DesktopSetter().apply_with_fade(new, new, 2.0, "cinnamon") == ["cinnamon"]
    assert _picture_uri_sets(commands) == [desktop.file_uri(new)]


def test_apply_with_fade_unsupported_backend_keeps_plain_apply_semantics(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    monkeypatch.setattr(desktop.shutil, "which", lambda cmd: None)

    with pytest.raises(RuntimeError):
        DesktopSetter().apply_with_fade(new, old, 2.0, "unknown")


def test_apply_with_fade_cinnamon_applies_frames_then_real_wallpaper(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)
    monkeypatch.setattr(desktop.time, "sleep", lambda *_args: None)

    assert DesktopSetter().apply_with_fade(new, old, 1.0, "cinnamon") == ["cinnamon"]

    uris = _picture_uri_sets(commands)
    assert uris[-1] == desktop.file_uri(new)
    frame_uris = uris[:-1]
    assert len(frame_uris) == 12
    frame_paths = [uri.removeprefix("file://") for uri in frame_uris]
    assert [Path(path).name for path in frame_paths] == [f"fade-{index:02d}.jpg" for index in range(1, 13)]
    assert all(Path(path).parent.name.startswith("mbs-fade-") for path in frame_paths)
    # Every frame file was cleaned up after the transition finished.
    assert all(not Path(path).exists() for path in frame_paths)
    # The compositor's own crossfade was suppressed for the duration of the fade.
    assert ["org.cinnamon.muffin", "background-transition", "none"] in [
        args[2:5] for args in commands if args[:2] == ["gsettings", "set"]
    ]


def test_apply_with_fade_gnome_applies_frames_then_real_wallpaper(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)
    monkeypatch.setattr(desktop.time, "sleep", lambda *_args: None)

    assert DesktopSetter().apply_with_fade(new, old, 1.0, "gnome") == ["gnome"]

    uris = _picture_uri_sets(commands)
    assert uris[-1] == desktop.file_uri(new)
    assert len(uris) == 13  # 12 blend frames, then the real wallpaper file
    # GNOME has no Cinnamon compositor to suppress.
    assert [args for args in commands if args[:2] == ["gsettings", "set"] and args[2] == "org.cinnamon.muffin"] == []


def test_apply_with_fade_frame_failure_falls_back_to_plain_apply(monkeypatch, tmp_path: Path):
    old, new = _fade_fixtures(tmp_path)
    commands = _cinnamon_gsettings_harness(monkeypatch)
    monkeypatch.setattr(desktop, "build_fade_frames", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))

    assert DesktopSetter().apply_with_fade(new, old, 1.0, "cinnamon") == ["cinnamon"]
    # The plain fallback still applied the real wallpaper exactly once.
    assert _picture_uri_sets(commands) == [desktop.file_uri(new)]
