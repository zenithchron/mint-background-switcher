# Changelog

All notable changes to Mint Background Switcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning for public releases.

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
