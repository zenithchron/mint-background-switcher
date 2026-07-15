"""Configuration and profile loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_file, xdg_config_dir
from .storage import locked_read_json, locked_write_json

CONFIG_VERSION = 1
VALID_MODES = {"shared", "same", "per-monitor", "span"}
EFFECT_CHOICES = ("none", "grayscale", "sepia", "blur")
VALID_EFFECTS = set(EFFECT_CHOICES)
VALID_BAR_COLORS = {"black", "auto"}


def _coerce_interval(value: Any, default: float = 10.0) -> float:
    try:
        return max(0.1, float(value))
    except (TypeError, ValueError):
        return default


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(p) for p in value if str(p).strip()]


def _coerce_monitor_folders(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for monitor, folders in value.items():
        folder_list = _coerce_str_list(folders)
        if folder_list:
            result[str(monitor)] = folder_list
    return result


@dataclass(slots=True)
class Profile:
    name: str
    interval_minutes: float = 10.0
    mode: str = "shared"
    recursive: bool = True
    shared_folders: list[str] = field(default_factory=list)
    monitor_folders: dict[str, list[str]] = field(default_factory=dict)
    black_hotkey: str = "<Primary><Alt>b"
    desktop: str = "auto"
    effect: str = "none"
    bar_color: str = "black"

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "Profile":
        mode = str(data.get("mode", "shared")).strip().lower()
        if mode not in VALID_MODES:
            mode = "shared"
        effect = str(data.get("effect", "none")).strip().lower()
        if effect not in VALID_EFFECTS:
            effect = "none"
        bar_color = str(data.get("bar_color", "black")).strip().lower()
        if bar_color not in VALID_BAR_COLORS:
            bar_color = "black"
        return cls(
            name=name,
            interval_minutes=_coerce_interval(data.get("interval_minutes", 10.0)),
            mode=mode,
            recursive=bool(data.get("recursive", True)),
            shared_folders=_coerce_str_list(data.get("shared_folders", [])),
            monitor_folders=_coerce_monitor_folders(data.get("monitor_folders", {})),
            black_hotkey=str(data.get("black_hotkey", "<Primary><Alt>b")),
            desktop=str(data.get("desktop", "auto")),
            effect=effect,
            bar_color=bar_color,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_minutes": self.interval_minutes,
            "mode": self.mode,
            "recursive": self.recursive,
            "shared_folders": self.shared_folders,
            "monitor_folders": self.monitor_folders,
            "black_hotkey": self.black_hotkey,
            "desktop": self.desktop,
            "effect": self.effect,
            "bar_color": self.bar_color,
        }

    def folders_for_monitor(self, monitor_name: str) -> list[str]:
        folders = self.monitor_folders.get(monitor_name) or self.monitor_folders.get(str(monitor_name)) or []
        return folders or self.shared_folders


@dataclass(slots=True)
class Config:
    active_profile: str = "Default"
    profiles: dict[str, Profile] = field(default_factory=dict)

    @classmethod
    def default(cls, folder: str | None = None) -> "Config":
        default_folder = folder
        if default_folder is None:
            pictures = Path.home() / "Pictures"
            default_folder = str(pictures) if pictures.exists() else ""
        profile = Profile(name="Default", shared_folders=[default_folder] if default_folder else [])
        return cls(active_profile="Default", profiles={"Default": profile})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        profiles_data = data.get("profiles") or {}
        if not isinstance(profiles_data, dict):
            return cls.default()
        profiles = {
            str(name): Profile.from_dict(str(name), pdata if isinstance(pdata, dict) else {})
            for name, pdata in profiles_data.items()
        }
        if not profiles:
            return cls.default()
        active = str(data.get("active_profile") or next(iter(profiles)))
        if active not in profiles:
            active = next(iter(profiles))
        return cls(active_profile=active, profiles=profiles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "active_profile": self.active_profile,
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
        }

    def get_profile(self, name: str | None = None) -> Profile:
        profile_name = name or self.active_profile
        try:
            return self.profiles[profile_name]
        except KeyError as exc:
            raise KeyError(f"No profile named {profile_name!r}. Available: {', '.join(sorted(self.profiles))}") from exc


def load_config(path: Path | None = None, create: bool = True) -> Config:
    path = path or config_file()
    if not path.exists():
        cfg = Config.default()
        if create:
            save_config(cfg, path)
        return cfg
    data = locked_read_json(path)
    return Config.from_dict(data)


def save_config(config: Config, path: Path | None = None) -> Path:
    path = path or config_file()
    xdg_config_dir().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    locked_write_json(path, config.to_dict())
    return path


def ensure_config(folder: str | None = None) -> Path:
    path = config_file()
    if not path.exists():
        save_config(Config.default(folder=folder), path)
    elif folder:
        cfg = load_config(path)
        prof = cfg.get_profile()
        if folder not in prof.shared_folders:
            prof.shared_folders.append(folder)
            save_config(cfg, path)
    return path
