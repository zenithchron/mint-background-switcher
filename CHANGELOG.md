# Changelog

All notable changes to Mint Background Switcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning for public releases.

## [0.1.21] - 2026-07-28

### Added

- **Open Containing Folder** under **Settings → View Current Pictures...**, inspired by John’s Background Switcher, for opening the selected current source's resolved parent in the desktop file manager.
- Responsive background launching plus visible success, missing-source, unavailable-opener, and nonzero launch-error feedback in the Current Pictures window.
- Fixed-argument opener tests and Xvfb-backed Settings coverage for button visibility, selected-source behavior, success, and errors.

### Changed

- Bumped the package version to `0.1.21`.

### Security

- Settings revalidates the selected source as an existing regular file immediately before opening its folder and invokes `xdg-open` with a fixed argument vector and no shell.

## [0.1.20] - 2026-07-27

### Added

- A tabbed Settings layout with General, one tab for every wallpaper mode, and About & Updates; the active mode remains an explicit General setting.
- Per-profile Polaroid controls for 1–20 photos per screen and a continuous Small-to-Large size slider, with existing profiles defaulting to four medium prints.

### Changed

- Polaroid prints now preserve each source image's native aspect ratio without inserted letterbox bars, fit the white frame snugly to the photo, and randomize fully visible coordinates, tilt, overlap, and stacking order for every render.
- Shared image-source folders now live under General, per-monitor assignments live under Per-monitor, and update/rollback controls live under About & Updates.
- Bumped the package version to `0.1.20`.

## [0.1.19] - 2026-07-27

### Fixed

- Managed updates now restart active tray, safe-start, or background-loop processes through the newly activated launcher so scheduled rotations immediately recognize newly added wallpaper modes.

### Changed

- Bumped the package version to `0.1.19`.

## [0.1.18] - 2026-07-27

### Added

- A local `collage` mode inspired by John’s Background Switcher, arranging five uncropped photos per monitor in a deterministic asymmetric mosaic.
- **collage** under **Settings → Profile settings → Mode**, with Save, **Apply Next Now** success/error, and explicit safe-black-fallback feedback.
- Deterministic composition, source-edge preservation, bounded malformed/oversized-image fallback, dry-run/source/state safety, no-repeat selection, black-screen non-regression, and Xvfb-backed Settings/About coverage.

### Changed

- Bumped the package version to `0.1.18`.

## [0.1.17] - 2026-07-26

### Added

- A local `polaroid` mode inspired by John’s Background Switcher, arranging four uncropped photos per monitor as individually tilted, bottom-heavy white prints on a dark background.
- **polaroid** under **Settings → Profile settings → Mode**, with Save, **Apply Next Now** success/error, and explicit safe-black-fallback feedback.
- Deterministic composition, source-edge preservation, malformed-image fallback, dry-run/source/state safety, no-repeat selection, black-screen non-regression, and Xvfb-backed Settings/About coverage.

### Changed

- Bumped the package version to `0.1.17`.

## [0.1.16] - 2026-07-25

### Added

- **View Current Pictures...** in Settings, inspired by John’s Background Switcher, for listing every unique original image used in the current wallpaper and opening a selected source in the default desktop application.
- Clear no-picture, successful-launch, missing-file, unavailable-opener, and nonzero launch-error feedback without changing the wallpaper, rotation state, or source files; an open dialog refreshes when revisited and revalidates the current sources before launching one.
- Read-only source-list service coverage plus an Xvfb-backed Settings test for button, dialog, refresh, list, version, asynchronous open-success, and open-error visibility.

### Changed

- Bumped the package version to `0.1.16`.

### Security

- Selected sources must still be regular files, and Settings launches `xdg-open` with a fixed argument vector and no shell.

## [0.1.15] - 2026-07-24

### Added

- An optional half-color desaturation effect inspired by John’s Background Switcher, applied to the complete generated wallpaper in every layout mode.
- **desaturate** under **Settings → Profile settings → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, dry-run/source-safety, black-screen, and Xvfb-backed Settings coverage for the new effect.

### Changed

- Bumped the package version to `0.1.15`.

## [0.1.14] - 2026-07-23

### Added

- An optional inverted-colors effect inspired by John’s Background Switcher, applied to the complete generated wallpaper in every layout mode.
- **invert** under **Settings → Profile settings → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, dry-run/source-safety, black-screen/fallback, and Xvfb-backed Settings coverage for the new effect.

### Changed

- Bumped the package version to `0.1.14`.

## [0.1.13] - 2026-07-22

### Added

- A persistent SQLite image-library index and database-backed no-repeat pools for responsive rotation with tens of thousands of local images.
- **Working files** controls in Settings to browse for, explicitly create, validate, and activate a dedicated folder for generated wallpapers and the image-library index.
- Verified, cancellable working-folder migration that serializes with rotations, revalidates concurrent profile changes, stages managed files, rejects collisions, updates the active wallpaper path, switches configuration only after successful copy, and retains the previous files for recovery.
- Ownership markers and actionable validation for foreign/nonempty folders, source-folder overlap, nested working folders, symbolic-link hazards, unavailable volumes, permissions, and file collisions.

### Changed

- Bumped the package version to `0.1.13`.
- Tray rotations and Settings **Apply Next Now** / **Black Screen** actions now run in non-daemon background workers; repeated tray **Next** requests coalesce and Settings opens in its own process instead of sharing GTK's event loop.
- Image discovery is cached for five minutes between refreshes, expensive scans are transactional and cancellable, no-repeat pools refill near-linearly once per cycle and use bounded draws between refills, and postcard/montage choices are drawn in one batch.
- Pillow validation uses lightweight `verify()` before the single composition decode instead of loading selected postcard images twice.
- Legacy path-heavy no-repeat lists are removed from `state.json`; profiles, runtime state, startup logs, updater installations, autostart entries, hotkeys, and source folders remain in their established locations.
- Rescue now recognizes and backs up a marker-validated custom working folder without touching source-image folders.

### Security

- A configured custom working folder never silently falls back to the default cache when unavailable.
- Working-folder migration copies only recognized generated PNGs and image-index files, verifies SHA-256 content before activation, never overwrites destination files, and never deletes the old files.
- Source-image directories remain read-only inputs; MBS creates no persistent source thumbnails or resized source copies.

## [0.1.12] - 2026-07-21

### Added

- **Check for Updates...** in Settings for user-triggered stable-release checks, current/new version confirmation, first-time managed-install setup, responsive background work, and clear failure feedback.
- **Roll Back...** in Settings when a previous valid managed release exists.
- Explicit Settings status for an active managed version, a managed version awaiting restart, or an unmanaged copy.
- Versioned per-user installations under `~/.local/share/mint-background-switcher/versions/`, an atomic `current` link, and a stable `~/.local/bin/mint-background-switcher` launcher.
- Install receipts containing the release version, commit, timestamp, and downloaded archive SHA-256 digest.

### Changed

- Bumped the package version to `0.1.12`.
- Added `tomli` on Python 3.10 so release metadata validation remains compatible with every supported Python version.
- Managed updates preserve safe-start/tray autostart mode and delay, rebind an existing black-screen hotkey to the stable launcher, and leave profiles, state, cache, source checkouts, and system-package-managed files untouched.
- Settings now warns that restarting into an activated version discards unsaved profile edits and explains that an already-running tray changes version only after restart or next login.
- Settings keeps update workers alive and blocks Close/window-manager shutdown until active check, install, or rollback work finishes.

### Security

- Release checks accept only stable semantic-version tags from the public repository, peel annotated tags to commits, pin archive downloads to the resolved commit, reject rewrites against any retained installation of the same version, and recheck the tag after download and immediately before activation.
- Source downloads require trusted GitHub/codeload HTTPS hosts and bounded response sizes; raw and canonical tar paths, duplicate extraction destinations, member types, expanded size, package name, metadata version, and runtime version are validated before installation. The confirmed pip phase may use the configured Python package index for declared build/runtime dependencies.
- Managed installs use a nonblocking update lock, build directly at an unreferenced permanent version path so venv shebangs remain valid, probe the staged command and runtime, and atomically activate only the `current` link.
- Failed installs and activation failures preserve or restore the working active version, stable launcher, and autostart files. Normal installation rejects downgrades and same-version tag rewrites; intentional downgrades use the explicit rollback path.

## [0.1.11] - 2026-07-21

### Added

- A local postcard mode inspired by John’s Background Switcher, arranging four uncropped photos in angled white frames with pushpins on a corkboard-colored background for each monitor.
- **postcard** under **Settings → Profile settings → Mode**, with Save and **Apply Next Now** success/error feedback.
- An Xvfb-backed Settings test that verifies the postcard control is present, visible, saveable, and immediately applicable in a real Tk window.

### Changed

- Bumped the package version to `0.1.11`.

## [0.1.10] - 2026-07-20

### Added

- A local 2x2 montage mode inspired by John’s Background Switcher, using four fitted, uncropped images per monitor from the profile's shared folders.
- **montage** under **Settings → Profile settings → Mode**, with Save and **Apply Next Now** success/error feedback.
- An Xvfb-backed Settings test that verifies the montage control is present, visible, saveable, and immediately applicable in a real Tk window.

### Changed

- Bumped the package version to `0.1.10`.

## [0.1.9] - 2026-07-19

### Added

- An optional three-month calendar overlay showing the previous, current, and next months with today highlighted, inspired by John’s Background Switcher and available under **Settings → Profile settings → Effect → calendar** with Save and **Apply Next Now** success/error feedback.
- An Xvfb-backed Settings test that verifies the calendar control is present, visible, and saveable in a real Tk window.

### Changed

- Bumped the package version to `0.1.9`.

## [0.1.8] - 2026-07-18

### Added

- An optional vignette effect that gently darkens the edges of the complete generated wallpaper, available under **Settings → Profile settings → Effect → vignette** with Save and **Apply Next Now** success/error feedback.
- An Xvfb-backed Settings test that verifies the vignette control is present and visible in a real Tk window.

### Changed

- Bumped the package version to `0.1.8`.
- Raised the minimum Pillow version to 9.1 to match the image-resampling API used by wallpaper composition and effects.

## [0.1.7] - 2026-07-15

### Added

- An optional soft-focus blur effect for the complete generated wallpaper, available under **Settings → Profile settings → Effect → blur** with the existing Save and **Apply Next Now** feedback.
- An Xvfb-backed Settings test that verifies the blur control is present and visible in a real Tk window.

### Changed

- Bumped the package version to `0.1.7`.

## [0.1.6] - 2026-07-14

### Added

- **Save Current Wallpaper...** in Settings, backed by the same atomic snapshot service as the `save-current` CLI command and explicit confirmation before replacing an existing file.
- A visible installed-version label and versioned Settings window title.
- An **About** dialog with the installed version, project description, MIT license, and repository URL.

### Changed

- Bumped the package version to `0.1.6`.

## [0.1.5] - 2026-07-13

### Added

- Optional automatic letterbox-bar colors derived from each source image's average color, configurable per profile in the settings editor.

### Changed

- Bumped the package version to `0.1.5`.

## [0.1.4] - 2026-07-12

### Added

- Optional sepia post-processing for every wallpaper mode, configurable per profile in the settings editor.

### Changed

- Bumped the package version to `0.1.4`.

## [0.1.3] - 2026-07-11

### Added

- Optional grayscale post-processing for every wallpaper mode, configurable per profile in the settings editor.

### Changed

- Bumped the package version to `0.1.3`.

## [0.1.2] - 2026-07-10

### Added

- `save-current` command for copying the current generated multi-monitor background to a PNG file without advancing the rotation.

### Changed

- Bumped the package version to `0.1.2`.
- `save-current` now requires an explicit `.png` file path, stages a stable snapshot under the shared wallpaper-state lock, installs it atomically without following destination symbolic links, preserves existing file permissions while new files honor the caller's umask, and does not delay the immediate solid-black privacy action.

## [0.1.1] - 2026-07-09

### Added

- `same` wallpaper mode, which picks one shared image and fits it independently on every monitor.
- `mint-background-switcher --version` for reporting the installed package version.

### Changed

- Bumped the package version to `0.1.1`.
- Enlarged and centered the settings window so the profile/settings panels are visible without manual resizing on normal desktop resolutions.
- Added monitor-aware centering so the settings window does not open split across a multi-monitor seam.
- Added a minimum settings-window size that adapts down for 1024x768-class screens instead of opening with clipped controls.

## [0.1.0] - 2026-07-06

### Added

- Local-folder wallpaper rotation for Linux Mint/Cinnamon.
- Shared, per-monitor, and spanned wallpaper modes.
- Fit-with-black-bars composition that preserves the whole source image.
- No-repeat random pools persisted across rotations.
- Fractional-scale-aware monitor detection for common Cinnamon scale factors.
- Tk settings editor with named profiles, profile rename, shared folders, and per-monitor folder assignment/removal.
- Optional AppIndicator tray menu with theme-friendly symbolic icon selection.
- Safe login startup mode with readiness checks, deferred first rotation, startup logging, and stuck-start guard.
- Built-in rescue command for disabling startup and resetting Cinnamon wallpaper/session settings from a TTY.
- Black-screen/privacy mode and optional Cinnamon hotkey registration.
- Automated test suite and GitHub Actions CI.
