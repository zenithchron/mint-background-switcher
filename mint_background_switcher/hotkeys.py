"""Cinnamon hotkey registration helper.

Mint Background Switcher can register up to five rebindable Cinnamon custom
hotkeys (Next, Previous, Redraw Current, Pause/Resume, and Black screen).
Each action owns one ``org.cinnamon.desktop.keybindings.custom-keybinding``
object; the actions are defined in :data:`HOTKEY_ACTIONS` and registered with
:func:`register_cinnamon_hotkey` / :func:`register_all_cinnamon_hotkeys`.
"""

from __future__ import annotations

import shutil
import shlex
import subprocess
import sys
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path

from .config import load_config

CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
ROOT_SCHEMA = "org.cinnamon.desktop.keybindings"


def _custom_path(slug: str) -> str:
    return f"/org/cinnamon/desktop/keybindings/custom-keybindings/{slug}/"


@dataclass(frozen=True)
class HotkeyAction:
    """A single rebindable Cinnamon hotkey action."""

    key: str
    display_name: str
    custom_path: str
    cli_command: str


HOTKEY_ACTIONS: dict[str, HotkeyAction] = {
    "next": HotkeyAction(
        key="next",
        display_name="Mint Background Switcher: Next",
        custom_path=_custom_path("mint-background-switcher-next"),
        cli_command="next",
    ),
    "pause-resume": HotkeyAction(
        key="pause-resume",
        display_name="Mint Background Switcher: Pause/Resume",
        custom_path=_custom_path("mint-background-switcher-pause"),
        cli_command="pause-toggle",
    ),
    "black-screen": HotkeyAction(
        key="black-screen",
        display_name="Mint Background Switcher: Black Screen",
        custom_path=_custom_path("mint-background-switcher-black-screen"),
        cli_command="black-screen",
    ),
    "previous": HotkeyAction(
        key="previous",
        display_name="Mint Background Switcher: Previous",
        custom_path=_custom_path("mint-background-switcher-previous"),
        cli_command="previous",
    ),
    "redraw": HotkeyAction(
        key="redraw",
        display_name="Mint Background Switcher: Redraw Current",
        custom_path=_custom_path("mint-background-switcher-redraw"),
        cli_command="redraw-current",
    ),
}

# Kept for callers that only care about the historic black-screen hotkey.
CUSTOM_PATH = HOTKEY_ACTIONS["black-screen"].custom_path

DEFAULT_BINDINGS = {
    "next": "<Primary><Alt>n",
    "pause-resume": "<Primary><Alt>p",
    "black-screen": "<Primary><Alt>b",
    "previous": "<Primary><Alt>Left",
    "redraw": "<Primary><Alt>r",
}


def hotkey_action(key: str) -> HotkeyAction:
    try:
        return HOTKEY_ACTIONS[key]
    except KeyError:
        valid = ", ".join(f"{name!r}" for name in HOTKEY_ACTIONS)
        raise ValueError(f"Unknown hotkey action {key!r}; expected one of: {valid}") from None


def hotkey_binding_for(profile, action_key: str) -> str:
    """The saved binding for ``action_key`` on ``profile`` (with defaults)."""
    hotkey_action(action_key)
    if action_key == "next":
        return profile.next_hotkey or DEFAULT_BINDINGS["next"]
    if action_key == "pause-resume":
        return profile.pause_hotkey or DEFAULT_BINDINGS["pause-resume"]
    if action_key == "previous":
        return profile.previous_hotkey or DEFAULT_BINDINGS["previous"]
    if action_key == "redraw":
        return profile.redraw_hotkey or DEFAULT_BINDINGS["redraw"]
    return profile.black_hotkey or DEFAULT_BINDINGS["black-screen"]


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


def registered_hotkey_actions() -> list[str]:
    """Action keys whose custom keybinding object already exists in dconf."""
    try:
        existing = _existing_custom_list()
    except Exception:
        return []
    return [key for key, spec in HOTKEY_ACTIONS.items() if spec.custom_path in existing]


def _run_commands(commands: list[list[str]]) -> None:
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings is required to register a Cinnamon hotkey")
    subprocess.run(commands[0], check=True)
    for cmd in commands[1:]:
        subprocess.run(cmd, check=True)


def register_cinnamon_hotkey(
    action: str,
    binding: str | None = None,
    command: str | None = None,
    dry_run: bool = False,
) -> list[list[str]]:
    """Register (or re-register) one Cinnamon custom hotkey.

    Returns the list of gsettings command argvs. With ``dry_run`` no gsettings
    call is executed. ``binding``/``command`` default to the active profile's
    saved value and the installed CLI, respectively.
    """
    spec = hotkey_action(action)
    cfg = load_config()
    profile = cfg.get_profile()
    if binding is None:
        binding = hotkey_binding_for(profile, spec.key)
    binding = _reject_control_chars(binding)
    if command is None:
        command = shell_command(source_wrapper_argv() + [spec.cli_command])
    else:
        command = _reject_control_chars(command)
    custom_list = _existing_custom_list()
    if spec.custom_path not in custom_list:
        custom_list.append(spec.custom_path)
    commands = [
        ["gsettings", "set", ROOT_SCHEMA, "custom-list", repr(custom_list)],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + spec.custom_path, "name", repr(spec.display_name)],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + spec.custom_path, "command", repr(command)],
        ["gsettings", "set", CUSTOM_SCHEMA + ":" + spec.custom_path, "binding", repr([binding])],
    ]
    if not dry_run:
        _run_commands(commands)
    return commands


def register_cinnamon_black_hotkey(
    binding: str | None = None,
    command: str | None = None,
    dry_run: bool = False,
) -> list[list[str]]:
    """Backward-compatible wrapper for the historic black-screen hotkey."""
    return register_cinnamon_hotkey("black-screen", binding=binding, command=command, dry_run=dry_run)


def register_all_cinnamon_hotkeys(
    command_prefix: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, list[list[str]]]:
    """Register all five hotkeys from the active profile's saved bindings.

    ``command_prefix`` (for example a managed launcher path) replaces the
    default wrapper argv in each registered command. Returns the gsettings
    command groups keyed by action.
    """
    cfg = load_config()
    profile = cfg.get_profile()
    results: dict[str, list[list[str]]] = {}
    for key, spec in HOTKEY_ACTIONS.items():
        command = shell_command(list(command_prefix) + [spec.cli_command]) if command_prefix else None
        results[key] = register_cinnamon_hotkey(
            key,
            binding=hotkey_binding_for(profile, key),
            command=command,
            dry_run=dry_run,
        )
    return results
