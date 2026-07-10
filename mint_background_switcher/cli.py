"""Command line interface."""

from __future__ import annotations

import argparse
import json

from . import __version__
from .autostart import disable_autostart, enable_autostart, tray_command
from .config import ensure_config, load_config
from .hotkeys import register_cinnamon_black_hotkey
from .monitor import detect_monitors
from .paths import config_file, state_file, startup_guard_file, startup_log_file
from .rescue import run_rescue
from .service import black_screen, pause, resume, run_loop, save_current_wallpaper, switch_once
from .startup import safe_start
from .state import load_state


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mint-background-switcher")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create default config")
    init.add_argument("--folder", help="Add a folder to the default shared image pool")

    nextp = sub.add_parser("next", help="Generate/apply next wallpaper")
    nextp.add_argument("--profile")
    nextp.add_argument("--dry-run", action="store_true")

    black = sub.add_parser("black-screen", help="Set all monitors black and pause rotation")
    black.add_argument("--profile")
    black.add_argument("--dry-run", action="store_true")

    sub.add_parser("pause", help="Pause rotation")
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

    hotkey = sub.add_parser("register-hotkey", help="Register Cinnamon black-screen hotkey")
    hotkey.add_argument("--binding", default=None)
    hotkey.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Print config/state/monitors")
    sub.add_parser("profiles", help="List profiles")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        path = ensure_config(args.folder)
        print(path)
        return 0
    if args.command == "next":
        _print_result(switch_once(args.profile, dry_run=args.dry_run))
        return 0
    if args.command == "black-screen":
        _print_result(black_screen(args.profile, dry_run=args.dry_run))
        return 0
    if args.command == "pause":
        state = pause()
        print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "resume":
        _print_result(resume(args.profile, dry_run=args.dry_run))
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
        commands = register_cinnamon_black_hotkey(binding=args.binding, dry_run=args.dry_run)
        if args.dry_run:
            for cmd in commands:
                print(" ".join(cmd))
        else:
            print("registered")
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
    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
