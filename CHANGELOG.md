# Changelog

All notable changes to Mint Background Switcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning for public releases.

## [0.1.2] - 2026-07-10

### Added

- `save-current` command for copying the current generated multi-monitor background to a PNG file without advancing the rotation.

### Changed

- Bumped the package version to `0.1.2`.

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
