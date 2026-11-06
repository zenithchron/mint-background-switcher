import pytest

from mint_background_switcher import __version__, cli
from mint_background_switcher.cli import build_parser


def test_version_flag_reports_package_version(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])

    assert exc.value.code == 0
    assert f"mint-background-switcher {__version__}" in capsys.readouterr().out


def test_save_current_command_passes_destination_and_force(monkeypatch, capsys, tmp_path):
    destination = tmp_path / "saved.png"
    calls = []

    def fake_save_current(path, *, overwrite=False):
        calls.append((path, overwrite))
        return destination

    monkeypatch.setattr(cli, "save_current_wallpaper", fake_save_current)

    assert cli.main(["save-current", str(destination), "--force"]) == 0
    assert calls == [(str(destination), True)]
    assert capsys.readouterr().out.strip() == str(destination)


def test_pause_toggle_command_flips_paused_flag(monkeypatch, tmp_path):
    from mint_background_switcher.state import load_state

    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    assert cli.main(["pause-toggle"]) == 0
    assert load_state().paused is True
    assert cli.main(["pause-toggle"]) == 0
    assert load_state().paused is False


def test_register_hotkey_dry_run_selects_action(monkeypatch, tmp_path, capsys):
    import mint_background_switcher.hotkeys as hotkeys
    from mint_background_switcher.config import Config, Profile, save_config

    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P", next_hotkey="<Ctrl>n")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    assert cli.main(["register-hotkey", "--action", "next", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "/tmp/mbs next" in out
    assert hotkeys.HOTKEY_ACTIONS["next"].custom_path in out

    assert cli.main(["register-hotkey", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "/tmp/mbs black-screen" in out
    assert "pause-toggle" not in out


def test_register_hotkey_all_dry_run_covers_every_action(monkeypatch, tmp_path, capsys):
    import mint_background_switcher.hotkeys as hotkeys
    from mint_background_switcher.config import Config, Profile, save_config

    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    assert cli.main(["register-hotkey", "--all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "#next " in out
    assert "#pause-resume " in out
    assert "#black-screen " in out


def test_register_hotkey_all_rejects_explicit_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["register-hotkey", "--all", "--binding", "<Ctrl>b", "--dry-run"])
    assert exc.value.code == 2
