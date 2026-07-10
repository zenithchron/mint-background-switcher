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
