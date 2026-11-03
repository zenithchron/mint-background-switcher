"""Run conditions that pause scheduled wallpaper switching.

Inspired by John's Background Switcher's switching conditions (SW-07..SW-11):
a profile can pause *scheduled* background switching while local conditions
hold (a named process is running, the laptop is on battery, a VNC/remote
session is active, the session has not been idle long enough, or the session
is locked / the screensaver is active).

Explicit user actions always apply the wallpaper: these conditions are only
consulted by the background loop before a scheduled switch.

Every probe fails open: when a condition cannot be detected (a desktop with
no battery, no ``xprintidle``, no reachable screensaver D-Bus service), the
condition never blocks switching.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

from .config import Profile

# Process names (``comm``) that identify a running VNC/remote-desktop server.
VNC_SERVER_PROCESSES = frozenset(
    {
        "x11vnc",
        "xvnc",
        "vncserver",
        "tigervncserver",
        "turbovncserver",
        "kasmvncserver",
        "vncagent",
    }
)

# (bus name, object path, boolean methods) for known lockers/screensavers.
_LOCK_PROBES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("org.cinnamon.ScreenSaver", "/org/cinnamon/ScreenSaver", ("IsLocked", "IsActive")),
    ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", ("IsLocked",)),
    ("org.lightdm.Status", "/org/lightdm/Status", ("IsScreenLocked",)),
)


def _iter_comms(proc_root: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(pid, comm)`` pairs for every readable process under ``proc_root``."""
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (proc_root / entry.name / "comm").read_text().strip()
        except OSError:
            continue
        if comm:
            yield int(entry.name), comm


def process_running(name: str, proc_root: Path = Path("/proc")) -> bool:
    """Return True when a process with the given name is running.

    The match is case-insensitive and exact against the process ``comm``
    (its executable name, as shown by ``ps -c``); command-line arguments do
    not match. The switcher's own process never matches.
    """
    wanted = str(name).strip().casefold()
    if not wanted:
        return False
    own_pid = os.getpid()
    for pid, comm in _iter_comms(proc_root):
        if pid == own_pid:
            continue
        if comm.casefold() == wanted:
            return True
    return False


def remote_session_active(proc_root: Path = Path("/proc")) -> bool:
    """Return True when a known VNC/remote-desktop server process is running."""
    for _pid, comm in _iter_comms(proc_root):
        if comm.lower() in VNC_SERVER_PROCESSES:
            return True
    return False


def _read_sysfs_file(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def power_state(sysfs_root: Path = Path("/sys/class/power_supply")) -> str:
    """Classify local power as ``"battery"``, ``"ac"``, or ``"unknown"``.

    ``"battery"`` means a battery is present and actually discharging with no
    AC source online (a laptop running on battery). ``"ac"`` means AC power
    is online or a battery is charging. ``"unknown"`` covers desktops without
    a battery and unreadable power data; battery-based conditions treat it as
    inactive rather than blocking.
    """
    try:
        devices = list(sysfs_root.iterdir())
    except OSError:
        return "unknown"
    if not devices:
        return "unknown"
    battery_statuses: list[str] = []
    ac_online = False
    for device in devices:
        device_type = (_read_sysfs_file(device / "Type") or "").lower()
        if device_type == "battery":
            status = (_read_sysfs_file(device / "status") or "").lower()
            battery_statuses.append(status)
        elif device_type in {"mains", "ac", "usb"}:
            if _read_sysfs_file(device / "online") == "1":
                ac_online = True
    if not battery_statuses:
        return "unknown"
    if ac_online:
        return "ac"
    if any(status in {"charging", "online"} for status in battery_statuses):
        return "ac"
    if any(status == "discharging" for status in battery_statuses):
        return "battery"
    return "unknown"


def session_idle_seconds() -> float | None:
    """Return the session idle time in seconds, or None when it cannot be read.

    Uses ``xprintidle`` (which reports milliseconds against the current X
    session) when it is installed. Any failure — missing tool, no display,
    timeout, unexpected output — yields None so callers fail open.
    """
    executable = shutil.which("xprintidle")
    if executable is None:
        return None
    try:
        output = subprocess.run(
            [executable],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if output.returncode != 0:
        return None
    try:
        return int(output.stdout.strip()) / 1000.0
    except ValueError:
        return None


def _probe_gdbus(service: str, object_path: str, method: str) -> bool | None:
    """Call a boolean D-Bus method via ``gdbus``; None when it cannot be answered."""
    if shutil.which("gdbus") is None:
        return None
    try:
        output = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                service,
                "--object-path",
                object_path,
                "--method",
                f"{service}.{method}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if output.returncode != 0:
        return None
    return output.stdout.strip() == "true"


def _locked_candidates(desktop: str) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    resolved = str(desktop or "auto").strip().lower()
    if resolved == "cinnamon":
        return (_LOCK_PROBES[0], _LOCK_PROBES[2])
    if resolved == "gnome":
        return (_LOCK_PROBES[1],)
    # auto / unknown / mate / xfce: ask every known locker and accept the first
    # one that answers.
    return _LOCK_PROBES


def session_locked(
    desktop: str = "auto",
    probe: Callable[[str, str, str], bool | None] | None = None,
) -> bool:
    """Return True when the session is locked or the screensaver is active."""
    check = probe if probe is not None else _probe_gdbus
    for service, object_path, methods in _locked_candidates(desktop):
        for method in methods:
            if check(service, object_path, method) is True:
                return True
    return False


def active_run_conditions(
    profile: Profile,
    *,
    proc_root: Path = Path("/proc"),
    power_root: Path = Path("/sys/class/power_supply"),
    idle_probe: Callable[[], float | None] | None = None,
    locked_probe: Callable[[str, str, str], bool | None] | None = None,
) -> list[str]:
    """Return short user-facing reasons why scheduled switching is paused.

    Each enabled condition contributes at most one reason; disabled or
    undetectable conditions contribute none (fail open).
    """
    reasons: list[str] = []
    process_name = str(profile.suppress_process or "").strip()
    if process_name and process_running(process_name, proc_root=proc_root):
        reasons.append(f"{process_name} is running")
    if profile.suppress_on_battery and power_state(power_root) == "battery":
        reasons.append("running on battery")
    if profile.suppress_remote_session and remote_session_active(proc_root=proc_root):
        reasons.append("a remote (VNC) session is active")
    if profile.idle_only:
        check_idle = idle_probe if idle_probe is not None else session_idle_seconds
        idle = check_idle()
        if idle is not None and idle < profile.idle_seconds:
            reasons.append(f"waiting for {profile.idle_seconds} s of idle time")
    if profile.suppress_when_locked and session_locked(profile.desktop, probe=locked_probe):
        reasons.append("session is locked or screensaver is active")
    return reasons
