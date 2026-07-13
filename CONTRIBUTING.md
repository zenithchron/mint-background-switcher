# Contributing

Thanks for helping improve Mint Background Switcher.

## Development setup

```bash
git clone https://github.com/zenithchron/mint-background-switcher.git
cd mint-background-switcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

On Linux Mint or Ubuntu, install desktop dependencies when testing settings/tray behavior:

```bash
sudo apt update
sudo apt install -y python3-pil python3-tk python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Before opening a pull request

Run:

```bash
git diff --check
python -m pytest -q
```

For changes that touch desktop startup, wallpaper application, Cinnamon settings, tray behavior, or rescue logic, also test the relevant command with temporary config/cache directories when practical:

```bash
MBS_CONFIG_DIR=/tmp/mbs-config MBS_CACHE_DIR=/tmp/mbs-cache \
  mint-background-switcher next --dry-run
```

## Design constraints

- Never crop wallpapers. Preserve the full source image and use the configured letterbox bars as needed.
- Keep dry-runs side-effect free.
- Avoid touching Cinnamon/Muffin/Nemo settings beyond the wallpaper keys needed for the requested action.
- Treat login autostart as safety-critical: startup should wait for Cinnamon readiness and should not immediately mutate desktop state.
- Keep optional GUI dependencies lazy so core CLI commands work on minimal/headless systems.

## Reporting bugs

Please include:

- Linux Mint/Cinnamon version.
- Python version.
- Monitor layout and scale settings.
- Command run and output.
- Relevant log file, especially `~/.cache/mint-background-switcher/startup.log` for startup issues.
