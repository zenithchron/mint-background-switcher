from pathlib import Path

import pytest

from mint_background_switcher.autostart import desktop_exec_line, disable_autostart, enable_autostart


def test_desktop_exec_line_quotes_spaces_and_escapes_percent():
    line = desktop_exec_line(["/tmp/Mint Background Switcher/run", "50%", "tray"])
    assert '"/tmp/Mint Background Switcher/run"' in line
    assert "50%%" in line
    assert line.endswith(" tray")


def test_desktop_exec_line_rejects_control_chars():
    with pytest.raises(ValueError):
        desktop_exec_line(["bad\narg"])


def test_enable_autostart_defaults_to_safe_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = enable_autostart(["/tmp/Mint Background Switcher/run", "safe-start"], delay_seconds=15)
    text = path.read_text(encoding="utf-8")
    assert 'Exec="/tmp/Mint Background Switcher/run" safe-start' in text
    assert "X-GNOME-Autostart-Delay=15" in text
    assert "Comment=Safely start wallpaper rotation after Cinnamon is ready" in text


def test_enable_autostart_without_command_uses_safe_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("mint_background_switcher.autostart.source_wrapper_argv", lambda: ["/tmp/run"])

    path = enable_autostart()

    assert "Exec=/tmp/run safe-start" in path.read_text(encoding="utf-8")


def test_disable_autostart_removes_all_mbs_entries(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    autostart_dir = tmp_path / "config" / "autostart"
    autostart_dir.mkdir(parents=True)
    primary = autostart_dir / "mint-background-switcher.desktop"
    primary.write_text("Exec=mint-background-switcher safe-start\n", encoding="utf-8")
    legacy = autostart_dir / "old.desktop"
    legacy.write_text("Exec=/tmp/mint_background_switcher tray\n", encoding="utf-8")
    unrelated = autostart_dir / "keep.desktop"
    unrelated.write_text("Exec=something-else\n", encoding="utf-8")

    removed = disable_autostart()

    assert sorted(p.name for p in removed) == ["mint-background-switcher.desktop", "old.desktop"]
    assert not primary.exists()
    assert not legacy.exists()
    assert unrelated.exists()
