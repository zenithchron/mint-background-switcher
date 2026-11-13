"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .availability import CollectionUnavailableError
from .autostart import disable_autostart, enable_autostart, tray_command
from .config import ensure_config, load_config
from .config_io import ConfigImportError, export_config, export_document, import_settings, load_export
from .hotkeys import HOTKEY_ACTIONS, register_all_cinnamon_hotkeys, register_cinnamon_hotkey
from .monitor import detect_monitors
from .overlays import DEFAULT_OVERLAY_CALENDAR_POSITION, overlays_enabled, read_picture_info, render_overlay_preview
from .paths import config_file, state_file, startup_guard_file, startup_log_file
from .rescue import run_rescue
from .service import (
    NoPreviousWallpaperError,
    add_web_source,
    black_screen,
    list_web_sources,
    pause,
    previous_wallpaper,
    refresh_web_sources_now,
    remove_web_source,
    resume,
    run_loop,
    save_current_wallpaper,
    switch_once,
    toggle_pause,
)
from .startup import safe_start
from .state import load_state
from .working_storage import WorkingDirectoryError


def _monitor_to_dict(monitor) -> dict:
    return {
        "name": monitor.name,
        "width": monitor.width,
        "height": monitor.height,
        "x": monitor.x,
        "y": monitor.y,
        "primary": monitor.primary,
        "scale": monitor.scale,
        "logical_width": monitor.logical_width,
        "logical_height": monitor.logical_height,
        "logical_x": monitor.logical_x,
        "logical_y": monitor.logical_y,
    }


def _print_result(result) -> None:
    print(f"action={result.action}")
    print(f"profile={result.profile}")
    print(f"wallpaper={result.wallpaper}")
    print(f"monitors={len(result.monitors)}")
    if result.images:
        print("images:")
        for image in result.images:
            print(f"  {image}")
    print(f"applied={result.applied}")
    if result.lockscreen_note:
        print(f"lock_screen={result.lockscreen_note}")
    if result.overlay_note:
        print(f"overlays={result.overlay_note}")
    if result.web_sources:
        print("web_sources:")
        for status in result.web_sources:
            line = f"  {status['status']}: {status['url']}"
            if status.get("path"):
                line += f" -> {status['path']}"
            if status.get("detail"):
                line += f" ({status['detail']})"
            print(line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mint-background-switcher")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create default config")
    init.add_argument("--folder", help="Add a folder to the default shared image pool")

    nextp = sub.add_parser("next", help="Generate/apply next wallpaper")
    nextp.add_argument("--profile")
    nextp.add_argument("--dry-run", action="store_true")

    previous = sub.add_parser("previous", help="Restore the previously applied wallpaper")
    previous.add_argument("--profile")
    previous.add_argument("--dry-run", action="store_true")

    black = sub.add_parser("black-screen", help="Set all monitors black and pause rotation")
    black.add_argument("--profile")
    black.add_argument("--dry-run", action="store_true")

    sub.add_parser("pause", help="Pause rotation")
    sub.add_parser("pause-toggle", help="Toggle rotation pause/resume without switching pictures")
    resume_p = sub.add_parser("resume", help="Resume rotation and immediately advance")
    resume_p.add_argument("--profile")
    resume_p.add_argument("--dry-run", action="store_true")

    save_current = sub.add_parser("save-current", help="Save a copy of the current generated background")
    save_current.add_argument("destination", help="Output PNG file path")
    save_current.add_argument("--force", action="store_true", help="Overwrite an existing output file")

    run = sub.add_parser("run", help="Run background loop without tray")
    run.add_argument("--profile")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--defer-first", action="store_true", help="Wait before the first wallpaper change")
    run.add_argument("--first-delay-seconds", type=float, default=0.0, help="Minimum delay used with --defer-first")

    safe = sub.add_parser("safe-start", help="Guarded login startup: wait for Cinnamon, then run without tray")
    safe.add_argument("--profile")
    safe.add_argument("--dry-run", action="store_true")
    safe.add_argument("--check-only", action="store_true", help="Run startup checks and exit without starting the loop")
    safe.add_argument("--delay-seconds", type=float, default=None, help="Initial login delay before readiness checks")
    safe.add_argument("--ready-timeout-seconds", type=float, default=None, help="Maximum time to wait for Cinnamon readiness")

    sub.add_parser("settings", help="Open settings editor")
    sub.add_parser("tray", help="Run optional tray icon manually")

    autostart = sub.add_parser("autostart", help="Enable/disable safe start at login")
    autostart.add_argument("--enable", action="store_true")
    autostart.add_argument("--disable", action="store_true")
    autostart.add_argument("--tray", action="store_true", help="Expert/legacy: autostart tray directly instead of safe-start")
    autostart.add_argument("--delay-seconds", type=int, default=20, help="Desktop-entry autostart delay before safe-start is invoked")

    rescue = sub.add_parser("rescue", help="Disable MBS and reset Cinnamon wallpaper/session settings")
    rescue_mode = rescue.add_mutually_exclusive_group()
    rescue_mode.add_argument("--light", action="store_true", help="Disable MBS and reset wallpaper only")
    rescue_mode.add_argument("--full", action="store_true", help="Also reset Cinnamon/Nemo dconf and monitors.xml")
    rescue.add_argument("--reboot", action="store_true")

    hotkey = sub.add_parser(
        "register-hotkey",
        help="Register Cinnamon hotkeys (Next, Previous, Pause/Resume, Black screen)",
    )
    hotkey.add_argument(
        "--action",
        choices=sorted(HOTKEY_ACTIONS),
        default="black-screen",
        help="Which hotkey to register (default: black-screen, the historic behavior)",
    )
    hotkey.add_argument("--all", action="store_true", help="Register all four hotkeys using the saved profile bindings")
    hotkey.add_argument("--binding", default=None)
    hotkey.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Print config/state/monitors")
    sub.add_parser("profiles", help="List profiles")

    export = sub.add_parser(
        "export",
        help="Export the full settings (all profiles) to a JSON file or stdout",
    )
    export.add_argument(
        "destination",
        nargs="?",
        default=None,
        help="Output file; omit to print the export document to stdout",
    )

    importp = sub.add_parser(
        "import",
        help="Replace the settings with a previous export (every profile and setting is replaced)",
    )
    importp.add_argument("source", help="Settings export file (or a saved config.json copy) to import")
    importp.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file and report what would be imported without changing anything",
    )

    web_source = sub.add_parser(
        "web-source",
        help="Manage web sources (direct image URLs or RSS/Atom feeds) for a profile",
    )
    web_source_sub = web_source.add_subparsers(dest="web_source_command", required=True)
    ws_add = web_source_sub.add_parser(
        "add",
        help="Add a direct image URL (http/https), or an RSS/Atom feed with --feed",
    )
    ws_add.add_argument("url")
    ws_add.add_argument(
        "--feed",
        action="store_true",
        help="Treat the URL as an RSS/Atom feed whose items carry pictures",
    )
    ws_add.add_argument("--profile")
    ws_remove = web_source_sub.add_parser("remove", help="Remove a web source URL from the profile")
    ws_remove.add_argument("url")
    ws_remove.add_argument("--profile")
    ws_list = web_source_sub.add_parser("list", help="List the profile's web sources")
    ws_list.add_argument("--profile")
    ws_refresh = web_source_sub.add_parser("refresh", help="Download/update the profile's web sources now")
    ws_refresh.add_argument("--profile")
    ws_refresh.add_argument("--dry-run", action="store_true", help="Report cache state without downloading")

    overlay_info = sub.add_parser(
        "overlay-info",
        help="Print the picture title, photographer, and date that MBS would show for one image",
    )
    overlay_info.add_argument("image", help="Picture file")

    overlay_preview = sub.add_parser(
        "overlay-preview",
        help="Render a preview image of the picture overlay for one picture",
    )
    overlay_preview.add_argument("image", help="Picture file")
    overlay_preview.add_argument("--out", default=None, help="Output file (default: overlay-preview alongside the picture)")
    overlay_preview.add_argument("--width", type=int, default=1920, help="Preview width in pixels (default: 1920)")
    overlay_preview.add_argument("--height", type=int, default=1080, help="Preview height in pixels (default: 1080)")
    overlay_preview.add_argument(
        "--profile",
        default=None,
        help="Profile whose overlay settings to use (default: active profile; if overlays are disabled, all fields are shown)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        path = ensure_config(args.folder)
        print(path)
        return 0
    if args.command == "next":
        try:
            _print_result(switch_once(args.profile, dry_run=args.dry_run))
        except CollectionUnavailableError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "previous":
        try:
            _print_result(previous_wallpaper(args.profile, dry_run=args.dry_run))
        except NoPreviousWallpaperError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "black-screen":
        _print_result(black_screen(args.profile, dry_run=args.dry_run))
        return 0
    if args.command == "pause":
        state = pause()
        print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "pause-toggle":
        state = toggle_pause()
        print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "resume":
        try:
            _print_result(resume(args.profile, dry_run=args.dry_run))
        except CollectionUnavailableError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "save-current":
        print(save_current_wallpaper(args.destination, overwrite=args.force))
        return 0
    if args.command == "run":
        run_loop(
            args.profile,
            dry_run=args.dry_run,
            defer_first=args.defer_first,
            first_delay_min_seconds=args.first_delay_seconds,
        )
        return 0
    if args.command == "safe-start":
        return safe_start(
            args.profile,
            dry_run=args.dry_run,
            check_only=args.check_only,
            delay_seconds=args.delay_seconds,
            readiness_timeout_seconds=args.ready_timeout_seconds,
        )
    if args.command == "settings":
        try:
            from .settings_ui import main as settings_main
        except ImportError as exc:
            raise RuntimeError("Settings editor requires Tkinter. On Mint/Ubuntu install python3-tk.") from exc

        settings_main()
        return 0
    if args.command == "tray":
        from .tray import main as tray_main
        tray_main()
        return 0
    if args.command == "autostart":
        if args.enable == args.disable:
            parser.error("autostart requires exactly one of --enable or --disable")
        if args.enable:
            command = tray_command() if args.tray else None
            path = enable_autostart(command, delay_seconds=args.delay_seconds)
            print(path)
            print("mode=" + ("tray" if args.tray else "safe-start"))
        else:
            removed = disable_autostart()
            if removed:
                for path in removed:
                    print(path)
            else:
                print("autostart already disabled")
        return 0
    if args.command == "rescue":
        result = run_rescue(full=args.full, reboot=args.reboot)
        print(f"mode={result.mode}")
        print(f"backup={result.backup_dir}")
        for action in result.actions:
            print(action)
        return 0
    if args.command == "register-hotkey":
        if args.all:
            if args.binding is not None:
                parser.error("--binding cannot be combined with --all")
            results = register_all_cinnamon_hotkeys(dry_run=args.dry_run)
            if args.dry_run:
                for key, cmds in results.items():
                    for cmd in cmds:
                        print(f"#{key} " + " ".join(cmd))
            else:
                print("registered next, previous, pause-resume, black-screen")
        else:
            commands = register_cinnamon_hotkey(args.action, binding=args.binding, dry_run=args.dry_run)
            if args.dry_run:
                for cmd in commands:
                    print(" ".join(cmd))
            else:
                print(f"registered {args.action}")
        return 0
    if args.command == "status":
        cfg = load_config()
        state = load_state()
        print(json.dumps({
            "config_file": str(config_file()),
            "state_file": str(state_file()),
            "startup_log_file": str(startup_log_file()),
            "startup_guard_file": str(startup_guard_file()),
            "config": cfg.to_dict(),
            "state": state.to_dict(),
            "monitors": [_monitor_to_dict(m) for m in detect_monitors()],
        }, indent=2, sort_keys=True))
        return 0
    if args.command == "profiles":
        cfg = load_config()
        for name in sorted(cfg.profiles):
            prefix = "*" if name == cfg.active_profile else " "
            print(f"{prefix} {name}")
        return 0
    if args.command == "export":
        cfg = load_config()
        try:
            if args.destination:
                path = export_config(cfg, Path(args.destination))
                print(path)
            else:
                print(json.dumps(export_document(cfg), indent=2, sort_keys=True))
        except (OSError, ValueError) as exc:
            print(f"export failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "import":
        try:
            candidate = load_export(Path(args.source)) if args.dry_run else import_settings(Path(args.source))
        except ConfigImportError as exc:
            print(f"import failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "dry_run": args.dry_run,
            "profile_count": len(candidate.profiles),
            "profiles": sorted(candidate.profiles),
            "active_profile": candidate.active_profile,
            "working_directory": candidate.working_directory,
        }, indent=2, sort_keys=True))
        return 0
    if args.command == "web-source":
        try:
            profile_name = load_config(create=False).get_profile(args.profile).name
            if args.web_source_command == "add":
                sources = add_web_source(args.profile, args.url, feed=args.feed)
            elif args.web_source_command == "remove":
                sources = remove_web_source(args.profile, args.url)
            elif args.web_source_command == "list":
                sources = list_web_sources(args.profile)
            else:
                sources = None
            if sources is not None:
                print(json.dumps({"profile": profile_name, "web_sources": sources}, indent=2, sort_keys=True))
                return 0
            statuses = refresh_web_sources_now(args.profile, dry_run=args.dry_run)
            print(json.dumps({
                "profile": profile_name,
                "dry_run": args.dry_run,
                "web_sources": [status.to_dict() for status in statuses],
            }, indent=2, sort_keys=True))
            return 0
        except (ValueError, WorkingDirectoryError) as exc:
            print(f"web-source failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "overlay-info":
        info = read_picture_info(Path(args.image))
        print(json.dumps({
            "title": info.title,
            "photographer": info.artist,
            "date": info.date_text,
        }, indent=2, sort_keys=True))
        return 0
    if args.command == "overlay-preview":
        try:
            image_path = Path(args.image).expanduser()
            if not image_path.is_file():
                print(f"overlay-preview failed: no such file: {image_path}", file=sys.stderr)
                return 1
            cfg = load_config(create=False)
            profile = cfg.get_profile(args.profile)
            if overlays_enabled(profile):
                show_title = profile.overlay_title
                show_artist = profile.overlay_artist
                show_date = profile.overlay_date
                zones = profile.no_draw_zones
                show_calendar = profile.overlay_calendar
                calendar_position = profile.overlay_calendar_position
            else:
                show_title = show_artist = show_date = True
                zones = []
                show_calendar = True
                calendar_position = DEFAULT_OVERLAY_CALENDAR_POSITION
            out = Path(args.out).expanduser() if args.out else image_path.with_name(f"overlay-preview{image_path.suffix or '.png'}")
            render_overlay_preview(
                image_path,
                out,
                width=args.width,
                height=args.height,
                fit_mode=profile.fit_mode,
                bar_color=profile.bar_color,
                show_title=show_title,
                show_artist=show_artist,
                show_date=show_date,
                zones=zones,
                show_calendar=show_calendar,
                calendar_position=calendar_position,
            )
            print(out)
        except (ValueError, OSError, WorkingDirectoryError) as exc:
            print(f"overlay-preview failed: {exc}", file=sys.stderr)
            return 1
        return 0
    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
