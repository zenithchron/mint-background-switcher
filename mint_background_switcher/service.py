"""Core wallpaper switching service functions."""

from __future__ import annotations

import os
import random
import secrets
import shutil
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Profile, load_config
from .desktop import DesktopSetter
from .images import (
    apply_effect,
    compose_black,
    compose_montage,
    compose_per_monitor,
    compose_postcard,
    compose_span,
    is_usable_image,
    scan_images,
)
from .library_index import IndexSnapshot, LibraryIndex, LibrarySelection
from .monitor import Monitor, detect_monitors
from .paths import generated_wallpaper_path
from .state import RuntimeState, draw_many, load_state, state_transaction
from .working_storage import ensure_configured_working_directory


@dataclass(slots=True)
class SwitchResult:
    profile: str
    wallpaper: Path
    images: list[str]
    monitors: list[Monitor]
    applied: bool
    action: str


class SwitchCancelled(RuntimeError):
    """Raised when a background rotation is cancelled before desktop activation."""


def _cancel_if_requested(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise SwitchCancelled("wallpaper rotation was cancelled")


def _profile_bucket(profile: Profile, suffix: str) -> str:
    return f"profile:{profile.name}:{suffix}"


def _draw_usable_many(
    state: RuntimeState,
    bucket: str,
    pool: list[str],
    count: int,
    *,
    rng: random.Random | None,
) -> list[str]:
    """Draw images while discarding selected files that Pillow cannot decode."""

    candidates = list(pool)
    selected: list[str] = []
    while candidates and len(selected) < count:
        batch = draw_many(state, bucket, candidates, count - len(selected), rng=rng)
        if not batch:
            break
        for image in batch:
            if is_usable_image(image):
                selected.append(image)
            else:
                candidates = [candidate for candidate in candidates if candidate != image]
            if len(selected) >= count:
                break
    return selected


@dataclass(slots=True)
class _ImagePool:
    paths: list[str] | None = None
    index: LibraryIndex | None = None
    snapshot: IndexSnapshot | None = None
    selection: LibrarySelection | None = None

    @property
    def empty(self) -> bool:
        if self.paths is not None:
            return not self.paths
        return self.snapshot is None or self.snapshot.image_count <= 0


def _load_image_pool(
    folders: list[str],
    recursive: bool,
    *,
    dry_run: bool,
    index: LibraryIndex | None,
    selection: LibrarySelection | None,
    cancelled: Callable[[], bool] | None,
    progress: Callable[[int, str], None] | None,
) -> _ImagePool:
    if dry_run:
        return _ImagePool(paths=scan_images(folders, recursive))
    if index is None:  # pragma: no cover - guarded by switch setup
        raise RuntimeError("live wallpaper rotation requires an image index")
    snapshot = index.ensure(
        folders,
        recursive=recursive,
        cancelled=cancelled,
        progress=progress,
    )
    return _ImagePool(index=index, snapshot=snapshot, selection=selection)


def _draw_from_pool(
    state: RuntimeState,
    pool: _ImagePool,
    bucket: str,
    count: int,
    *,
    rng: random.Random | None,
    require_usable: bool = False,
) -> list[str]:
    if pool.paths is not None:
        if require_usable:
            return _draw_usable_many(state, bucket, pool.paths, count, rng=rng)
        return draw_many(state, bucket, pool.paths, count, rng=rng)
    if pool.index is None or pool.snapshot is None:
        return []

    selected: list[str] = []
    while len(selected) < count:
        selector = pool.selection or pool.index
        batch = selector.draw(
            pool.snapshot.signature,
            bucket,
            count - len(selected),
            rng=rng,
        )
        if not batch:
            break
        if not require_usable:
            selected.extend(batch)
            break
        valid_in_batch = 0
        for image in batch:
            if is_usable_image(image):
                selected.append(image)
                valid_in_batch += 1
            else:
                selector.discard(pool.snapshot.signature, image)
            if len(selected) >= count:
                break
        if valid_in_batch == 0:
            continue

    # Every entry in RuntimeState.remaining belongs to the pre-SQLite path-pool
    # implementation. The first indexed live draw completes that migration globally.
    state.remaining.clear()
    return selected


def _draw_one_from_pool(
    state: RuntimeState,
    pool: _ImagePool,
    bucket: str,
    *,
    rng: random.Random | None,
) -> str:
    selected = _draw_from_pool(state, pool, bucket, 1, rng=rng)
    if not selected:
        raise ValueError(f"No images available for bucket {bucket}")
    return selected[0]


def _next_wallpaper_path(
    profile: Profile,
    state: RuntimeState,
    *,
    dry_run: bool,
    working_directory: Path,
) -> tuple[Path, int | None]:
    """Return an off-screen output path and the live slot to save after a successful apply.

    Live rotations alternate between two active files so the desktop never watches the
    currently displayed image being overwritten. Dry-runs write to their own preview
    file instead of touching either live file.
    """
    if dry_run:
        return generated_wallpaper_path(profile.name, suffix="dry-run", base_dir=working_directory), None
    slot = (state.wallpaper_slot + 1) % 2
    return generated_wallpaper_path(profile.name, suffix=f"active-{slot}", base_dir=working_directory), slot


def _apply_black_fallback(
    profile: Profile,
    monitors: list[Monitor],
    wallpaper_path: Path,
    *,
    dry_run: bool,
    cancelled: Callable[[], bool] | None,
) -> Path:
    """Apply an all-black non-sticky fallback when configured image folders are empty.

    This is intentionally different from the user-invoked black-screen action: it
    does not pause rotation or set black_screen state, so removable drives coming
    back online on a later tick can resume normal wallpapers automatically.
    """
    wallpaper = compose_black(monitors, wallpaper_path)
    _cancel_if_requested(cancelled)
    DesktopSetter(dry_run=dry_run).apply_black(wallpaper, profile.desktop)
    return wallpaper


def _apply_composed_wallpaper(
    profile: Profile,
    wallpaper: Path,
    *,
    dry_run: bool,
    cancelled: Callable[[], bool] | None,
) -> None:
    _cancel_if_requested(cancelled)
    apply_effect(wallpaper, profile.effect)
    _cancel_if_requested(cancelled)
    DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)


@dataclass(slots=True)
class _SelectionScope:
    selection: LibrarySelection | None = None

    def begin(self, index: LibraryIndex | None) -> LibrarySelection | None:
        if index is not None:
            self.selection = index.selection()
            self.selection.__enter__()
        return self.selection

    def finish(self, error: BaseException | None) -> None:
        if self.selection is not None:
            selection = self.selection
            self.selection = None
            selection.__exit__(type(error) if error is not None else None, error, error.__traceback__ if error else None)


def switch_once(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    clear_black: bool = True,
    rng: random.Random | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> SwitchResult:
    selection_scope = _SelectionScope()
    if dry_run:
        transient_state = RuntimeState.from_dict(load_state().to_dict())
        try:
            result = _switch_once_with_state(
                profile_name,
                transient_state,
                selection_scope=selection_scope,
                dry_run=True,
                clear_black=clear_black,
                rng=rng,
                cancelled=cancelled,
                progress=progress,
            )
        except BaseException as error:
            selection_scope.finish(error)
            raise
        selection_scope.finish(None)
        return result
    try:
        with state_transaction() as state:
            result = _switch_once_with_state(
                profile_name,
                state,
                selection_scope=selection_scope,
                dry_run=False,
                clear_black=clear_black,
                rng=rng,
                cancelled=cancelled,
                progress=progress,
            )
    except BaseException as error:
        selection_scope.finish(error)
        raise
    selection_scope.finish(None)
    return result


def _switch_once_with_state(
    profile_name: str | None,
    state: RuntimeState,
    *,
    selection_scope: _SelectionScope,
    dry_run: bool,
    clear_black: bool,
    rng: random.Random | None,
    cancelled: Callable[[], bool] | None,
    progress: Callable[[int, str], None] | None,
) -> SwitchResult:
    cfg = load_config()
    profile = cfg.get_profile(profile_name)
    working_directory = ensure_configured_working_directory(cfg)
    index = None if dry_run else LibraryIndex(working_directory)
    selection = selection_scope.begin(index)
    monitors = detect_monitors()
    state.active_profile = profile.name
    wallpaper_path, next_slot = _next_wallpaper_path(
        profile,
        state,
        dry_run=dry_run,
        working_directory=working_directory,
    )

    selections: dict[str, str] = {}
    images_used: list[str] = []
    action: str = "next"
    if profile.mode == "span":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
        )
        if pool.empty:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            image = _draw_one_from_pool(
                state,
                pool,
                _profile_bucket(profile, "span"),
                rng=rng,
            )
            wallpaper = compose_span(monitors, image, wallpaper_path, bar_color=profile.bar_color)
            images_used = [image]
            _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)
    elif profile.mode == "montage":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
        )
        if pool.empty:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            chosen = _draw_from_pool(
                state,
                pool,
                _profile_bucket(profile, "montage"),
                len(monitors) * 4,
                rng=rng,
            )
            montage_by_monitor = {
                monitor.name: chosen[index * 4 : (index + 1) * 4]
                for index, monitor in enumerate(monitors)
            }
            images_used = chosen
            wallpaper = compose_montage(monitors, montage_by_monitor, wallpaper_path, bar_color=profile.bar_color)
            _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)
    elif profile.mode == "postcard":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
        )
        if pool.empty:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            chosen = _draw_from_pool(
                state,
                pool,
                _profile_bucket(profile, "postcard"),
                len(monitors) * 4,
                rng=rng,
                require_usable=True,
            )
            if not chosen:
                wallpaper = _apply_black_fallback(
                    profile,
                    monitors,
                    wallpaper_path,
                    dry_run=dry_run,
                    cancelled=cancelled,
                )
                action = "black-fallback"
            else:
                postcard_by_monitor = {
                    monitor.name: chosen[index * 4 : (index + 1) * 4]
                    for index, monitor in enumerate(monitors)
                }
                images_used = chosen
                wallpaper = compose_postcard(monitors, postcard_by_monitor, wallpaper_path, bar_color=profile.bar_color)
                _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)
    elif profile.mode == "same":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
        )
        if pool.empty:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            image = _draw_one_from_pool(
                state,
                pool,
                _profile_bucket(profile, "same"),
                rng=rng,
            )
            selections = {monitor.name: image for monitor in monitors}
            images_used = [image]
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path, bar_color=profile.bar_color)
            _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)
    elif profile.mode == "shared":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
        )
        if pool.empty:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            chosen = _draw_from_pool(
                state,
                pool,
                _profile_bucket(profile, "shared"),
                len(monitors),
                rng=rng,
            )
            for monitor, image in zip(monitors, chosen):
                selections[monitor.name] = image
            images_used = chosen
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path, bar_color=profile.bar_color)
            _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)
    else:
        pools_by_monitor: dict[str, _ImagePool] = {}
        missing_monitors: list[str] = []
        for monitor in monitors:
            folders = profile.folders_for_monitor(monitor.name)
            pool = _load_image_pool(
                folders,
                profile.recursive,
                dry_run=dry_run,
                index=index,
                selection=selection,
                cancelled=cancelled,
                progress=progress,
            )
            if not pool.empty:
                pools_by_monitor[monitor.name] = pool
            else:
                missing_monitors.append(monitor.name)
        if missing_monitors:
            wallpaper = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            for monitor in monitors:
                image = _draw_one_from_pool(
                    state,
                    pools_by_monitor[monitor.name],
                    _profile_bucket(profile, f"monitor:{monitor.name}"),
                    rng=rng,
                )
                selections[monitor.name] = image
                images_used.append(image)
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path, bar_color=profile.bar_color)
            _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, cancelled=cancelled)

    if next_slot is not None:
        state.wallpaper_slot = next_slot
    if clear_black:
        state.black_screen = False
        state.paused = False
    state.last_wallpaper = str(wallpaper)
    state.last_images = images_used
    return SwitchResult(profile.name, wallpaper, images_used, monitors, applied=not dry_run, action=action)


def black_screen(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> SwitchResult:
    _cancel_if_requested(cancelled)
    cfg = load_config()
    profile = cfg.get_profile(profile_name)
    working_directory = ensure_configured_working_directory(cfg)
    setter = DesktopSetter(dry_run=dry_run)
    wallpaper_path = generated_wallpaper_path(
        profile.name,
        suffix="dry-run-black" if dry_run else "black",
        base_dir=working_directory,
    )

    if dry_run:
        _cancel_if_requested(cancelled)
        monitors = detect_monitors()
        _cancel_if_requested(cancelled)
        wallpaper = compose_black(monitors, wallpaper_path)
        _cancel_if_requested(cancelled)
        setter.apply_black(wallpaper, profile.desktop)
        return SwitchResult(profile.name, wallpaper, [], monitors, applied=False, action="black-screen")

    _cancel_if_requested(cancelled)
    supports_solid_black = setter.supports_solid_black(profile.desktop)
    _cancel_if_requested(cancelled)
    if supports_solid_black:
        # Privacy action first: do not wait behind a slow save-current copy. Reapply
        # after taking the lock so this also wins against an in-flight rotation.
        setter.apply_black(None, profile.desktop)

    # Hold the state lock before touching the live black cache file. This keeps
    # save-current snapshots stable and serializes black-screen with rotations.
    with state_transaction() as state:
        if supports_solid_black:
            setter.apply_black(None, profile.desktop)
            monitors = detect_monitors()
            wallpaper = compose_black(monitors, wallpaper_path)
        else:
            _cancel_if_requested(cancelled)
            monitors = detect_monitors()
            _cancel_if_requested(cancelled)
            wallpaper = compose_black(monitors, wallpaper_path)
            _cancel_if_requested(cancelled)
            setter.apply_black(wallpaper, profile.desktop)

        state.active_profile = profile.name
        state.black_screen = True
        state.paused = True
        state.last_wallpaper = str(wallpaper)
        state.last_images = []

    return SwitchResult(profile.name, wallpaper, [], monitors, applied=True, action="black-screen")


def pause() -> RuntimeState:
    with state_transaction() as state:
        state.paused = True
        return RuntimeState.from_dict(state.to_dict())


def _create_staged_output(output: Path) -> tuple[int, Path]:
    """Create a same-directory staging file while honoring the caller's umask."""
    for _ in range(100):
        staged = output.with_name(f".{output.name}.{secrets.token_hex(8)}.tmp")
        try:
            fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        return fd, staged
    raise FileExistsError(f"Could not create a staging file beside: {output}")


def save_current_wallpaper(destination: str | Path, *, overwrite: bool = False) -> Path:
    """Atomically copy a stable snapshot of the current wallpaper to a PNG file."""
    output = Path(destination).expanduser()
    if output.suffix.lower() != ".png":
        raise ValueError("Saved wallpaper destination must use a .png extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    destination_mode: int | None = None
    try:
        destination_info = output.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISDIR(destination_info.st_mode):
            raise ValueError("Saved wallpaper destination must be a PNG file path, not a directory")
        if stat.S_ISLNK(destination_info.st_mode):
            raise ValueError("Saved wallpaper destination must not be a symbolic link")
        if not stat.S_ISREG(destination_info.st_mode):
            raise ValueError("Saved wallpaper destination must be a regular file")
        if not overwrite:
            raise FileExistsError(f"Destination already exists: {output}")
        destination_mode = stat.S_IMODE(destination_info.st_mode) & 0o777

    staged: Path | None = None
    try:
        # Live rotations hold this same lock while composing the alternating cache
        # slots. Keep it until the snapshot is fully staged so neither slot can be
        # overwritten midway through this copy.
        with state_transaction() as state:
            if not state.last_wallpaper:
                raise RuntimeError("No current wallpaper is available; run 'next' first")

            source = Path(state.last_wallpaper).expanduser()
            if not source.is_file():
                raise FileNotFoundError(f"Current wallpaper file is missing: {source}")
            if source.resolve() == output.resolve():
                raise ValueError("Saved wallpaper destination must differ from the current cache file")

            with source.open("rb") as source_file:
                fd, staged = _create_staged_output(output)
                with os.fdopen(fd, "wb") as staged_file:
                    if destination_mode is not None:
                        os.fchmod(staged_file.fileno(), destination_mode)
                    shutil.copyfileobj(source_file, staged_file)
                    staged_file.flush()
                    os.fsync(staged_file.fileno())

        if overwrite:
            # Replace the completed snapshot atomically. If a symlink is created in
            # the narrow race after validation, os.replace replaces the link itself
            # rather than following its target.
            os.replace(staged, output)
        else:
            # The staging file lives beside the output, so this hard link is an
            # atomic no-clobber install on the same filesystem.
            try:
                os.link(staged, output)
            except FileExistsError as exc:
                raise FileExistsError(f"Destination already exists: {output}") from exc
        return output.resolve()
    finally:
        try:
            if staged is not None:
                staged.unlink()
        except FileNotFoundError:
            pass


def resume(profile_name: str | None = None, *, dry_run: bool = False) -> SwitchResult:
    return switch_once(profile_name, dry_run=dry_run, clear_black=True)


def run_loop(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    defer_first: bool = False,
    first_delay_min_seconds: float = 0.0,
) -> None:
    cfg: Config = load_config()
    profile = cfg.get_profile(profile_name)
    print(f"Running Mint Background Switcher profile {profile.name!r}; interval={profile.interval_minutes} minute(s)")
    if defer_first:
        delay = max(profile.interval_minutes * 60.0, first_delay_min_seconds, 5.0)
        print(f"Deferring first wallpaper change for {delay:.0f} second(s)", flush=True)
        time.sleep(delay)
    while True:
        state = load_state()
        cfg = load_config()
        profile = cfg.get_profile(profile_name)
        if state.black_screen:
            time.sleep(min(max(profile.interval_minutes * 60.0, 5.0), 60.0))
            continue
        if not state.paused:
            try:
                result = switch_once(profile.name, dry_run=dry_run)
                print(f"Generated {result.wallpaper} for {len(result.monitors)} monitor(s)", flush=True)
            except Exception as exc:
                print(f"Mint Background Switcher error: {exc}", flush=True)
        time.sleep(max(profile.interval_minutes * 60.0, 5.0))
