"""Core wallpaper switching service functions."""

from __future__ import annotations

import os
import random
import secrets
import shutil
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import (
    MAX_EXCLUDED_IMAGES,
    Config,
    Profile,
    config_file,
    in_night_window,
    load_config,
)
from .desktop import DesktopSetter
from .images import (
    ImageDecodeError,
    apply_effect,
    compose_black,
    compose_collage,
    compose_montage,
    compose_per_monitor,
    compose_polaroid,
    compose_postcard,
    compose_span,
    image_orientation,
    is_usable_image,
    scan_images,
)
from .library_index import IndexSnapshot, LibraryIndex, LibrarySelection, orientation_matches
from .monitor import Monitor, detect_monitors, monitor_orientation
from .paths import generated_wallpaper_path
from .run_conditions import active_run_conditions
from .state import RuntimeState, draw_many, load_state, state_transaction
from .storage import atomic_write_json_unlocked, locked_file, lock_path_for, read_json_unlocked
from .working_storage import ensure_configured_working_directory


@dataclass(slots=True)
class SwitchResult:
    profile: str
    wallpaper: Path
    images: list[str]
    monitors: list[Monitor]
    applied: bool
    action: str
    lockscreen_note: str = ""


class SwitchCancelled(RuntimeError):
    """Raised when a background rotation is cancelled before desktop activation."""


def current_source_images() -> list[Path]:
    """Return the unique local source paths used by the current wallpaper.

    This is a read-only snapshot of runtime state. Paths are made absolute without
    requiring the source files to still be mounted or present.
    """

    images: list[Path] = []
    seen: set[str] = set()
    for raw_path in load_state().last_images:
        if not raw_path.strip():
            continue
        try:
            image = Path(os.path.abspath(Path(raw_path).expanduser()))
        except (OSError, RuntimeError):
            continue
        key = os.fspath(image)
        if key not in seen:
            seen.add(key)
            images.append(image)
    return images


def _normalized_exclusion_path(raw: object) -> str:
    """Absolute form of a never-show-again entry, or raise when unusable."""
    candidate = str(raw or "").strip()
    if not candidate or any(ch in candidate for ch in "\r\n\t"):
        raise ValueError("picture path is empty or contains a line break")
    return os.path.abspath(os.path.expanduser(candidate))


def _exclusion_match_set(profile: Profile) -> frozenset[str]:
    """Every path form that satisfies a saved never-show-again entry.

    Entries are stored as the absolute path captured at exclusion time, but
    pool paths may be the resolved realpath (dry-run scan) or a plain abspath
    (library index), so matching accepts the stored, abspath, and resolved
    forms of each entry.
    """
    if not profile.excluded_images:
        return frozenset()
    matches: set[str] = set()
    for raw in profile.excluded_images:
        matches.add(raw)
        try:
            expanded = os.path.expanduser(raw)
            matches.add(os.path.abspath(expanded))
            matches.add(str(Path(expanded).resolve(strict=False)))
        except (OSError, RuntimeError, ValueError):
            continue
    return frozenset(matches)


def _mutate_excluded_images(profile_name: str | None, mutate: Callable[[Profile], list[str]]) -> list[str]:
    """Apply one never-show-again change to the freshest saved config."""
    path = config_file()
    with locked_file(lock_path_for(path)):
        config = Config.from_dict(read_json_unlocked(path)) if path.exists() else Config.default()
        profile = config.get_profile(profile_name)
        result = mutate(profile)
        atomic_write_json_unlocked(path, config.to_dict())
    return result


def get_excluded_images(profile_name: str | None = None) -> list[str]:
    """Return the profile's never-show-again list (read-only)."""
    return list(load_config(create=False).get_profile(profile_name).excluded_images)


def excluded_path_set(profile_name: str | None = None) -> frozenset[str]:
    """All path forms matched by the profile's never-show-again entries."""
    return _exclusion_match_set(load_config(create=False).get_profile(profile_name))


def add_excluded_images(profile_name: str | None, raw_paths: Iterable[str]) -> list[str]:
    """Add pictures to the profile's never-show-again list.

    Returns the entries actually added. Paths are normalized to absolute
    form; duplicates are dropped and the list is capped at the config limit.
    """

    def _add(profile: Profile) -> list[str]:
        added: list[str] = []
        for raw in raw_paths:
            if len(profile.excluded_images) >= MAX_EXCLUDED_IMAGES:
                break
            normalized = _normalized_exclusion_path(raw)
            if normalized in profile.excluded_images:
                continue
            profile.excluded_images.append(normalized)
            added.append(normalized)
        return added

    return _mutate_excluded_images(profile_name, _add)


def remove_excluded_images(profile_name: str | None, raw_paths: Iterable[str]) -> list[str]:
    """Remove pictures from the profile's never-show-again list.

    Returns the entries actually removed.
    """

    def _remove(profile: Profile) -> list[str]:
        targets = {_normalized_exclusion_path(raw) for raw in raw_paths}
        removed = [path for path in profile.excluded_images if path in targets]
        profile.excluded_images = [path for path in profile.excluded_images if path not in targets]
        return removed

    return _mutate_excluded_images(profile_name, _remove)


def clear_excluded_images(profile_name: str | None) -> int:
    """Empty the profile's never-show-again list; return how many entries left."""

    def _clear(profile: Profile) -> list[str]:
        removed = list(profile.excluded_images)
        profile.excluded_images = []
        return removed

    return len(_mutate_excluded_images(profile_name, _clear))


def exclude_current_images(
    profile_name: str | None = None,
    paths: Sequence[str | Path] | None = None,
) -> list[str]:
    """Exclude the current wallpaper's source pictures from future rotation.

    With no explicit paths, the sources recorded for the currently applied
    wallpaper are used, so multi-picture layouts exclude every picture that
    is currently on screen.
    """
    if paths is None:
        paths = [str(image) for image in current_source_images()]
    sources = [str(path) for path in paths]
    if not sources:
        return []
    return add_excluded_images(profile_name, sources)


def _cancel_if_requested(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise SwitchCancelled("wallpaper rotation was cancelled")


def _profile_bucket(profile: Profile, suffix: str) -> str:
    return f"profile:{profile.name}:{suffix}"


def _orientation_requirements(
    profile: Profile,
    monitors: list[Monitor],
    mode: str,
) -> tuple[str | None, ...] | None:
    """Per-slot monitor orientations for one rotation, or None when matching does not apply.

    Orientation matching only shapes layouts where one picture fills each
    wallpaper slot (shared, same, span, per-monitor); multi-picture layouts
    (montage, collage, postcard, polaroid) stay unfiltered. For a single shared
    picture it applies only when every monitor shares one non-square
    orientation.
    """
    if not profile.match_orientation:
        return None
    if mode in ("montage", "collage", "postcard", "polaroid"):
        return None
    if mode in ("shared", "per-monitor"):
        return tuple(monitor_orientation(monitor) for monitor in monitors)
    if mode in ("same", "span"):
        orientations = {monitor_orientation(monitor) for monitor in monitors}
        if orientations in ({"landscape"}, {"portrait"}):
            return (orientations.pop(),)
    return None


def _draw_usable_many(
    state: RuntimeState,
    bucket: str,
    pool: list[str],
    count: int,
    *,
    rng: random.Random | None,
    sequential: bool = False,
) -> list[str]:
    """Draw images while discarding selected files that Pillow cannot decode."""

    candidates = list(pool)
    selected: list[str] = []
    while candidates and len(selected) < count:
        batch = draw_many(state, bucket, candidates, count - len(selected), rng=rng, sequential=sequential)
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
    excluded: frozenset[str] = frozenset()

    @property
    def empty(self) -> bool:
        if self.paths is not None:
            return not self.paths
        if self.snapshot is None:
            return True
        if self.index is None or not self.excluded:
            return self.snapshot.image_count <= 0
        return self.index.available_count(self.snapshot.signature, self.excluded) == 0


def _load_image_pool(
    folders: list[str],
    recursive: bool,
    *,
    dry_run: bool,
    index: LibraryIndex | None,
    selection: LibrarySelection | None,
    cancelled: Callable[[], bool] | None,
    progress: Callable[[int, str], None] | None,
    min_image_size: int = 0,
    ignore_hidden: bool = False,
    ignore_patterns: Iterable[str] = (),
    image_types: Iterable[str] = (),
    excluded: frozenset[str] = frozenset(),
) -> _ImagePool:
    if dry_run:
        paths = scan_images(folders, recursive, min_image_size, ignore_hidden, ignore_patterns, image_types)
        if excluded:
            paths = [path for path in paths if path not in excluded]
        return _ImagePool(paths=paths, excluded=excluded)
    if index is None:  # pragma: no cover - guarded by switch setup
        raise RuntimeError("live wallpaper rotation requires an image index")
    snapshot = index.ensure(
        folders,
        recursive=recursive,
        min_image_size=min_image_size,
        ignore_hidden=ignore_hidden,
        ignore_patterns=ignore_patterns,
        image_types=image_types,
        cancelled=cancelled,
        progress=progress,
    )
    return _ImagePool(index=index, snapshot=snapshot, selection=selection, excluded=excluded)


def _draw_oriented_from_list(
    state: RuntimeState,
    bucket: str,
    paths: list[str],
    orientations: Sequence[str | None],
    *,
    rng: random.Random | None,
    sequential: bool = False,
) -> list[str]:
    """Dry-run selection that prefers each slot's monitor orientation.

    Mirrors the no-repeat pool order of ``draw_many`` (sequential folder order or a
    random shuffle) so the preview matches the live rotation, but within that order
    it prefers a picture whose orientation matches the slot's monitor orientation.
    A monitor with no matching picture available falls back to whatever remains, so
    rotation never blocks on shape alone.
    """
    random_source = rng or random.SystemRandom()
    pool_set = {str(Path(p).expanduser().resolve()) for p in paths}
    available = [p for p in state.remaining.get(bucket, []) if p in pool_set]
    fresh = not available
    if fresh:
        available = sorted(pool_set)
    if sequential:
        available.sort()
    elif fresh:
        random_source.shuffle(available)

    orientation_by_path: dict[str, str] = {}

    def orientation_of(path: str) -> str:
        orientation = orientation_by_path.get(path)
        if orientation is None:
            orientation = image_orientation(path)
            orientation_by_path[path] = orientation
        return orientation

    if not pool_set or not orientations:
        return []
    selected: list[str] = []
    selected_set: set[str] = set()
    for required in orientations:
        if not available:
            # Cycle wrap: when fewer pictures than slots remain, reuse pictures
            # exactly like draw_many, so rotation never stops on pool size.
            pool_full = [p for p in pool_set if p not in selected_set] or list(pool_set)
            if sequential:
                pool_full.sort()
            else:
                random_source.shuffle(pool_full)
            available = pool_full
        chosen = None
        for path in available:
            if orientation_matches(required, orientation_of(path)):
                chosen = path
                break
        if chosen is None:
            # No matching picture: consume the same position draw_many would so
            # leftovers stay interchangeable with ordinary draws.
            chosen = available[0] if sequential else available[-1]
        available.remove(chosen)
        selected.append(chosen)
        selected_set.add(chosen)
    state.remaining[bucket] = available
    return selected


def _draw_from_pool(
    state: RuntimeState,
    pool: _ImagePool,
    bucket: str,
    count: int,
    *,
    rng: random.Random | None,
    require_usable: bool = False,
    sequential: bool = False,
    orientations: Sequence[str | None] | None = None,
) -> list[str]:
    oriented: tuple[str | None, ...] | None
    if orientations is not None and len(orientations) == count:
        oriented = tuple(orientations)
    else:
        oriented = None
    if pool.paths is not None:
        if oriented is not None:
            return _draw_oriented_from_list(
                state,
                bucket,
                pool.paths,
                orientations,
                rng=rng,
                sequential=sequential,
            )
        if require_usable:
            return _draw_usable_many(state, bucket, pool.paths, count, rng=rng, sequential=sequential)
        return draw_many(state, bucket, pool.paths, count, rng=rng, sequential=sequential)
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
            sequential=sequential,
            orientations=oriented[len(selected) :] if oriented is not None else None,
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


def _discard_from_pool(pool: _ImagePool, path: str) -> None:
    """Discard one source that failed during actual pixel decoding."""

    if pool.paths is not None:
        pool.paths = [candidate for candidate in pool.paths if candidate != path]
        return
    if pool.snapshot is None:
        return
    selector = pool.selection or pool.index
    if selector is not None:
        selector.discard(pool.snapshot.signature, path)


def _draw_one_from_pool(
    state: RuntimeState,
    pool: _ImagePool,
    bucket: str,
    *,
    rng: random.Random | None,
    sequential: bool = False,
    orientation: str | None = None,
) -> str:
    selected = _draw_from_pool(
        state,
        pool,
        bucket,
        1,
        rng=rng,
        sequential=sequential,
        orientations=(orientation,) if orientation is not None else None,
    )
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


def _mirror_lockscreen(profile: Profile, wallpaper: Path, *, dry_run: bool) -> str:
    """Mirror an applied wallpaper to the lock screen when the profile asks for it.

    Returns a short user-facing note describing the mirror outcome (or an empty
    string when the profile does not enable mirroring). Failures are reported
    through the note so the desktop wallpaper path is never broken.
    """
    if not profile.mirror_lockscreen:
        return ""
    result = DesktopSetter(dry_run=dry_run).mirror_lockscreen(wallpaper, profile.desktop)
    return result.detail


def _apply_black_fallback(
    profile: Profile,
    monitors: list[Monitor],
    wallpaper_path: Path,
    *,
    dry_run: bool,
    cancelled: Callable[[], bool] | None,
) -> tuple[Path, str]:
    """Apply an all-black non-sticky fallback when configured image folders are empty.

    This is intentionally different from the user-invoked black-screen action: it
    does not pause rotation or set black_screen state, so removable drives coming
    back online on a later tick can resume normal wallpapers automatically.
    """
    wallpaper = compose_black(monitors, wallpaper_path)
    _cancel_if_requested(cancelled)
    DesktopSetter(dry_run=dry_run).apply_black(wallpaper, profile.desktop)
    return wallpaper, _mirror_lockscreen(profile, wallpaper, dry_run=dry_run)


def _apply_composed_wallpaper(
    profile: Profile,
    wallpaper: Path,
    *,
    dry_run: bool,
    rng: random.Random | None,
    cancelled: Callable[[], bool] | None,
) -> str:
    _cancel_if_requested(cancelled)
    apply_effect(wallpaper, profile.effect, rng=rng)
    _cancel_if_requested(cancelled)
    DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)
    return _mirror_lockscreen(profile, wallpaper, dry_run=dry_run)


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


def night_schedule_action(profile: Profile, state: RuntimeState, now: datetime) -> str:
    """Decide the per-tick night-schedule step for the background loop.

    Returns one of:

    - ``"enter"``: the night window is active and the desktop is not black yet,
      so the loop should apply the black-screen action.
    - ``"exit"``: the night window has ended and the current black screen was
      caused by the schedule, so the loop should resume rotation automatically.
    - ``"black"``: keep the current black screen (night still active, or a
      manual black screen the schedule must not touch) and skip rotation.
    - ``"off"``: no night-schedule action; the loop runs its ordinary tick.
    """
    if not profile.night_black_screen:
        return "off"
    night_active = in_night_window(profile.night_start, profile.night_end, now)
    if night_active:
        return "enter" if not state.black_screen else "black"
    if state.black_screen and state.black_reason == "night":
        return "exit"
    if state.black_screen:
        return "black"
    return "off"


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
    excluded_paths = _exclusion_match_set(profile)
    working_directory = ensure_configured_working_directory(cfg)
    index = None if dry_run else LibraryIndex(working_directory)
    selection = selection_scope.begin(index)
    if selection is not None and excluded_paths:
        selection.exclude(excluded_paths)
    monitors = detect_monitors()
    state.active_profile = profile.name
    orientation_requirements = _orientation_requirements(profile, monitors, profile.mode)
    single_orientation = orientation_requirements[0] if orientation_requirements else None
    wallpaper_path, next_slot = _next_wallpaper_path(
        profile,
        state,
        dry_run=dry_run,
        working_directory=working_directory,
    )

    selections: dict[str, str] = {}
    images_used: list[str] = []
    action: str = "next"
    lockscreen_note: str = ""
    if profile.mode == "span":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
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
                sequential=profile.sequential,
                orientation=single_orientation,
            )
            wallpaper = compose_span(monitors, image, wallpaper_path, bar_color=profile.bar_color, fit_mode=profile.fit_mode)
            images_used = [image]
            lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
    elif profile.mode == "montage":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
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
                sequential=profile.sequential,
            )
            montage_by_monitor = {
                monitor.name: chosen[index * 4 : (index + 1) * 4]
                for index, monitor in enumerate(monitors)
            }
            images_used = chosen
            wallpaper = compose_montage(
                monitors,
                montage_by_monitor,
                wallpaper_path,
                bar_color=profile.bar_color,
                fit_mode=profile.fit_mode,
            )
            lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
    elif profile.mode == "collage":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            bucket = _profile_bucket(profile, "collage")
            decode_retries_remaining = max(1, len(monitors) * 5)
            while True:
                _cancel_if_requested(cancelled)
                chosen = _draw_from_pool(
                    state,
                    pool,
                    bucket,
                    len(monitors) * 5,
                    rng=rng,
                    sequential=profile.sequential,
                )
                if not chosen:
                    wallpaper, lockscreen_note = _apply_black_fallback(
                        profile,
                        monitors,
                        wallpaper_path,
                        dry_run=dry_run,
                        cancelled=cancelled,
                    )
                    action = "black-fallback"
                    break
                collage_by_monitor = {
                    monitor.name: chosen[index * 5 : (index + 1) * 5]
                    for index, monitor in enumerate(monitors)
                }
                try:
                    wallpaper = compose_collage(
                        monitors,
                        collage_by_monitor,
                        wallpaper_path,
                        bar_color=profile.bar_color,
                        fit_mode=profile.fit_mode,
                    )
                except ImageDecodeError as exc:
                    _discard_from_pool(pool, exc.image_path)
                    decode_retries_remaining -= 1
                    if decode_retries_remaining <= 0:
                        wallpaper, lockscreen_note = _apply_black_fallback(
                            profile,
                            monitors,
                            wallpaper_path,
                            dry_run=dry_run,
                            cancelled=cancelled,
                        )
                        action = "black-fallback"
                        break
                    continue
                images_used = chosen
                lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
                break
    elif profile.mode == "postcard":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            bucket = _profile_bucket(profile, "postcard")
            count_per_monitor = profile.postcard_count
            requested_count = count_per_monitor if profile.postcard_span else len(monitors) * count_per_monitor
            while True:
                _cancel_if_requested(cancelled)
                chosen = _draw_from_pool(
                    state,
                    pool,
                    bucket,
                    requested_count,
                    rng=rng,
                    sequential=profile.sequential,
                )
                if not chosen:
                    wallpaper, lockscreen_note = _apply_black_fallback(
                        profile,
                        monitors,
                        wallpaper_path,
                        dry_run=dry_run,
                        cancelled=cancelled,
                    )
                    action = "black-fallback"
                    break
                if profile.postcard_span:
                    postcard_by_monitor = {monitors[0].name: chosen}
                else:
                    postcard_by_monitor = {
                        monitor.name: chosen[index * count_per_monitor : (index + 1) * count_per_monitor]
                        for index, monitor in enumerate(monitors)
                    }
                try:
                    wallpaper = compose_postcard(
                        monitors,
                        postcard_by_monitor,
                        wallpaper_path,
                        bar_color=profile.bar_color,
                        size=profile.postcard_size,
                        span=profile.postcard_span,
                        tilt=profile.postcard_tilt,
                        background=profile.postcard_background,
                        captions=profile.postcard_captions,
                        rng=rng,
                    )
                except ImageDecodeError as exc:
                    _discard_from_pool(pool, exc.image_path)
                    continue
                images_used = chosen
                lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
                break
    elif profile.mode == "polaroid":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            bucket = _profile_bucket(profile, "polaroid")
            count_per_monitor = profile.polaroid_count
            requested_count = count_per_monitor if profile.polaroid_span else len(monitors) * count_per_monitor
            while True:
                _cancel_if_requested(cancelled)
                chosen = _draw_from_pool(
                    state,
                    pool,
                    bucket,
                    requested_count,
                    rng=rng,
                    sequential=profile.sequential,
                )
                if not chosen:
                    wallpaper, lockscreen_note = _apply_black_fallback(
                        profile,
                        monitors,
                        wallpaper_path,
                        dry_run=dry_run,
                        cancelled=cancelled,
                    )
                    action = "black-fallback"
                    break
                if profile.polaroid_span:
                    polaroid_by_monitor = {monitors[0].name: chosen}
                else:
                    polaroid_by_monitor = {
                        monitor.name: chosen[index * count_per_monitor : (index + 1) * count_per_monitor]
                        for index, monitor in enumerate(monitors)
                    }
                try:
                    wallpaper = compose_polaroid(
                        monitors,
                        polaroid_by_monitor,
                        wallpaper_path,
                        bar_color=profile.bar_color,
                        size=profile.polaroid_size,
                        span=profile.polaroid_span,
                        tilt=profile.polaroid_tilt,
                        captions=profile.polaroid_captions,
                        rng=rng,
                    )
                except ImageDecodeError as exc:
                    _discard_from_pool(pool, exc.image_path)
                    continue
                images_used = chosen
                lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
                break
    elif profile.mode == "same":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
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
                sequential=profile.sequential,
                orientation=single_orientation,
            )
            selections = {monitor.name: image for monitor in monitors}
            images_used = [image]
            wallpaper = compose_per_monitor(
                monitors,
                selections,
                wallpaper_path,
                bar_color=profile.bar_color,
                fit_mode=profile.fit_mode,
            )
            lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
    elif profile.mode == "shared":
        pool = _load_image_pool(
            profile.shared_folders,
            profile.recursive,
            dry_run=dry_run,
            index=index,
            selection=selection,
            cancelled=cancelled,
            progress=progress,
            min_image_size=profile.min_image_size,
            ignore_hidden=profile.ignore_hidden,
            ignore_patterns=profile.ignore_patterns,
            image_types=profile.image_types,
            excluded=excluded_paths,
        )
        if pool.empty:
            wallpaper, lockscreen_note = _apply_black_fallback(
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
                sequential=profile.sequential,
                orientations=orientation_requirements,
            )
            for monitor, image in zip(monitors, chosen):
                selections[monitor.name] = image
            images_used = chosen
            wallpaper = compose_per_monitor(
                monitors,
                selections,
                wallpaper_path,
                bar_color=profile.bar_color,
                fit_mode=profile.fit_mode,
            )
            lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)
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
                min_image_size=profile.min_image_size,
                ignore_hidden=profile.ignore_hidden,
                ignore_patterns=profile.ignore_patterns,
                image_types=profile.image_types,
                excluded=excluded_paths,
            )
            if not pool.empty:
                pools_by_monitor[monitor.name] = pool
            else:
                missing_monitors.append(monitor.name)
        if missing_monitors:
            wallpaper, lockscreen_note = _apply_black_fallback(
                profile,
                monitors,
                wallpaper_path,
                dry_run=dry_run,
                cancelled=cancelled,
            )
            action = "black-fallback"
        else:
            for position, monitor in enumerate(monitors):
                image = _draw_one_from_pool(
                    state,
                    pools_by_monitor[monitor.name],
                    _profile_bucket(profile, f"monitor:{monitor.name}"),
                    rng=rng,
                    sequential=profile.sequential,
                    orientation=orientation_requirements[position] if orientation_requirements else None,
                )
                selections[monitor.name] = image
                images_used.append(image)
            wallpaper = compose_per_monitor(
                monitors,
                selections,
                wallpaper_path,
                bar_color=profile.bar_color,
                fit_mode=profile.fit_mode,
            )
            lockscreen_note = _apply_composed_wallpaper(profile, wallpaper, dry_run=dry_run, rng=rng, cancelled=cancelled)

    if next_slot is not None:
        state.wallpaper_slot = next_slot
    if clear_black:
        state.black_screen = False
        state.black_reason = ""
        state.paused = False
    state.last_wallpaper = str(wallpaper)
    state.last_images = images_used
    return SwitchResult(
        profile.name,
        wallpaper,
        images_used,
        monitors,
        applied=not dry_run,
        action=action,
        lockscreen_note=lockscreen_note,
    )


def black_screen(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    cancelled: Callable[[], bool] | None = None,
    reason: str = "manual",
) -> SwitchResult:
    """Turn every monitor black and stay black until resumed.

    ``reason`` records why the black screen is active: ``"night"`` marks
    schedule-driven black screens so the loop can resume automatically when
    the night window ends, while any other value (including ``"manual"``)
    keeps the classic sticky behavior where only an explicit resume or
    rotation clears it.
    """
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
        return SwitchResult(
            profile.name,
            wallpaper,
            [],
            monitors,
            applied=False,
            action="black-screen",
            lockscreen_note=_mirror_lockscreen(profile, wallpaper, dry_run=True),
        )

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
        state.black_reason = "night" if reason == "night" else "manual"
        state.paused = True
        state.last_wallpaper = str(wallpaper)
        state.last_images = []

    return SwitchResult(
        profile.name,
        wallpaper,
        [],
        monitors,
        applied=True,
        action="black-screen",
        lockscreen_note=_mirror_lockscreen(profile, wallpaper, dry_run=False),
    )


def pause() -> RuntimeState:
    with state_transaction() as state:
        state.paused = True
        return RuntimeState.from_dict(state.to_dict())


def toggle_pause() -> RuntimeState:
    """Flip the paused flag without applying a wallpaper.

    Unlike :func:`resume`, toggling back to running does not immediately
    switch pictures: the background loop applies the next rotation on its
    normal cadence. This keeps the Pause/Resume hotkey predictable.
    """
    with state_transaction() as state:
        state.paused = not state.paused
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
    skip_first: bool = False,
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
        # Dry-run previews keep their historic behavior and never trigger the
        # scheduled black screen or its automatic resume.
        night_action = "off" if dry_run else night_schedule_action(profile, state, datetime.now())
        # Run conditions only pause *scheduled* switching in this loop; manual
        # switches (Save & Apply Now, `next`, resume) always apply. Probes are
        # fail-open by design, and detection failure here must not stop the
        # background loop either: an exception means "no condition holds".
        if dry_run:
            suppressed_reasons: list[str] = []
        else:
            try:
                suppressed_reasons = active_run_conditions(profile)
            except Exception:
                suppressed_reasons = []
        retry_delay = min(max(profile.interval_minutes * 60.0, 5.0), 60.0)
        rotated_this_tick = False
        if night_action == "enter":
            try:
                result = black_screen(profile.name, reason="night")
                state = load_state()
                print(
                    f"Night schedule active; keeping the desktop black until {profile.night_end} local time",
                    flush=True,
                )
                if result.lockscreen_note:
                    print(result.lockscreen_note, flush=True)
            except Exception as exc:
                print(f"Mint Background Switcher error: {exc}", flush=True)
        elif night_action == "exit":
            if suppressed_reasons:
                # The window ended, but run conditions still hold; the next
                # tick retries the resume once they clear.
                print(
                    f"Night schedule ended, but scheduled switching is paused ({'; '.join(suppressed_reasons)}); "
                    "will resume as soon as the conditions clear",
                    flush=True,
                )
            else:
                try:
                    result = switch_once(profile.name)
                    state = load_state()
                    rotated_this_tick = True
                    print("Night schedule ended; resuming rotation", flush=True)
                    if result.lockscreen_note:
                        print(result.lockscreen_note, flush=True)
                except Exception as exc:
                    print(f"Mint Background Switcher error: {exc}", flush=True)
        if state.black_screen:
            time.sleep(retry_delay)
            continue
        if rotated_this_tick:
            time.sleep(max(profile.interval_minutes * 60.0, 5.0))
            continue
        if not state.paused:
            if suppressed_reasons:
                # Do not consume the rotate-at-startup skip while suppressed,
                # mirroring the pause/black-screen handling.
                print(
                    f"Wallpaper switch paused ({'; '.join(suppressed_reasons)}); will retry sooner",
                    flush=True,
                )
            elif skip_first:
                # Rotate-at-startup is off: keep the current background and let
                # the normal interval take over. Black-screen/pause cycles do not
                # consume the skip, so resuming from either still switches on time.
                skip_first = False
                print("Rotate at startup is off; keeping the current background until the next interval", flush=True)
            else:
                try:
                    result = switch_once(profile.name, dry_run=dry_run)
                    print(f"Generated {result.wallpaper} for {len(result.monitors)} monitor(s)", flush=True)
                    if result.lockscreen_note:
                        print(result.lockscreen_note, flush=True)
                except Exception as exc:
                    print(f"Mint Background Switcher error: {exc}", flush=True)
        if suppressed_reasons:
            # Retry on a short cadence so a clearing condition resumes the
            # schedule without waiting a full interval.
            time.sleep(retry_delay)
        else:
            time.sleep(max(profile.interval_minutes * 60.0, 5.0))
