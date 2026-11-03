"""Tests for the run-conditions module (SW-07..SW-11).

Every probe must fail open: an undetectable condition never blocks switching.
"""

from pathlib import Path

import pytest

from mint_background_switcher import run_conditions
from mint_background_switcher.config import Profile


def _make_proc(root: Path, comms: dict[int, str]) -> Path:
    proc = root / "proc"
    for pid, comm in comms.items():
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "comm").write_text(comm + "\n")
    return proc


def _make_power_supply(root: Path, devices: dict[str, dict[str, str]]) -> Path:
    base = root / "power_supply"
    for name, attrs in devices.items():
        device = base / name
        device.mkdir(parents=True)
        for key, value in attrs.items():
            (device / key).write_text(value + "\n")
    return base


def test_process_running_matches_comm_case_insensitive(tmp_path: Path):
    proc = _make_proc(tmp_path, {101: "MPV", 102: "firefox"})
    assert run_conditions.process_running("mpv", proc_root=proc) is True
    assert run_conditions.process_running("mpv ", proc_root=proc) is True


def test_process_running_no_match_and_empty_name(tmp_path: Path):
    proc = _make_proc(tmp_path, {101: "mpv"})
    assert run_conditions.process_running("thunderbird", proc_root=proc) is False
    assert run_conditions.process_running("   ", proc_root=proc) is False
    assert run_conditions.process_running("", proc_root=proc) is False


def test_process_running_ignores_own_process(tmp_path: Path):
    import os

    proc = _make_proc(tmp_path, {os.getpid(): "mpv"})
    assert run_conditions.process_running("mpv", proc_root=proc) is False


def test_process_running_missing_proc_root_fails_open(tmp_path: Path):
    assert run_conditions.process_running("mpv", proc_root=tmp_path / "nope") is False


def test_remote_session_active_detects_vnc_servers(tmp_path: Path):
    proc = _make_proc(tmp_path, {201: "x11vnc", 202: "firefox"})
    assert run_conditions.remote_session_active(proc_root=proc) is True


def test_remote_session_active_absent(tmp_path: Path):
    proc = _make_proc(tmp_path, {201: "vncclient", 202: "firefox"})
    assert run_conditions.remote_session_active(proc_root=proc) is False


def test_power_state_battery_when_discharging_without_ac(tmp_path: Path):
    base = _make_power_supply(
        tmp_path,
        {
            "BAT0": {"Type": "Battery", "status": "Discharging"},
            "AC": {"Type": "Mains", "online": "0"},
        },
    )
    assert run_conditions.power_state(base) == "battery"


def test_power_state_ac_when_online_or_charging(tmp_path: Path):
    base = _make_power_supply(
        tmp_path / "plugged",
        {
            "BAT0": {"Type": "Battery", "status": "Charging"},
            "AC": {"Type": "Mains", "online": "1"},
        },
    )
    assert run_conditions.power_state(base) == "ac"
    base = _make_power_supply(
        tmp_path / "charging", {"BAT0": {"Type": "Battery", "status": "Charging"}}
    )
    assert run_conditions.power_state(base) == "ac"


def test_power_state_unknown_without_battery_or_data(tmp_path: Path):
    base = _make_power_supply(tmp_path, {"AC": {"Type": "Mains", "online": "1"}})
    assert run_conditions.power_state(base) == "unknown"
    assert run_conditions.power_state(tmp_path / "missing") == "unknown"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_conditions.power_state(empty) == "unknown"


def test_session_idle_seconds_missing_tool_fails_open(monkeypatch):
    monkeypatch.setattr(run_conditions.shutil, "which", lambda name: None)
    assert run_conditions.session_idle_seconds() is None


def test_session_idle_seconds_parses_milliseconds(monkeypatch):
    monkeypatch.setattr(run_conditions.shutil, "which", lambda name: "/usr/bin/xprintidle")

    class _Output:
        returncode = 0
        stdout = "123456\n"

    monkeypatch.setattr(run_conditions.subprocess, "run", lambda *a, **k: _Output())
    assert run_conditions.session_idle_seconds() == pytest.approx(123.456)


def test_session_idle_seconds_bad_output_fails_open(monkeypatch):
    monkeypatch.setattr(run_conditions.shutil, "which", lambda name: "/usr/bin/xprintidle")

    class _Output:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(run_conditions.subprocess, "run", lambda *a, **k: _Output())
    assert run_conditions.session_idle_seconds() is None


def test_session_locked_probe_true_and_desktop_selection():
    seen: list[tuple[str, str, str]] = []

    def probe(service, object_path, method):
        seen.append((service, object_path, method))
        return service == "org.cinnamon.ScreenSaver" and method == "IsLocked"

    assert run_conditions.session_locked("cinnamon", probe=probe) is True
    assert all(service == "org.cinnamon.ScreenSaver" or service == "org.lightdm.Status" for service, _, _ in seen)
    seen.clear()

    assert run_conditions.session_locked("gnome", probe=probe) is False
    assert all(service == "org.gnome.ScreenSaver" for service, _, _ in seen)


def test_session_locked_fails_open_when_no_service_answers():
    assert run_conditions.session_locked("auto", probe=lambda *args: None) is False
    assert run_conditions.session_locked("auto", probe=lambda *args: False) is False


def test_active_run_conditions_all_disabled_returns_nothing(tmp_path: Path):
    profile = Profile(name="P")
    assert run_conditions.active_run_conditions(profile, proc_root=tmp_path, power_root=tmp_path) == []


def test_active_run_conditions_each_condition_reports_its_reason(tmp_path: Path):
    proc = _make_proc(tmp_path, {101: "mpv", 201: "x11vnc"})
    power = _make_power_supply(tmp_path, {"BAT0": {"Type": "Battery", "status": "Discharging"}})
    profile = Profile(
        name="P",
        suppress_process="mpv",
        suppress_on_battery=True,
        suppress_remote_session=True,
        idle_only=True,
        idle_seconds=300,
        suppress_when_locked=True,
    )
    reasons = run_conditions.active_run_conditions(
        profile,
        proc_root=proc,
        power_root=power,
        idle_probe=lambda: 10.0,
        locked_probe=lambda *args: True,
    )
    assert reasons == [
        "mpv is running",
        "running on battery",
        "a remote (VNC) session is active",
        "waiting for 300 s of idle time",
        "session is locked or screensaver is active",
    ]


def test_active_run_conditions_fail_open_when_undetectable(tmp_path: Path):
    profile = Profile(
        name="P",
        suppress_process="mpv",
        suppress_on_battery=True,
        suppress_remote_session=True,
        idle_only=True,
        idle_seconds=300,
        suppress_when_locked=True,
    )
    # No /proc entries, no power supply, idle unknown, no locker answers.
    reasons = run_conditions.active_run_conditions(
        profile,
        proc_root=tmp_path / "empty-proc",
        power_root=tmp_path / "empty-power",
        idle_probe=lambda: None,
        locked_probe=lambda *args: None,
    )
    assert reasons == []


def test_active_run_conditions_idle_boundary_is_inclusive(tmp_path: Path):
    proc = tmp_path / "empty-proc"
    profile = Profile(name="P", idle_only=True, idle_seconds=300)
    assert run_conditions.active_run_conditions(profile, proc_root=proc, idle_probe=lambda: 300.0) == []
    assert run_conditions.active_run_conditions(
        profile, proc_root=proc, idle_probe=lambda: 299.9
    ) == ["waiting for 300 s of idle time"]
