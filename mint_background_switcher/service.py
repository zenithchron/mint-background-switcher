"""Core wallpaper switching service functions."""

from __future__ import annotations

import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Profile, load_config
from .desktop import DesktopSetter
from .images import compose_black, compose_per_monitor, compose_span, scan_images
from .monitor import Monitor, detect_monitors
from .paths import generated_wallpaper_path
from .state import RuntimeState, draw_many, draw_one, load_state, state_transaction


@dataclass(slots=True)
class SwitchResult:
    profile: str
    wallpaper: Path
    images: list[str]
    monitors: list[Monitor]
    applied: bool
    action: str


def _profile_bucket(profile: Profile, suffix: str) -> str:
    return f"profile:{profile.name}:{suffix}"


def _next_wallpaper_path(profile: Profile, state: RuntimeState, *, dry_run: bool) -> tuple[Path, int | None]:
    """Return an off-screen output path and the live slot to save after a successful apply.

    Live rotations alternate between two active files so the desktop never watches the
    currently displayed image being overwritten. Dry-runs write to their own preview
    file instead of touching either live file.
    """
    if dry_run:
        return generated_wallpaper_path(profile.name, suffix="dry-run"), None
    slot = (state.wallpaper_slot + 1) % 2
    return generated_wallpaper_path(profile.name, suffix=f"active-{slot}"), slot


def _apply_black_fallback(
    profile: Profile,
    monitors: list[Monitor],
    wallpaper_path: Path,
    *,
    dry_run: bool,
) -> Path:
    """Apply an all-black non-sticky fallback when configured image folders are empty.

    This is intentionally different from the user-invoked black-screen action: it
    does not pause rotation or set black_screen state, so removable drives coming
    back online on a later tick can resume normal wallpapers automatically.
    """
    wallpaper = compose_black(monitors, wallpaper_path)
    DesktopSetter(dry_run=dry_run).apply_black(wallpaper, profile.desktop)
    return wallpaper


def switch_once(
    profile_name: str | None = None,
    *,
    dry_run: bool = False,
    clear_black: bool = True,
    rng: random.Random | None = None,
) -> SwitchResult:
    if dry_run:
        transient_state = RuntimeState.from_dict(load_state().to_dict())
        return _switch_once_with_state(
            profile_name,
            transient_state,
            dry_run=True,
            clear_black=clear_black,
            rng=rng,
        )
    with state_transaction() as state:
        return _switch_once_with_state(
            profile_name,
            state,
            dry_run=False,
            clear_black=clear_black,
            rng=rng,
        )


def _switch_once_with_state(
    profile_name: str | None,
    state: RuntimeState,
    *,
    dry_run: bool,
    clear_black: bool,
    rng: random.Random | None,
) -> SwitchResult:
    cfg = load_config()
    profile = cfg.get_profile(profile_name)
    monitors = detect_monitors()
    state.active_profile = profile.name
    wallpaper_path, next_slot = _next_wallpaper_path(profile, state, dry_run=dry_run)

    selections: dict[str, str] = {}
    images_used: list[str] = []
    action = "next"
    if profile.mode == "span":
        pool = scan_images(profile.shared_folders, profile.recursive)
        if not pool:
            wallpaper = _apply_black_fallback(profile, monitors, wallpaper_path, dry_run=dry_run)
            action = "black-fallback"
        else:
            image = draw_one(state, _profile_bucket(profile, "span"), pool, rng=rng)
            wallpaper = compose_span(monitors, image, wallpaper_path)
            images_used = [image]
            DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)
    elif profile.mode == "same":
        pool = scan_images(profile.shared_folders, profile.recursive)
        if not pool:
            wallpaper = _apply_black_fallback(profile, monitors, wallpaper_path, dry_run=dry_run)
            action = "black-fallback"
        else:
            image = draw_one(state, _profile_bucket(profile, "same"), pool, rng=rng)
            selections = {monitor.name: image for monitor in monitors}
            images_used = [image]
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path)
            DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)
    elif profile.mode == "shared":
        pool = scan_images(profile.shared_folders, profile.recursive)
        if not pool:
            wallpaper = _apply_black_fallback(profile, monitors, wallpaper_path, dry_run=dry_run)
            action = "black-fallback"
        else:
            chosen = draw_many(state, _profile_bucket(profile, "shared"), pool, len(monitors), rng=rng)
            for monitor, image in zip(monitors, chosen):
                selections[monitor.name] = image
            images_used = chosen
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path)
            DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)
    else:
        pools_by_monitor: dict[str, list[str]] = {}
        missing_monitors: list[str] = []
        for monitor in monitors:
            folders = profile.folders_for_monitor(monitor.name)
            pool = scan_images(folders, profile.recursive)
            if pool:
                pools_by_monitor[monitor.name] = pool
            else:
                missing_monitors.append(monitor.name)
        if missing_monitors:
            wallpaper = _apply_black_fallback(profile, monitors, wallpaper_path, dry_run=dry_run)
            action = "black-fallback"
        else:
            for monitor in monitors:
                image = draw_one(state, _profile_bucket(profile, f"monitor:{monitor.name}"), pools_by_monitor[monitor.name], rng=rng)
                selections[monitor.name] = image
                images_used.append(image)
            wallpaper = compose_per_monitor(monitors, selections, wallpaper_path)
            DesktopSetter(dry_run=dry_run).apply(wallpaper, profile.desktop)

    if next_slot is not None:
        state.wallpaper_slot = next_slot
    if clear_black:
        state.black_screen = False
        state.paused = False
    state.last_wallpaper = str(wallpaper)
    state.last_images = images_used
    return SwitchResult(profile.name, wallpaper, images_used, monitors, applied=not dry_run, action=action)


def black_screen(profile_name: str | None = None, *, dry_run: bool = False) -> SwitchResult:
    cfg = load_config()
    profile = cfg.get_profile(profile_name)
    setter = DesktopSetter(dry_run=dry_run)
    wallpaper_path = generated_wallpaper_path(profile.name, suffix="dry-run-black" if dry_run else "black")

    if not dry_run and setter.supports_solid_black(profile.desktop):
        # Put the screen into solid black before doing monitor detection or PNG work.
        # The fallback PNG is generated afterward for status/fallback backends.
        setter.apply_black(None, profile.desktop)
        monitors = detect_monitors()
        wallpaper = compose_black(monitors, wallpaper_path)
    else:
        monitors = detect_monitors()
        wallpaper = compose_black(monitors, wallpaper_path)
        setter.apply_black(wallpaper, profile.desktop)

    if not dry_run:
        with state_transaction() as state:
            state.active_profile = profile.name
            state.black_screen = True
            state.paused = True
            state.last_wallpaper = str(wallpaper)
            state.last_images = []
    return SwitchResult(profile.name, wallpaper, [], monitors, applied=not dry_run, action="black-screen")


def pause() -> RuntimeState:
    with state_transaction() as state:
        state.paused = True
        return RuntimeState.from_dict(state.to_dict())


def save_current_wallpaper(destination: str | Path, *, overwrite: bool = False) -> Path:
    """Copy the current generated wallpaper to a user-selected PNG file."""
    state = load_state()
    if not state.last_wallpaper:
        raise RuntimeError("No current wallpaper is available; run 'next' first")

    source = Path(state.last_wallpaper).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Current wallpaper file is missing: {source}")

    output = Path(destination).expanduser()
    if output.is_dir():
        output = output / source.name
    if output.suffix.lower() != ".png":
        raise ValueError("Saved wallpaper destination must use a .png extension")

    output.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == output.resolve():
        raise ValueError("Saved wallpaper destination must differ from the current cache file")
    if overwrite:
        shutil.copyfile(source, output)
    else:
        try:
            with source.open("rb") as source_file, output.open("xb") as output_file:
                shutil.copyfileobj(source_file, output_file)
        except FileExistsError as exc:
            raise FileExistsError(f"Destination already exists: {output}") from exc
    return output.resolve()


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
