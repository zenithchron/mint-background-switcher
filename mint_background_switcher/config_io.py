"""Full settings export and import (backup and restore of the whole config)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .paths import config_file
from .storage import atomic_write_json_unlocked, locked_file, lock_path_for

EXPORT_FORMAT = "mint-background-switcher-settings"
EXPORT_FORMAT_VERSION = 1


class ConfigImportError(ValueError):
    """Raised when a file cannot be used as a settings import source."""


def export_document(config: Config) -> dict[str, Any]:
    """Build the deterministic export document for ``config``."""
    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "config": config.to_dict(),
    }


def export_config(config: Config, destination: Path) -> Path:
    """Atomically write the full settings export for ``config`` to ``destination``.

    Refuses to overwrite the live settings file: the wrapped export document is
    not a config, and writing it over ``config.json`` would make the next save
    treat the installation as empty.
    """
    destination = Path(destination).expanduser()
    if destination.resolve() == config_file().resolve():
        raise ValueError(
            f"refusing to export onto the live settings file {config_file()}; choose a different file"
        )
    atomic_write_json_unlocked(destination, export_document(config))
    return destination


def _extract_config_data(data: Any) -> dict[str, Any]:
    """Return the config object inside an export document, or a raw config file."""
    if not isinstance(data, dict):
        raise ConfigImportError("top-level JSON value must be an object")
    if "config" in data:
        config_data = data["config"]
        if not isinstance(config_data, dict):
            raise ConfigImportError("the 'config' entry of the export must be an object")
        return config_data
    return data


def load_export(source: Path) -> Config:
    """Parse and validate a settings export (or raw config file) without touching any config.

    Accepts both the wrapped export document (``{"format": ..., "config": {...}}``)
    and a plain config file, so a saved copy of ``config.json`` is a valid import
    source. Raises :class:`ConfigImportError` on anything unusable.
    """
    source = Path(source).expanduser()
    try:
        raw = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigImportError("the file is not valid UTF-8 text") from exc
    except OSError as exc:
        raise ConfigImportError(f"cannot read {source}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigImportError(f"not valid JSON: {exc}") from exc
    config_data = _extract_config_data(data)
    profiles_data = config_data.get("profiles")
    if not isinstance(profiles_data, dict) or not profiles_data:
        raise ConfigImportError("no profiles found; the file is not a usable settings export")
    for name, pdata in profiles_data.items():
        clean_name = str(name).strip()
        if not clean_name:
            raise ConfigImportError("a profile has a blank name")
        if not isinstance(pdata, dict):
            raise ConfigImportError(f"profile {clean_name!r} is malformed")
    return Config.from_dict(config_data)


def import_settings(source: Path, destination: Path | None = None) -> Config:
    """Validate ``source`` and atomically replace the settings at ``destination``.

    This is a full restore: every profile, the active profile, and the working
    directory are replaced by the imported values. On any validation failure the
    destination is left byte-for-byte unchanged.
    """
    destination = Path(destination).expanduser() if destination is not None else config_file()
    imported = load_export(source)
    if destination.is_dir():
        raise ConfigImportError(f"destination {destination} is a directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(lock_path_for(destination)):
        atomic_write_json_unlocked(destination, imported.to_dict())
    return imported
