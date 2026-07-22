"""Validation and ownership helpers for regenerable MBS working files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from .config import Config, load_config, replace_working_directory
from .paths import generated_wallpaper_path, xdg_cache_dir
from .state import state_transaction

MARKER_FILENAME = ".mint-background-switcher-storage.json"
MARKER_DATA = {"application": "mint-background-switcher", "schema": 1}
FOREIGN_DIRECTORY_MESSAGE = "directory contains files and is not marked as Mint Background Switcher storage"


class WorkingDirectoryError(ValueError):
    """Raised when a working directory is unavailable or unsafe to use."""


class WorkingDirectoryOverlapError(WorkingDirectoryError):
    """Raised when working storage overlaps another managed or source tree."""


class WorkingDirectoryMigrationCancelled(WorkingDirectoryError):
    """Raised when a requested working-directory migration is cancelled."""


@dataclass(frozen=True, slots=True)
class WorkingDirectoryMigrationResult:
    source: Path
    destination: Path
    copied_names: tuple[str, ...]


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def configured_working_directory(config: Config) -> Path:
    """Return the configured working path without silently falling back."""

    if config.working_directory:
        return _absolute(config.working_directory)
    return _absolute(xdg_cache_dir())


def _source_directories(config: Config) -> set[Path]:
    directories: set[Path] = set()
    for profile in config.profiles.values():
        raw_paths = list(profile.shared_folders)
        for paths in profile.monitor_folders.values():
            raw_paths.extend(paths)
        for raw_path in raw_paths:
            if raw_path:
                directories.add(_absolute(raw_path).resolve(strict=False))
    return directories


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _validate_marker(marker: Path) -> None:
    try:
        if marker.is_symlink() or not marker.is_file():
            raise WorkingDirectoryError("working-directory ownership marker is not a regular file")
        data = json.loads(marker.read_text(encoding="utf-8"))
    except WorkingDirectoryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkingDirectoryError(f"could not read working-directory ownership marker: {exc}") from exc
    if data != MARKER_DATA:
        raise WorkingDirectoryError("working-directory ownership marker is invalid or unsupported")


def _probe_writable(directory: Path) -> None:
    probe = directory / f".mbs-write-probe-{uuid.uuid4().hex}"
    fd: int | None = None
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"ok\n")
        os.fsync(fd)
    except OSError as exc:
        raise WorkingDirectoryError(f"working directory is not writable: {directory}: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def validate_working_directory(
    path: str | Path,
    config: Config,
    *,
    require_marker: bool = False,
) -> Path:
    """Validate an existing exact directory and return its canonical path."""

    candidate = _absolute(path)
    try:
        if not candidate.exists():
            raise WorkingDirectoryError(f"working directory does not exist: {candidate}")
        if not candidate.is_dir():
            raise WorkingDirectoryError(f"working-directory path is not a directory: {candidate}")
        resolved = candidate.resolve(strict=True)
    except WorkingDirectoryError:
        raise
    except OSError as exc:
        raise WorkingDirectoryError(f"could not access working directory {candidate}: {exc}") from exc

    for source in _source_directories(config):
        if _overlaps(resolved, source):
            raise WorkingDirectoryOverlapError(
                f"working directory overlaps a wallpaper source folder: {resolved} and {source}"
            )

    marker = resolved / MARKER_FILENAME
    try:
        entries = list(resolved.iterdir())
    except OSError as exc:
        raise WorkingDirectoryError(f"could not list working directory {resolved}: {exc}") from exc

    if marker.exists() or marker.is_symlink():
        _validate_marker(marker)
    elif require_marker:
        raise WorkingDirectoryError("working directory is not marked as Mint Background Switcher storage")
    elif entries:
        raise WorkingDirectoryError(FOREIGN_DIRECTORY_MESSAGE)

    _probe_writable(resolved)
    return resolved


def _write_marker(directory: Path) -> None:
    marker = directory / MARKER_FILENAME
    payload = (json.dumps(MARKER_DATA, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _validate_marker(marker)
        return
    try:
        with os.fdopen(fd, "wb") as marker_file:
            marker_file.write(payload)
            marker_file.flush()
            os.fsync(marker_file.fileno())
    except BaseException:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        raise


def prepare_working_directory(path: str | Path, config: Config) -> Path:
    """Adopt an empty directory or validate an existing MBS-owned directory."""

    resolved = validate_working_directory(path, config)
    _write_marker(resolved)
    return validate_working_directory(resolved, config, require_marker=True)


def create_working_directory(parent: str | Path, name: str, config: Config) -> Path:
    """Explicitly create one child directory and mark it as MBS-owned."""

    child_name = name.strip()
    if (
        not child_name
        or child_name in {".", ".."}
        or Path(child_name).name != child_name
        or "/" in child_name
        or "\\" in child_name
        or any(ord(character) < 32 for character in child_name)
    ):
        raise WorkingDirectoryError("working folder name must be one safe folder name")

    parent_path = _absolute(parent)
    if not parent_path.is_dir():
        raise WorkingDirectoryError(f"parent directory does not exist: {parent_path}")
    child = parent_path / child_name
    try:
        child.mkdir()
    except FileExistsError as exc:
        raise WorkingDirectoryError(f"working folder already exists: {child}") from exc
    except OSError as exc:
        raise WorkingDirectoryError(f"could not create working folder {child}: {exc}") from exc

    try:
        return prepare_working_directory(child, config)
    except BaseException:
        try:
            child.rmdir()
        except OSError:
            pass
        raise


def ensure_configured_working_directory(config: Config) -> Path:
    """Return a usable configured directory, creating only the standard default."""

    configured = configured_working_directory(config)
    if config.working_directory:
        return validate_working_directory(configured, config, require_marker=True)

    try:
        configured.mkdir(parents=True, exist_ok=True)
        resolved = configured.resolve(strict=True)
    except OSError as exc:
        raise WorkingDirectoryError(f"could not create default working directory {configured}: {exc}") from exc
    for source in _source_directories(config):
        if _overlaps(resolved, source):
            raise WorkingDirectoryOverlapError(
                f"working directory overlaps a wallpaper source folder: {resolved} and {source}"
            )
    _probe_writable(resolved)
    _write_marker(resolved)
    return resolved


def _managed_names(config: Config, source: Path) -> list[str]:
    suffixes = ("active", "active-0", "active-1", "black", "dry-run", "dry-run-black")
    names = {
        generated_wallpaper_path(profile_name, suffix=suffix, base_dir=source).name
        for profile_name in config.profiles
        for suffix in suffixes
    }
    names.update(
        {
            "library-index.sqlite3",
            "library-index.sqlite3-journal",
            "library-index.sqlite3-shm",
            "library-index.sqlite3-wal",
        }
    )
    return sorted(names)


def _source_files(config: Config, source: Path) -> list[Path]:
    result: list[Path] = []
    for name in _managed_names(config, source):
        path = source / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise WorkingDirectoryError(f"could not inspect managed working file {path}: {exc}") from exc
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise WorkingDirectoryError(f"managed working file is not a regular file: {path}")
        result.append(path)
    return result


def _cancel_if_requested(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise WorkingDirectoryMigrationCancelled("working-directory migration was cancelled")


def _sha256(path: Path, cancelled: Callable[[], bool] | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(1024 * 1024):
            _cancel_if_requested(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path, cancelled: Callable[[], bool] | None) -> None:
    source_digest = hashlib.sha256()
    with source.open("rb") as source_file, destination.open("xb") as destination_file:
        while chunk := source_file.read(1024 * 1024):
            _cancel_if_requested(cancelled)
            source_digest.update(chunk)
            destination_file.write(chunk)
        destination_file.flush()
        os.fsync(destination_file.fileno())
    try:
        destination.chmod(source.stat().st_mode & 0o777)
    except OSError as exc:
        raise WorkingDirectoryError(f"could not preserve mode for migrated file {destination}: {exc}") from exc
    if source_digest.hexdigest() != _sha256(destination, cancelled):
        raise WorkingDirectoryError(f"verification failed while copying managed working file: {source.name}")


def _install_exclusive(
    source: Path,
    destination: Path,
    cancelled: Callable[[], bool] | None,
) -> tuple[int, int]:
    """Copy one staged file to a newly created destination without replacing anything."""

    source_mode = source.stat().st_mode & 0o777
    descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, source_mode)
        descriptor_info = os.fstat(descriptor)
        created_identity = (descriptor_info.st_dev, descriptor_info.st_ino)
        digest = hashlib.sha256()
        with source.open("rb") as source_file, os.fdopen(descriptor, "wb") as destination_file:
            descriptor = None
            while chunk := source_file.read(1024 * 1024):
                _cancel_if_requested(cancelled)
                digest.update(chunk)
                destination_file.write(chunk)
            destination_file.flush()
            os.fsync(destination_file.fileno())
        if digest.hexdigest() != _sha256(destination, cancelled):
            raise WorkingDirectoryError(f"verification failed while installing managed working file: {source.name}")
        assert created_identity is not None  # os.open and os.fstat succeeded
        return created_identity
    except FileExistsError as exc:
        raise WorkingDirectoryError(f"destination already contains managed filename: {destination.name}") from exc
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if created_identity is not None:
            try:
                current = destination.lstat()
                if (current.st_dev, current.st_ino) == created_identity:
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise


def _remove_staging(directory: Path) -> None:
    if not directory.name.startswith(".mbs-migration-"):
        return
    try:
        if directory.is_symlink() or not directory.is_dir():
            directory.unlink()
            return
    except FileNotFoundError:
        return
    shutil.rmtree(directory)


def _finalize_staging(directory: Path, expected_names: set[str]) -> None:
    """Remove only expected staged copies, then remove staging before activation."""

    try:
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink():
            raise WorkingDirectoryError("migration staging path changed before activation")
        entries = list(directory.iterdir())
        if {entry.name for entry in entries} != expected_names:
            raise WorkingDirectoryError("migration staging directory contained unexpected entries")
        for entry in entries:
            entry_metadata = entry.lstat()
            if entry.is_symlink() or not stat.S_ISREG(entry_metadata.st_mode):
                raise WorkingDirectoryError("migration staging directory contained unexpected entries")
        for entry in entries:
            entry.unlink()
        directory.rmdir()
    except FileNotFoundError:
        raise WorkingDirectoryError("migration staging directory disappeared before activation") from None


def migrate_working_directory(
    config: Config,
    destination: str | Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> WorkingDirectoryMigrationResult:
    """Copy verified managed files, then switch the configured working directory."""

    target = _absolute(destination)
    try:
        if not target.exists():
            raise WorkingDirectoryError(f"working directory does not exist: {target}")
        target = target.resolve(strict=True)
    except WorkingDirectoryError:
        raise
    except OSError as exc:
        raise WorkingDirectoryError(f"could not access working directory {target}: {exc}") from exc

    installed: list[tuple[Path, tuple[int, int]]] = []
    config_saved = False
    source: Path | None = None
    staging: Path | None = None
    old_setting: str | None = None
    new_setting: str | None = None

    def remove_installed_files() -> None:
        retained: list[tuple[Path, tuple[int, int]]] = []
        errors: list[str] = []
        for path, identity in installed:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    path.unlink()
                else:
                    retained.append((path, identity))
                    errors.append(f"{path.name} changed after installation")
            except FileNotFoundError:
                pass
            except OSError as exc:
                retained.append((path, identity))
                errors.append(f"{path.name}: {exc}")
        installed[:] = retained
        if errors:
            raise WorkingDirectoryError(
                "working-folder migration failed and some copied files could not be removed: "
                + "; ".join(errors)
            )

    def rollback_before_state_unlock(_error: BaseException | None = None) -> None:
        nonlocal config_saved
        if config_saved:
            try:
                replace_working_directory(old_setting, expected=new_setting)
            except BaseException as rollback_error:
                raise WorkingDirectoryError(
                    "working-folder migration failed after configuration activation and the previous "
                    "configuration could not be restored; copied files were retained for recovery"
                ) from rollback_error
            config_saved = False
        remove_installed_files()

    try:
        with state_transaction(on_error=rollback_before_state_unlock) as state:
            # The state lock serializes this inventory and activation with rotations.
            # Re-read configuration only after acquiring it so a caller cannot make us
            # overwrite a profile change from another Settings/tray process.
            live_config = load_config()
            source = ensure_configured_working_directory(live_config)
            if source == target:
                return WorkingDirectoryMigrationResult(source, target, ())
            if target.is_relative_to(source) or source.is_relative_to(target):
                raise WorkingDirectoryOverlapError(
                    f"working folders must not contain one another: {source} and {target}"
                )
            target = prepare_working_directory(target, live_config)

            # Reserved names are collisions even if there is no corresponding source
            # file. Otherwise a retained symlink could be activated and followed later.
            for name in _managed_names(live_config, source):
                target_file = target / name
                if target_file.exists() or target_file.is_symlink():
                    raise WorkingDirectoryError(f"destination already contains managed filename: {name}")

            files = _source_files(live_config, source)
            _cancel_if_requested(cancelled)
            staging = target / f".mbs-migration-{uuid.uuid4().hex}"
            try:
                staging.mkdir(mode=0o700)
            except OSError as exc:
                raise WorkingDirectoryError(
                    f"could not create migration staging directory in {target}: {exc}"
                ) from exc

            total = len(files)
            for completed, source_file in enumerate(files, start=1):
                _cancel_if_requested(cancelled)
                staged_file = staging / source_file.name
                _copy_verified(source_file, staged_file, cancelled)
                _cancel_if_requested(cancelled)
                target_file = target / source_file.name
                identity = _install_exclusive(staged_file, target_file, cancelled)
                installed.append((target_file, identity))
                if progress is not None:
                    progress(completed, total, source_file.name)

            _cancel_if_requested(cancelled)
            _finalize_staging(staging, {path.name for path in files})
            staging = None
            default = _absolute(xdg_cache_dir()).resolve(strict=False)
            old_setting = live_config.working_directory
            new_setting = None if target == default else str(target)

            def validate_activation(latest_config: Config) -> None:
                latest_source = ensure_configured_working_directory(latest_config)
                if latest_source != source:
                    raise WorkingDirectoryError(
                        "configured working directory changed during migration; the old folder remains active"
                    )
                validate_working_directory(target, latest_config, require_marker=True)
                installed_identities = {path.name: identity for path, identity in installed}
                for name in _managed_names(latest_config, source):
                    target_file = target / name
                    if not target_file.exists() and not target_file.is_symlink():
                        continue
                    expected_identity = installed_identities.get(name)
                    if expected_identity is None:
                        raise WorkingDirectoryError(
                            f"destination acquired managed filename during migration: {name}"
                        )
                    current = target_file.lstat()
                    if (current.st_dev, current.st_ino) != expected_identity:
                        raise WorkingDirectoryError(
                            f"destination managed filename changed during migration: {name}"
                        )

            replace_working_directory(
                new_setting,
                expected=old_setting,
                validate=validate_activation,
            )
            config_saved = True

            if state.last_wallpaper:
                previous = _absolute(state.last_wallpaper)
                if previous.parent.resolve(strict=False) == source and previous.name in {path.name for path in files}:
                    state.last_wallpaper = str(target / previous.name)

        assert source is not None
        return WorkingDirectoryMigrationResult(source, target, tuple(path.name for path, _identity in installed))
    except BaseException:
        rollback_before_state_unlock()
        raise
    finally:
        if staging is not None:
            _remove_staging(staging)