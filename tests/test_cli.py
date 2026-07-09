import pytest

from mint_background_switcher import __version__
from mint_background_switcher.cli import build_parser


def test_version_flag_reports_package_version(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])

    assert exc.value.code == 0
    assert f"mint-background-switcher {__version__}" in capsys.readouterr().out
