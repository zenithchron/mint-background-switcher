"""XDG path helpers for Mint Background Switcher."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "mint-background-switcher"


def xdg_config_dir() -> Path:
    override = os.environ.get("MBS_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


def xdg_cache_dir() -> Path:
    override = os.environ.get("MBS_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / APP_DIR_NAME


def config_file() -> Path:
    return xdg_config_dir() / "config.json"


def state_file() -> Path:
    return xdg_config_dir() / "state.json"


def generated_wallpaper_path(profile_name: str, suffix: str = "active") -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in profile_name).strip("._") or "profile"
    return xdg_cache_dir() / f"{safe}-{suffix}.png"


def startup_log_file() -> Path:
    return xdg_cache_dir() / "startup.log"


def startup_guard_file() -> Path:
    return xdg_config_dir() / "startup-guard.json"


def autostart_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "mint-background-switcher.desktop"
