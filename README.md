# Mint Background Switcher

Mint Background Switcher is a Linux Mint/Cinnamon wallpaper switcher for multi-monitor desktops. It rotates local image folders, supports one shared image pool or per-monitor folders, and fits each whole image inside its monitor with black or automatically color-matched bars instead of cropping.

## Features

- Local image folders with recursive scanning.
- Random no-repeat rotation until each pool is exhausted.
- Shared, same-image, 2x2 montage, postcard, per-monitor, and spanned wallpaper modes.
- Fractional-scale aware monitor composition for Cinnamon/X11.
- Named profiles for different folder/layout setups.
- Settings editor for profiles, folders, wallpaper actions, installed version, and About information.
- User-triggered managed updates from Settings with versioned per-user installs, atomic activation, restart, and rollback.
- Optional tray menu for quick actions.
- Save the current generated multi-monitor background to a PNG file from Settings or the CLI.
- Optional per-profile grayscale, sepia, soft-focus blur, vignette, and three-month calendar wallpaper effects.
- Optional automatic letterbox-bar colors matched to each source image.
- Safe login autostart that waits for Cinnamon before rotating.
- Black-screen/privacy mode that stays black until resumed.
- Built-in rescue command for disabling startup and resetting Cinnamon wallpaper/session settings from a TTY.

## Change log

### 0.1.12 - 2026-07-21

- Added **Check for Updates...** and **Roll Back...** to Settings with responsive background checking and installation status.
- Added versioned per-user managed installations, commit-pinned release downloads, archive validation, atomic activation, stable launchers, and previous-version rollback.
- Preserved existing configuration, runtime state, safe-start/tray autostart mode and delay, and registered black-screen hotkeys across managed updates.
- Added explicit managed-install status and restart guidance; no update is downloaded or installed without confirmation.
- Hardened tag-rewrite, archive-path, and in-progress window-close handling around activation.
- Bumped the package version to `0.1.12`.

### 0.1.11 - 2026-07-21

- Added a local postcard mode that arranges four uncropped photos in angled white frames with pushpins on a corkboard-colored background for each monitor.
- Added **postcard** under **Settings → Profile settings → Mode**; save the profile or choose **Apply Next Now** for success/error feedback.
- Bumped the package version to `0.1.11`.

### 0.1.10 - 2026-07-20

- Added a local 2x2 montage mode that fits four uncropped images independently on each monitor.
- Added **montage** under **Settings → Profile settings → Mode**; save the profile or choose **Apply Next Now** for success/error feedback.
- Bumped the package version to `0.1.10`.

### 0.1.9 - 2026-07-19

- Added an optional three-month calendar overlay showing the previous, current, and next months with today highlighted.
- Added **calendar** under **Settings → Profile settings → Effect**; save the profile or choose **Apply Next Now** for success/error feedback.
- Bumped the package version to `0.1.9`.

### 0.1.8 - 2026-07-18

- Added an optional vignette effect that gently darkens the edges of the complete generated wallpaper.
- Added **vignette** under **Settings → Profile settings → Effect**; save the profile or choose **Apply Next Now** for success/error feedback.
- Bumped the package version to `0.1.8`.

### 0.1.7 - 2026-07-15

- Added an optional soft-focus blur effect for the complete generated wallpaper.
- Added **blur** under **Settings → Profile settings → Effect**; save the profile or choose **Apply Next Now** for success/error feedback.
- Bumped the package version to `0.1.7`.

### 0.1.6 - 2026-07-14

- Added **Save Current Wallpaper...** to Settings so the generated background can be exported without using the CLI.
- Added the installed version directly to the Settings window and title.
- Added an **About** dialog with the installed version, project description, license, and repository URL.
- Bumped the package version to `0.1.6`.

### 0.1.5 - 2026-07-13

- Added an optional automatic letterbox-bar color that uses each source image's average color while preserving the complete image.
- Bumped the package version to `0.1.5`.

### 0.1.4 - 2026-07-12

- Added an optional sepia effect that gives the complete wallpaper a warm, vintage tone in every layout mode.
- Bumped the package version to `0.1.4`.

### 0.1.3 - 2026-07-11

- Added an optional grayscale effect that post-processes the complete wallpaper in every layout mode.
- Bumped the package version to `0.1.3`.

### 0.1.2 - 2026-07-10

- Added `save-current`, which copies the current generated background to a PNG file without changing the wallpaper or advancing the rotation.
- Bumped the package version to `0.1.2`.

### 0.1.1 - 2026-07-09

- Added `same` mode, which picks one image and fits that same image independently on every monitor.
- Added `mint-background-switcher --version` and bumped the package version to `0.1.1`.
- Enlarged and centered the settings window so the profile/settings panels are visible without manual resizing on normal desktop resolutions.
- Added monitor-aware centering so the settings window does not open split across a multi-monitor seam.
- Added a minimum settings-window size that adapts down for 1024x768-class screens instead of opening with clipped controls.

### 0.1.0

- Initial public release with multi-monitor wallpaper rotation, profiles, per-monitor folders, safe autostart, tray support, black-screen mode, and rescue tooling.

## Requirements

- Linux Mint Cinnamon on X11 is the primary target.
- Python 3.10 or newer, including the `venv` module for managed installations.
- Pillow 9.1 or newer for image composition and effects.
- `xrandr` and `gsettings` for monitor detection and desktop wallpaper application.
- Tkinter for the settings editor.
- GTK/AppIndicator bindings for optional tray mode.

On Linux Mint or Ubuntu, install the usual system packages with:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pil python3-tk python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Install from GitHub

```bash
git clone https://github.com/zenithchron/mint-background-switcher.git "$HOME/mint-background-switcher"
cd "$HOME/mint-background-switcher" &&
python3 -m venv --system-site-packages .venv &&
.venv/bin/python -m pip install --upgrade pip &&
.venv/bin/python -m pip install -e ".[dev]" &&
.venv/bin/python -m pytest -q &&
.venv/bin/mint-background-switcher --version &&
.venv/bin/mint-background-switcher settings
```

The checkout and its virtual environment bootstrap the first installation. In Settings, find **Application updates**, choose **Check for Updates...**, and confirm **Set up managed updates**. The app then downloads the current tagged release into its versioned per-user installation and offers to restart Settings from the stable managed launcher. No `sudo` is used, and the source checkout is left intact as a manual recovery path.

## Quick start

From the repository checkout:

```bash
./scripts/mint-background-switcher init --folder ~/Pictures
./scripts/mint-background-switcher settings
./scripts/mint-background-switcher next --dry-run
./scripts/mint-background-switcher next
```

The Settings window exposes user-facing wallpaper controls, including the **postcard** and **montage** modes, profile effects such as the three-month **calendar**, **Apply Next Now**, **Black Screen**, and **Save Current Wallpaper...**. Its footer shows the installed version; choose **About** for the version, project details, license, and repository URL. The **Application updates** row shows whether managed updates are active or ready after restart and provides **Check for Updates...** and **Roll Back...**.

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

## Managed updates and rollback

Managed updates are strictly user-triggered. Settings does not check, download, or install releases in the background. Choose **Check for Updates...**; if a newer stable release exists, Settings shows both versions and asks before downloading. A network or validation failure is reported as an error and is never presented as “up to date.”

If the running copy came from a checkout, editable install, or another unmanaged location and is already current, the same button offers to install a managed copy. Managed files live at:

- Versioned installations: `~/.local/share/mint-background-switcher/versions/`
- Atomic active-version link: `~/.local/share/mint-background-switcher/current`
- Stable user command: `~/.local/bin/mint-background-switcher`

An existing file or link at the stable user-command path is renamed to a timestamped `mint-background-switcher.pre-managed-*` backup before the managed launcher is created. System-wide or package-manager-owned files are not modified.

The updater resolves the latest `vMAJOR.MINOR.PATCH` tag through GitHub, pins the download to that tag's commit, accepts source downloads only from GitHub/codeload over HTTPS, limits response sizes, rejects unsafe tar members, checks the package and runtime version, records the archive SHA-256 digest, and rechecks that the tag still names the same commit before activation. A candidate gets its receipt only after its venv, command, Tk/Pillow runtime, and any preserved tray runtime pass validation. The active `current` link changes atomically only after all those checks succeed.

Creating the candidate venv invokes `pip`. If required packages are not already cached or available from system site packages, pip may contact your configured Python package index for build requirements and dependencies such as setuptools, wheel, Pillow, and Python 3.10's tomli. See [SECURITY.md](SECURITY.md) for the complete network and trust boundary.

Profiles, runtime state, generated wallpapers, and other user data remain under `~/.config` and `~/.cache`, outside the managed installation. Existing safe-start/tray autostart mode and delay are rewritten to the stable launcher. A registered Mint Background Switcher black-screen hotkey is rebound to the same stable launcher. The currently running tray process keeps running its old code until it is restarted or the next login.

After two managed versions have been installed, **Roll Back...** activates the previous valid managed version without using the network and retains the newer version. During the first migration there is no previous managed version to roll back to, so the original source checkout is intentionally left untouched as the recovery path. Restarting Settings warns before discarding unsaved profile edits.

If Settings cannot be opened from a desktop shortcut, try the stable command directly:

```bash
$HOME/.local/bin/mint-background-switcher settings
```

A versioned launcher can also be run directly from its directory under `~/.local/share/mint-background-switcher/versions/`. See [SECURITY.md](SECURITY.md) for the updater's trust boundary.

## Common commands

```bash
# Create default config, optionally using a folder for the shared pool
mint-background-switcher init --folder ~/Pictures

# Show installed version
mint-background-switcher --version

# Generate and apply one rotation now
mint-background-switcher next

# Generate but do not change the desktop
mint-background-switcher next --dry-run

# Turn every monitor black and stay black
mint-background-switcher black-screen

# Resume scheduled rotation and immediately show a new wallpaper
mint-background-switcher resume

# Atomically save the current generated multi-monitor background (requires a .png file path)
mint-background-switcher save-current ~/Pictures/current-background.png

# Explicitly replace an existing regular-file copy; symbolic-link destinations are rejected
mint-background-switcher save-current ~/Pictures/current-background.png --force

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
- Managed versions and active-version link: `~/.local/share/mint-background-switcher/`
- Stable managed launcher: `~/.local/bin/mint-background-switcher`
- Autostart entry: `~/.config/autostart/mint-background-switcher.desktop`

For tests or experimentation, override paths with:

```bash
export MBS_CONFIG_DIR=/tmp/mbs-config
export MBS_CACHE_DIR=/tmp/mbs-cache
export MBS_INSTALL_ROOT=/tmp/mbs-managed
export MBS_USER_BIN_DIR=/tmp/mbs-bin
```

## Profile modes

Each profile has a mode:

- `shared`: all monitors draw from one shared image pool, without duplicates within the same rotation when possible.
- `same`: one image is picked from the shared image pool and fitted independently on every monitor.
- `montage`: four images from the shared pool are arranged in a 2x2 grid on each monitor, with every complete image fitted inside its tile instead of cropped.
- `postcard`: four images from the shared pool are fitted without cropping, placed in angled white frames with pushpins, and arranged on a corkboard-colored background independently for each monitor.
- `per-monitor`: each monitor uses its own folder list. If a monitor has no explicit folders, it falls back to the shared folders.
- `span`: one image is fit with configured letterbox bars across the full virtual desktop canvas.

All modes keep the full image visible. The app never uses a fill/crop resize path for wallpaper generation. Letterbox bars are black by default; choose `auto` in the settings editor to match each panel's bars to the average color of its source image. In `span` mode, the single source image determines the color for the full canvas. If Cinnamon monitor scale is set to 75%, 125%, 150%, 175%, or 200%, monitor detection composes wallpapers at the physical panel resolution instead of the scaled logical desktop size.

Each profile can optionally apply a `grayscale`, warm vintage-style `sepia`, soft-focus `blur`, edge-darkening `vignette`, or three-month `calendar` effect after composing the complete multi-monitor wallpaper. The calendar shows the previous, current, and next months near the bottom of the wallpaper and highlights today. Choose the effect under **Settings → Profile settings → Effect**, save the profile, then use **Apply Next Now** (or run `next`) to preview the result on the desktop. The default `none` setting leaves image colors unchanged.

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

`save-current` copies that generated PNG, including the complete multi-monitor composition, without selecting new source images or changing runtime state. In Settings, choose **Save Current Wallpaper...** and select a PNG destination; Settings asks before replacing an existing file. From the CLI, the destination must end in `.png` and existing files are protected unless `--force` is supplied.

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

## Versioning

Releases use semantic version numbers. The package version lives in `pyproject.toml` and `mint_background_switcher/__init__.py`, and public releases are tagged as `vMAJOR.MINOR.PATCH`.

## License

Mint Background Switcher is released under the MIT License. See [LICENSE](LICENSE).
