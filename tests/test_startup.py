from pathlib import Path
from types import SimpleNamespace

from mint_background_switcher import startup
from mint_background_switcher.autostart import enable_autostart
from mint_background_switcher.monitor import Monitor
from mint_background_switcher.paths import startup_guard_file, startup_log_file
from mint_background_switcher.storage import locked_read_json


def _ready_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(startup, "detect_desktop", lambda: "cinnamon")
    monkeypatch.setattr(startup, "_cinnamon_process_ready", lambda: (True, "cinnamon process running"))
    monkeypatch.setattr(startup.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(
        startup,
        "_run_quick_command",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="'spanned'\n", stderr=""),
    )
    monkeypatch.setattr(startup, "detect_monitors", lambda: [Monitor("DP-1", 3840, 2160, 0, 0)])


def test_safe_start_check_only_writes_ready_and_does_not_start_loop(monkeypatch, tmp_path: Path):
    _ready_environment(monkeypatch, tmp_path)
    loop_calls = []

    rc = startup.safe_start(
        check_only=True,
        delay_seconds=0,
        readiness_timeout_seconds=0,
        sleep=lambda _seconds: None,
        loop=lambda *args, **kwargs: loop_calls.append((args, kwargs)),
    )

    guard = locked_read_json(startup_guard_file())
    assert rc == 0
    assert guard["phase"] == "ready"
    assert "ready" in guard["detail"]
    assert loop_calls == []
    assert "safe-start starting" in startup_log_file().read_text(encoding="utf-8")


def test_safe_start_starts_deferred_loop_after_readiness(monkeypatch, tmp_path: Path):
    _ready_environment(monkeypatch, tmp_path)
    loop_calls = []

    rc = startup.safe_start(
        "P",
        dry_run=True,
        delay_seconds=0,
        readiness_timeout_seconds=0,
        sleep=lambda _seconds: None,
        loop=lambda *args, **kwargs: loop_calls.append((args, kwargs)),
    )

    assert rc == 0
    assert loop_calls == [(('P',), {"dry_run": True, "defer_first": True, "first_delay_min_seconds": 0.0})]
    assert loop_calls[0][1]["defer_first"] is True


def test_safe_start_previous_incomplete_disables_autostart(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setattr(startup, "_boot_id", lambda: "new-boot")
    path = enable_autostart(["/tmp/run", "safe-start"])
    guard_path = startup_guard_file()
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    guard_path.write_text('{"phase":"starting","pid":999999,"boot_id":"old-boot"}\n', encoding="utf-8")

    rc = startup.safe_start(delay_seconds=0, readiness_timeout_seconds=0, sleep=lambda _seconds: None)

    assert rc == 1
    assert not path.exists()
    assert locked_read_json(guard_path)["phase"] == "disabled"


def test_safe_start_failed_readiness_exits_without_loop(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("DISPLAY", raising=False)
    loop_calls = []

    rc = startup.safe_start(
        delay_seconds=0,
        readiness_timeout_seconds=0,
        sleep=lambda _seconds: None,
        loop=lambda *args, **kwargs: loop_calls.append((args, kwargs)),
    )

    assert rc == 1
    assert loop_calls == []
    assert locked_read_json(startup_guard_file())["phase"] == "failed"
