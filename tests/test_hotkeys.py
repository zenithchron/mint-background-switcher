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
