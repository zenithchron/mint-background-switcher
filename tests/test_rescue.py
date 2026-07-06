from types import SimpleNamespace

import signal

from mint_background_switcher import rescue
from mint_background_switcher.autostart import enable_autostart


def test_rescue_light_disables_autostart_and_moves_mbs_state(monkeypatch, tmp_path):
    home = tmp_path / "home"
    config_dir = home / ".config" / "mint-background-switcher"
    cache_dir = home / ".cache" / "mint-background-switcher"
    config_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}\n", encoding="utf-8")
    (cache_dir / "startup.log").write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("MBS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MBS_CACHE_DIR", str(cache_dir))
    autostart = enable_autostart(["/tmp/run", "safe-start"])
    calls = []
    monkeypatch.setattr(rescue.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(rescue.subprocess, "run", lambda args, **_kwargs: calls.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))

    result = rescue.run_rescue(full=False, reboot=False)

    assert result.mode == "light"
    assert not autostart.exists()
    assert not config_dir.exists()
    assert not cache_dir.exists()
    assert (result.backup_dir / "mint-background-switcher.config" / "config.json").exists()
    assert (result.backup_dir / "mint-background-switcher.cache" / "startup.log").exists()
    assert any(cmd[:4] == ["dbus-run-session", "--", "gsettings", "set"] for cmd in calls)


def test_rescue_full_backs_up_and_resets_cinnamon_settings(monkeypatch, tmp_path):
    home = tmp_path / "home"
    dconf_dir = home / ".config" / "dconf"
    dconf_dir.mkdir(parents=True)
    (dconf_dir / "user").write_bytes(b"dconf")
    monitors = home / ".config" / "monitors.xml"
    monitors.write_text("<monitors/>\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("MBS_CONFIG_DIR", str(home / ".config" / "mint-background-switcher"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(home / ".cache" / "mint-background-switcher"))
    calls = []
    monkeypatch.setattr(rescue.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(rescue.subprocess, "run", lambda args, **_kwargs: calls.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))

    result = rescue.run_rescue(full=True, reboot=False)

    assert (result.backup_dir / "dconf.backup" / "user").exists()
    assert (result.backup_dir / "monitors.xml.backup").exists()
    assert not monitors.exists()
    assert ["dbus-run-session", "--", "dconf", "reset", "-f", "/org/cinnamon/"] in calls
    assert ["dbus-run-session", "--", "dconf", "reset", "-f", "/org/nemo/desktop/"] in calls


def test_rescue_process_cleanup_does_not_kill_current_process(monkeypatch):
    calls = []
    killed = []
    monkeypatch.setattr(rescue.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(rescue.os, "getpid", lambda: 100)
    monkeypatch.setattr(rescue.os, "getppid", lambda: 99)
    monkeypatch.setattr(
        rescue.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or SimpleNamespace(returncode=0, stdout="99\n100\n101\n", stderr=""),
    )
    monkeypatch.setattr(rescue.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    rescue._kill_matching_processes("mint-background-switcher", [])

    assert calls == [["/usr/bin/pgrep", "-u", rescue.os.environ.get("USER") or str(rescue.os.getuid()), "-f", "mint-background-switcher"]]
    assert killed == [(101, signal.SIGTERM)]
