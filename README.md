# Mint Background Switcher

Mint Background Switcher is a Linux Mint/Cinnamon wallpaper switcher for multi-monitor desktops. It rotates local image folders, supports one shared image pool or per-monitor folders, and fits each whole image inside its monitor with black bars instead of cropping.

## Features

- Local image folders with recursive scanning.
- Random no-repeat rotation until each pool is exhausted.
- Shared, per-monitor, and spanned wallpaper modes.
- Fractional-scale aware monitor composition for Cinnamon/X11.
- Named profiles for different folder/layout setups.
- Settings editor for profiles, shared folders, and per-monitor folders.
- Optional tray menu for quick actions.
- Safe login autostart that waits for Cinnamon before rotating.
- Black-screen/privacy mode that stays black until resumed.
- Built-in rescue command for disabling startup and resetting Cinnamon wallpaper/session settings from a TTY.

## Change log

### Unreleased

- Enlarged and centered the settings window so the profile/settings panels are visible without manual resizing on normal desktop resolutions.
- Added a minimum settings-window size that adapts down for smaller screens instead of opening with clipped controls.

### 0.1.0

- Initial public release with multi-monitor wallpaper rotation, profiles, per-monitor folders, safe autostart, tray support, black-screen mode, and rescue tooling.

## Requirements

- Linux Mint Cinnamon on X11 is the primary target.
- Python 3.10 or newer.
- Pillow for image composition.
- `xrandr` and `gsettings` for monitor detection and desktop wallpaper application.
- Tkinter for the settings editor.
- GTK/AppIndicator bindings for optional tray mode.

On Linux Mint or Ubuntu, install the usual system packages with:

```bash
sudo apt update
sudo apt install -y python3-pil python3-tk python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Install from GitHub

```bash
git clone https://github.com/zenithchron/mint-background-switcher.git
cd mint-background-switcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

If you prefer a user install instead of a project virtual environment:

```bash
python3 -m pip install --user -e .
```

## Quick start

From the repository checkout:

```bash
./scripts/mint-background-switcher init --folder ~/Pictures
./scripts/mint-background-switcher settings
./scripts/mint-background-switcher next --dry-run
./scripts/mint-background-switcher next
```

After manual commands work, enable safe login autostart:

```bash
./scripts/mint-background-switcher autostart --enable
```

Safe autostart runs `safe-start`, not the tray. It waits for Cinnamon, verifies monitor/gsettings readiness, logs startup progress, and defers the first wallpaper change.

To run the optional tray manually:

```bash
./scripts/mint-background-switcher tray
```

To use the tray as the login entry instead of safe-start, use the expert option below only after manual tray testing is stable on your desktop:

```bash
./scripts/mint-background-switcher autostart --enable --tray --delay-seconds 90
```

## Common commands

```bash
# Create default config, optionally using a folder for the shared pool
mint-background-switcher init --folder ~/Pictures

# Generate and apply one rotation now
mint-background-switcher next

# Generate but do not change the desktop
mint-background-switcher next --dry-run

# Turn every monitor black and stay black
mint-background-switcher black-screen

# Resume scheduled rotation and immediately show a new wallpaper
mint-background-switcher resume

# Run the background loop without tray UI
mint-background-switcher run

# Guarded login startup check: waits for Cinnamon readiness but exits without rotating
mint-background-switcher safe-start --check-only

# Launch optional tray icon manually
mint-background-switcher tray

# Open the settings editor
mint-background-switcher settings

# Enable safe login autostart
mint-background-switcher autostart --enable

# Disable all known Mint Background Switcher autostart entries
mint-background-switcher autostart --disable

# Emergency recovery from a TTY if Cinnamon boots without panel/menu
mint-background-switcher rescue --full --reboot

# Register a Cinnamon custom hotkey for black-screen mode
mint-background-switcher register-hotkey --binding '<Primary><Alt>b'
```

## Configuration paths

- Config and profiles: `~/.config/mint-background-switcher/config.json`
- Runtime state: `~/.config/mint-background-switcher/state.json`
- Startup guard: `~/.config/mint-background-switcher/startup-guard.json`
- Generated wallpapers and startup log: `~/.cache/mint-background-switcher/`
- Autostart entry: `~/.config/autostart/mint-background-switcher.desktop`

For tests or experimentation, override paths with:

```bash
export MBS_CONFIG_DIR=/tmp/mbs-config
export MBS_CACHE_DIR=/tmp/mbs-cache
```

## Profile modes

Each profile has a mode:

- `shared`: all monitors draw from one shared image pool, without duplicates within the same rotation when possible.
- `per-monitor`: each monitor uses its own folder list. If a monitor has no explicit folders, it falls back to the shared folders.
- `span`: one image is fit with black bars across the full virtual desktop canvas.

All modes keep the full image visible. The app never uses a fill/crop resize path for wallpaper generation. If Cinnamon monitor scale is set to 75%, 125%, 150%, 175%, or 200%, monitor detection composes wallpapers at the physical panel resolution instead of the scaled logical desktop size.

## Monitor names

Monitor names come from `xrandr`, for example `DP-1`, `HDMI-1`, or `eDP-1`. Open settings after connecting monitors to see current names. In settings, use **Add per-monitor folder...** to browse to a folder first, then choose the screen in the dialog. Use **Remove per-monitor folder...** to delete an assignment.

For tests, you can provide virtual monitor geometry:

```bash
MBS_TEST_MONITORS='Left:1920x1080+0+0,Middle:2560x1440+1920+0,Right:1920x1080+4480+0' \
  mint-background-switcher next --dry-run
```

Add `@150%`, `@1.25`, etc. when you want the test geometry to simulate Cinnamon monitor scale.

## Switching behavior

Live wallpaper changes are rendered to an off-screen active file first, then applied by switching the desktop URI. The app alternates between two active files so the image currently displayed by Cinnamon/GNOME is not overwritten in place. Normal Cinnamon wallpaper changes only update the desktop background URI/options; they do not modify Muffin/Nemo transition or panel settings automatically.

Black-screen mode uses Cinnamon/GNOME solid-black color mode before doing monitor detection or fallback PNG work, so the visible switch should be near-instant. If a configured image folder is empty or temporarily unavailable, normal rotation applies a non-sticky black fallback instead of erroring, then retries on the next rotation.

## Safe login startup and recovery

`autostart --enable` writes a guarded `safe-start` desktop entry. Safe-start waits before doing readiness checks, confirms Cinnamon/gsettings/monitor detection are sane, writes progress to `~/.cache/mint-background-switcher/startup.log`, and marks startup state in `~/.config/mint-background-switcher/startup-guard.json`.

If a previous startup never reached the ready phase, the next safe-start disables autostart and exits instead of trying again at boot.

If Cinnamon ever comes up without panel/menu, switch to a TTY with `Ctrl+Alt+F3`, log in, go to the repository checkout, and run:

```bash
./scripts/mint-background-switcher rescue --full --reboot
```

`rescue --light` only disables Mint Background Switcher and resets wallpaper. `rescue --full` also backs up and resets Cinnamon/Nemo dconf settings and `monitors.xml`, which is more disruptive but is the recovery path for an icons-only desktop failure.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Before submitting changes, run:

```bash
git diff --check
python -m pytest -q
```

## License

Mint Background Switcher is released under the MIT License. See [LICENSE](LICENSE).
