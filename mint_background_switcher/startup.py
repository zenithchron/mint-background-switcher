"""Safe login startup for Mint Background Switcher.

The normal background loop intentionally changes wallpaper immediately.  That is
fine for a manual command but too risky during Cinnamon login, especially when
fractional scaling/panel/AppIndicator initialization is still settling.  This
module implements a guarded autostart entry point that waits for Cinnamon to be
ready, records startup progress, and defers the first wallpaper change.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .autostart import disable_autostart
from .desktop import detect_desktop
from .monitor import detect_monitors
from .paths import startup_guard_file, startup_log_file, xdg_cache_dir, xdg_config_dir
from .service import run_loop
from .storage import locked_read_json, locked_write_json

DEFAULT_STARTUP_DELAY_SECONDS = 60.0
DEFAULT_READY_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_SECONDS = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _pid_alive(pid: object) -> bool:
    try:
        pid_int = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except OSError:
        return False
    return True


def append_startup_log(message: str) -> None:
    """Append a line to the safe-start log and mirror it to stdout."""
    line = f"{_now_iso()} {message}"
    print(line, flush=True)
    try:
        path = startup_log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        # Logging must never make startup less safe.
        pass


def _read_guard() -> dict:
    path = startup_guard_file()
    if not path.exists():
        return {}
    try:
        data = locked_read_json(path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_guard(phase: str, detail: str = "") -> None:
    data = {
        "phase": phase,
        "detail": detail,
        "pid": os.getpid(),
        "boot_id": _boot_id(),
        "updated_at": _now_iso(),
    }
    path = startup_guard_file()
    xdg_config_dir().mkdir(parents=True, exist_ok=True)
    locked_write_json(path, data)


def _previous_start_is_active(guard: dict) -> bool:
    return guard.get("phase") == "starting" and guard.get("boot_id") == _boot_id() and _pid_alive(guard.get("pid"))


def _previous_start_incomplete(guard: dict) -> bool:
    if guard.get("phase") != "starting":
        return False
    return not _previous_start_is_active(guard)


def _run_quick_command(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)


def _cinnamon_process_ready() -> tuple[bool, str]:
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return True, "pgrep not available"
    try:
        result = _run_quick_command([pgrep, "-x", "-u", os.environ.get("USER") or str(os.getuid()), "cinnamon"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not check cinnamon process: {exc}"
    if result.returncode == 0:
        return True, "cinnamon process running"
    return False, "cinnamon process is not running yet"


def startup_ready() -> tuple[bool, str]:
    """Return whether it is safe to start the deferred background loop."""
    if os.geteuid() == 0:
        return False, "refusing to start as root"
    if not os.environ.get("DISPLAY"):
        return False, "DISPLAY is not set"
    desktop = detect_desktop()
    if desktop != "cinnamon" and os.environ.get("MBS_SAFE_START_ALLOW_NON_CINNAMON") != "1":
        return False, f"desktop is {desktop!r}, not Cinnamon"

    ok, reason = _cinnamon_process_ready()
    if not ok:
        return False, reason

    if not shutil.which("gsettings"):
        return False, "gsettings is not available"
    try:
        result = _run_quick_command(["gsettings", "get", "org.cinnamon.desktop.background", "picture-options"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"gsettings is not ready: {exc}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        return False, f"gsettings is not ready: {err or result.returncode}"

    try:
        monitors = detect_monitors()
    except Exception as exc:
        return False, f"monitor detection failed: {exc}"
    if not monitors:
        return False, "no monitors detected"
    if any(m.width <= 0 or m.height <= 0 for m in monitors):
        return False, "monitor geometry is not valid"
    return True, f"ready: {len(monitors)} monitor(s), desktop={desktop}"


def wait_until_ready(
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    last_reason = "not checked"
    while True:
        ok, reason = startup_ready()
        last_reason = reason
        append_startup_log(f"readiness check: {reason}")
        if ok:
            return True, reason
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, last_reason
        sleep(min(max(poll_seconds, 0.1), remaining))


def safe_start(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    check_only: bool = False,
    delay_seconds: float | None = None,
    readiness_timeout_seconds: float | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    loop: Callable[..., None] = run_loop,
) -> int:
    """Guarded autostart entry point.

    Returns a process-style exit code.  The function does not apply a wallpaper
    during readiness checks.  If it does start the loop, the first wallpaper
    change is deferred by at least ``delay_seconds``.
    """
    xdg_cache_dir().mkdir(parents=True, exist_ok=True)
    delay = _env_float("MBS_SAFE_START_DELAY_SECONDS", DEFAULT_STARTUP_DELAY_SECONDS) if delay_seconds is None else max(0.0, delay_seconds)
    timeout = (
        _env_float("MBS_SAFE_START_READY_TIMEOUT_SECONDS", DEFAULT_READY_TIMEOUT_SECONDS)
        if readiness_timeout_seconds is None
        else max(0.0, readiness_timeout_seconds)
    )

    guard = _read_guard()
    if _previous_start_is_active(guard):
        append_startup_log("another safe-start is already in its startup phase; exiting")
        return 0
    if _previous_start_incomplete(guard):
        removed = disable_autostart()
        detail = f"previous startup did not reach ready; disabled autostart ({len(removed)} entr{'y' if len(removed) == 1 else 'ies'} removed)"
        append_startup_log(detail)
        _write_guard("disabled", detail)
        return 1

    append_startup_log("safe-start starting")
    _write_guard("starting", "startup checks in progress")

    if delay > 0:
        append_startup_log(f"waiting {delay:.0f} second(s) before readiness checks")
        sleep(delay)

    ok, reason = wait_until_ready(timeout_seconds=timeout, poll_seconds=poll_seconds, sleep=sleep)
    if not ok:
        detail = f"startup not ready; exiting without touching wallpaper: {reason}"
        append_startup_log(detail)
        _write_guard("failed", detail)
        return 1

    append_startup_log(reason)
    _write_guard("ready", reason)
    if check_only:
        append_startup_log("check-only requested; not starting background loop")
        return 0

    append_startup_log("starting deferred background loop")
    try:
        loop(profile_name, dry_run=dry_run, defer_first=True, first_delay_min_seconds=delay)
    except Exception as exc:
        detail = f"background loop exited unexpectedly: {exc}"
        append_startup_log(detail)
        _write_guard("failed", detail)
        return 1
    return 0
