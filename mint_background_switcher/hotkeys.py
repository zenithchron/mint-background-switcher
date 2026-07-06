"""Cinnamon hotkey registration helper."""

from __future__ import annotations

import shutil
import shlex
import subprocess
import sys
from ast import literal_eval
from pathlib import Path

from .config import load_config

CUSTOM_PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/mint-background-switcher-black-screen/"
CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
ROOT_SCHEMA = "org.cinnamon.desktop.keybindings"


def _reject_control_chars(arg: str) -> str:
    if any(ord(ch) < 32 for ch in arg):
        raise ValueError("Command arguments must not contain control characters")
    return arg


def source_wrapper_argv() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    wrapper = root / "scripts" / "mint-background-switcher"
    if wrapper.exists():
        return [str(wrapper)]
    exe = shutil.which("mint-background-switcher")
    if exe:
        return [exe]
    return [sys.executable, "-m", "mint_background_switcher"]


def shell_command(argv: list[str]) -> str:
    return shlex.join([_reject_control_chars(str(arg)) for arg in argv])


def source_wrapper_command() -> str:
    return shell_command(source_wrapper_argv())


def _existing_custom_list() -> list[str]:
    if not shutil.which("gsettings"):
        return []
    existing_raw = subprocess.run(
        ["gsettings", "get", ROOT_SCHEMA, "custom-list"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    try:
        parsed = literal_eval(existing_raw.strip() or "[]")
    except (SyntaxError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def register_cinnamon_black_hotkey(binding: str | None = None, command: str | None = None, dry_run: bool = False) -> list[list[str]]:
    cfg = load_config()
    profile = cfg.get_profile()
    binding = _reject_control_chars(binding or profile.black_hotkey)
    command = _reject_control_chars(command) if command is not None else shell_command(source_wrapper_argv() + ["black-screen"])
    custom_list = _existing_custom_list()
    if CUSTOM_PATH not in custom_list:
        custom_list.append(CUSTOM_PATH)
    commands = [
        ["gsettings", "set", ROOT_SCHEMA, "custom-list", repr(custom_list)],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + CUSTOM_PATH, "name", "'Mint Background Switcher: Black Screen'"],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + CUSTOM_PATH, "command", repr(command)],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + CUSTOM_PATH, "binding", repr([binding])],
    ]
    if dry_run:
        return commands
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings is required to register a Cinnamon hotkey")
    subprocess.run(commands[0], check=True)
    for cmd in commands[1:]:
        subprocess.run(cmd, check=True)
    return commands
