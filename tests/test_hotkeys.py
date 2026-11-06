import pytest
from ast import literal_eval

from mint_background_switcher.config import Config, Profile, save_config
from mint_background_switcher import hotkeys


def test_shell_command_quotes_paths_with_spaces():
    command = hotkeys.shell_command(["/tmp/Mint Background Switcher/run", "black-screen"])
    assert command == "'/tmp/Mint Background Switcher/run' black-screen"


def test_shell_command_rejects_control_chars():
    with pytest.raises(ValueError):
        hotkeys.shell_command(["bad\narg"])


def test_hotkey_dry_run_preserves_existing_custom_list_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/Mint Background Switcher/run"])

    commands = hotkeys.register_cinnamon_black_hotkey(dry_run=True)

    assert commands[0][:4] == ["gsettings", "set", hotkeys.ROOT_SCHEMA, "custom-list"]
    assert hotkeys.CUSTOM_PATH in commands[0][4]
    assert literal_eval(commands[2][-1]) == "'/tmp/Mint Background Switcher/run' black-screen"


def test_hotkey_dry_run_registers_next_action_with_profile_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P", next_hotkey="<Ctrl>n")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/Mint Background Switcher/run"])

    commands = hotkeys.register_cinnamon_hotkey("next", dry_run=True)

    assert hotkeys.HOTKEY_ACTIONS["next"].custom_path in commands[0][4]
    assert literal_eval(commands[1][-1]) == "Mint Background Switcher: Next"
    assert literal_eval(commands[2][-1]) == "'/tmp/Mint Background Switcher/run' next"
    assert literal_eval(commands[3][-1]) == ["<Ctrl>n"]


def test_hotkey_dry_run_uses_historic_black_screen_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    commands = hotkeys.register_cinnamon_black_hotkey(dry_run=True)

    assert hotkeys.CUSTOM_PATH in commands[0][4]
    assert literal_eval(commands[2][-1]) == "/tmp/mbs black-screen"
    assert literal_eval(commands[3][-1]) == ["<Primary><Alt>b"]


def test_hotkey_dry_run_rejects_unknown_action():
    with pytest.raises(ValueError):
        hotkeys.register_cinnamon_hotkey("bogus", dry_run=True)


def test_hotkey_dry_run_rejects_control_chars_in_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    with pytest.raises(ValueError):
        hotkeys.register_cinnamon_hotkey("black-screen", binding="bad\nbinding", dry_run=True)


def test_hotkey_dry_run_rejects_control_chars_in_command():
    with pytest.raises(ValueError):
        hotkeys.register_cinnamon_hotkey("next", command="bad\ncmd", dry_run=True)


def test_register_all_dry_run_covers_every_action(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P", next_hotkey="<Ctrl>n")}))
    monkeypatch.setattr(hotkeys.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(hotkeys, "source_wrapper_argv", lambda: ["/tmp/mbs"])

    results = hotkeys.register_all_cinnamon_hotkeys(command_prefix=["/opt/launcher"], dry_run=True)

    assert set(results) == set(hotkeys.HOTKEY_ACTIONS)
    for key, commands in results.items():
        spec = hotkeys.HOTKEY_ACTIONS[key]
        assert spec.custom_path in commands[0][4]
        assert literal_eval(commands[2][-1]) == f"/opt/launcher {spec.cli_command}"
    assert literal_eval(results["next"][3][-1]) == ["<Ctrl>n"]
    assert literal_eval(results["pause-resume"][3][-1]) == ["<Primary><Alt>p"]


def test_registered_hotkey_actions_reads_dconf_custom_list(monkeypatch):
    known = [
        hotkeys.HOTKEY_ACTIONS["black-screen"].custom_path,
        hotkeys.HOTKEY_ACTIONS["next"].custom_path,
    ]
    monkeypatch.setattr(hotkeys, "_existing_custom_list", lambda: known)
    assert hotkeys.registered_hotkey_actions() == ["next", "black-screen"]

    monkeypatch.setattr(hotkeys, "_existing_custom_list", lambda: [])
    assert hotkeys.registered_hotkey_actions() == []

    def boom():
        raise RuntimeError("dconf unavailable")

    monkeypatch.setattr(hotkeys, "_existing_custom_list", boom)
    assert hotkeys.registered_hotkey_actions() == []
