"""Autostart desktop entry management."""

from __future__ import annotations

import stat
from collections.abc import Sequence
from pathlib import Path

from .hotkeys import source_wrapper_argv
from .paths import autostart_file

AUTOSTART_MARKERS = ("mint-background-switcher", "mint_background_switcher")


def _desktop_exec_arg(arg: str) -> str:
    if any(ord(ch) < 32 for ch in arg):
        raise ValueError("Autostart command arguments must not contain control characters")
    escaped = arg.replace("%", "%%")
    if not escaped or any(ch.isspace() or ch in '"\\' for ch in escaped):
        escaped = '"' + escaped.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return escaped


def desktop_exec_line(argv: Sequence[str]) -> str:
    return " ".join(_desktop_exec_arg(str(arg)) for arg in argv)


def safe_start_command() -> list[str]:
    """Return the default low-risk autostart command.

    Autostart intentionally uses safe-start instead of tray.  The tray can still
    be launched manually, but login should not depend on AppIndicator/panel
    initialization and should not immediately change the wallpaper.
    """
    return source_wrapper_argv() + ["safe-start"]


def tray_command() -> list[str]:
    """Return the legacy tray command for explicit/manual use."""
    return source_wrapper_argv() + ["tray"]


def enable_autostart(command: Sequence[str] | str | None = None, *, delay_seconds: int = 20) -> Path:
    if command is None:
        exec_line = desktop_exec_line(safe_start_command())
    elif isinstance(command, str):
        exec_line = _desktop_exec_arg(command)
    else:
        exec_line = desktop_exec_line(command)
    path = autostart_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Mint Background Switcher\n"
        f"Exec={exec_line}\n"
        "Comment=Safely start wallpaper rotation after Cinnamon is ready\n"
        "X-GNOME-Autostart-enabled=true\n"
        f"X-GNOME-Autostart-Delay={max(0, int(delay_seconds))}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _entry_mentions_app(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in text for marker in AUTOSTART_MARKERS)


def disable_autostart(*, remove_all: bool = True) -> list[Path]:
    """Remove every known MBS autostart entry and return removed paths."""
    removed: list[Path] = []
    path = autostart_file()
    candidates = [path]
    if remove_all and path.parent.exists():
        candidates.extend(p for p in path.parent.glob("*.desktop") if p != path and _entry_mentions_app(p))
    for candidate in candidates:
        try:
            candidate.unlink()
            removed.append(candidate)
        except FileNotFoundError:
            pass
    return removed
