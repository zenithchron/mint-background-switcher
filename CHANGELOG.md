# Changelog

All notable changes to Mint Background Switcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning for public releases.

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
