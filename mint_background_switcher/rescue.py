"""Built-in emergency rescue helpers.

These helpers intentionally prefer disabling Mint Background Switcher and
restoring Cinnamon to a boring, safe state over preserving the current wallpaper.
They are designed for use from a TTY when Cinnamon boots without panel/menu.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .autostart import disable_autostart
from .paths import xdg_cache_dir, xdg_config_dir


@dataclass(slots=True)
class RescueResult:
    mode: str
    backup_dir: Path
    actions: list[str] = field(default_factory=list)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _home() -> Path:
    return Path.home()


def _backup_root() -> Path:
    return _home() / "mbs-rescue"


def _run(args: list[str], actions: list[str], *, timeout: float = 15.0) -> None:
    try:
        subprocess.run(args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        actions.append("ran: " + " ".join(args))
    except (OSError, subprocess.TimeoutExpired) as exc:
        actions.append("skipped/failed: " + " ".join(args) + f" ({exc})")


def _move_to_backup(path: Path, backup_dir: Path, name: str, actions: list[str]) -> None:
    if not path.exists():
        return
    target = backup_dir / name
    try:
        shutil.move(str(path), str(target))
        actions.append(f"moved {path} -> {target}")
    except OSError as exc:
        actions.append(f"could not move {path}: {exc}")


def _copy_to_backup(path: Path, backup_dir: Path, name: str, actions: list[str]) -> None:
    if not path.exists():
        return
    target = backup_dir / name
    try:
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)
        actions.append(f"copied {path} -> {target}")
    except OSError as exc:
        actions.append(f"could not copy {path}: {exc}")


def _kill_matching_processes(pattern: str, actions: list[str]) -> None:
    """Terminate matching MBS processes without killing this rescue command."""
    pgrep = shutil.which("pgrep")
    if not pgrep:
        actions.append("skipped process cleanup: pgrep not available")
        return
    user = os.environ.get("USER") or str(os.getuid())
    try:
        result = subprocess.run(
            [pgrep, "-u", user, "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        actions.append(f"skipped process cleanup for {pattern!r}: {exc}")
        return
    protected = {os.getpid(), os.getppid()}
    killed = 0
    for raw_pid in result.stdout.split():
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if pid in protected:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except ProcessLookupError:
            pass
        except OSError as exc:
            actions.append(f"could not terminate pid {pid}: {exc}")
    actions.append(f"terminated {killed} process(es) matching {pattern!r}")


def reset_wallpaper(actions: list[str]) -> None:
    if shutil.which("dbus-run-session") and shutil.which("gsettings"):
        _run(["dbus-run-session", "--", "gsettings", "set", "org.cinnamon.desktop.background", "picture-options", "none"], actions)
        _run(["dbus-run-session", "--", "gsettings", "set", "org.cinnamon.desktop.background", "primary-color", "#000000"], actions)
        _run(["dbus-run-session", "--", "gsettings", "set", "org.cinnamon.desktop.background", "secondary-color", "#000000"], actions)
        _run(["dbus-run-session", "--", "gsettings", "reset", "org.cinnamon.desktop.background", "picture-uri"], actions)
        _run(["dbus-run-session", "--", "gsettings", "reset", "org.cinnamon.muffin", "background-transition"], actions)
        _run(["dbus-run-session", "--", "gsettings", "reset", "org.nemo.desktop", "background-fade"], actions)
    else:
        actions.append("skipped gsettings wallpaper reset: dbus-run-session or gsettings not available")


def reset_cinnamon_settings(backup_dir: Path, actions: list[str]) -> None:
    dconf_dir = _home() / ".config" / "dconf"
    monitors_xml = _home() / ".config" / "monitors.xml"
    _copy_to_backup(dconf_dir, backup_dir, "dconf.backup", actions)
    _copy_to_backup(monitors_xml, backup_dir, "monitors.xml.backup", actions)
    try:
        monitors_xml.unlink()
        actions.append(f"removed {monitors_xml}")
    except FileNotFoundError:
        pass
    except OSError as exc:
        actions.append(f"could not remove {monitors_xml}: {exc}")

    if shutil.which("dbus-run-session") and shutil.which("dconf"):
        _run(["dbus-run-session", "--", "dconf", "reset", "-f", "/org/cinnamon/"], actions)
        _run(["dbus-run-session", "--", "dconf", "reset", "-f", "/org/nemo/desktop/"], actions)
    else:
        actions.append("skipped dconf reset: dbus-run-session or dconf not available")


def run_rescue(*, full: bool = False, reboot: bool = False) -> RescueResult:
    mode = "full" if full else "light"
    backup_dir = _backup_root() / _timestamp()
    backup_dir.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    if shutil.which("sudo"):
        _run(["sudo", "dmesg", "-n", "1"], actions)
        if full and not os.environ.get("DISPLAY"):
            _run(["sudo", "systemctl", "stop", "lightdm"], actions)

    for removed in disable_autostart():
        actions.append(f"removed autostart {removed}")

    _kill_matching_processes("mint-background-switcher", actions)
    _kill_matching_processes("mint_background_switcher", actions)

    _move_to_backup(xdg_config_dir(), backup_dir, "mint-background-switcher.config", actions)
    _move_to_backup(xdg_cache_dir(), backup_dir, "mint-background-switcher.cache", actions)

    reset_wallpaper(actions)
    if full:
        reset_cinnamon_settings(backup_dir, actions)

    result = RescueResult(mode=mode, backup_dir=backup_dir, actions=actions)
    if reboot:
        if shutil.which("sudo"):
            _run(["sudo", "reboot"], actions, timeout=5.0)
        else:
            _run(["reboot"], actions, timeout=5.0)
    return result
