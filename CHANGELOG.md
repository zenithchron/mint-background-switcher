# Changelog

All notable changes to Mint Background Switcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning for public releases.

## [0.2.25] - 2026-11-11

### Added

- **Calendar overlay** (JBS OVR-06, the desktop-overlays backlog sub-item that remained future work after v0.2.23) — a small monthly calendar card drawn on top of the composed wallpaper with today's date highlighted in blue:
  - **Settings → Overlays → Picture information**: new **Show calendar (current month, today highlighted)** checkbox plus a **Position** choice (Bottom right — default —, Bottom left, Top right, Top left). The calendar composes independently of the title / photographer / date lines and honors the same per-profile no-draw zones: if the requested corner is obstructed the card moves to the next clear corner, and a panel fully covered by zones is skipped without breaking rotation.
  - Works with the Shared, Same, Per-monitor, and Span layouts (multi-picture layouts never draw overlays, as before), renders at physical panel resolution so the card stays sharp and proportionally sized on fractional-scale displays, and is reported by **Save & Apply Now**, the background loop, and the CLI via the same `overlays` note (e.g. `calendar drawn on 1 panel`).
  - CLI: `mint-background-switcher overlay-preview <image>` now includes the calendar when the profile has it enabled (and always includes it in the no-overlay fallback mode); `--profile` selects which profile's overlay settings apply.
- Bumped the package version to `0.2.25`.

## [0.2.24] - 2026-11-10

### Changed

- **Two-row Settings tab bar** (backlog #9): the nine settings pages now open from two tab rows instead of one cramped row — top row: **Sources, Layout & Appearance, Overlays, Rotation & Shortcuts**; bottom row: **Conditions, Never Show Again, Public Collections, Storage, Updates & About**. Selecting a tab in either row shows its page and highlights that row while the other row dims; Ctrl+Tab / Ctrl+Shift+Tab cycles pages across both rows. Every tab's behavior, underlined accelerator letters, and the Save & Apply Now flow are unchanged. The fixed 944×668 minimum geometry is preserved: page spacing was compacted (shared-sources and current-wallpaper lists, section padding) so every page fits unclipped at the minimum size under both the default and clam themes.
- Bumped the package version to `0.2.24`.

## [0.2.23] - 2026-11-09

### Added

- **Desktop picture overlays** (JBS OVR-01..OVR-05) — optional picture information drawn on top of the composed wallpaper:
  - **Settings → Overlays** (new page, between Layout & Appearance and Rotation & Shortcuts): per-profile toggles for **Show picture title** (EXIF title, falling back to the file name), **Show photographer** (EXIF artist), and **Show picture date** (EXIF date, falling back to the file date), plus a **No-draw zones** editor (up to 8 zones per profile; whole-desktop or per-monitor; coordinates in pixels with Add zone / Remove selected and visible validation feedback).
  - Overlays compose with every single-picture layout — Shared, Same, Per-monitor, and Span — on top of whatever the selected display fit mode produced; multi-picture layouts (Montage, Collage, Postcard, Polaroid) never draw overlays. Panels are rendered at physical panel resolution, so text stays sharp and proportionally sized on fractional-scale (e.g. 125%) displays.
  - **Fail-open by design**: a zone, missing metadata, or any drawing error skips the affected panel only — rotation always succeeds, and the outcome is reported by **Save & Apply Now**, the background loop, and the CLI (`overlays=` line).
  - CLI for automation: `mint-background-switcher overlay-info <image>` (print title/photographer/date as JSON) and `mint-background-switcher overlay-preview <image> [--out FILE] [--width N] [--height N] [--profile NAME]` (render a standalone preview image of the overlay).

### Changed

- The Settings window now has nine task-based pages (Overlays added); the fixed 944×668 minimum geometry is unchanged.
- Bumped the package version to `0.2.23`.

## [0.2.22] - 2026-11-08

### Added

- **Web picture sources** (JBS SRC-03) — the first non-local picture source and the source-plugin architecture it is built on:
  - **Settings → Sources → Web picture sources**: a per-profile list of direct image URLs (`http`/`https`, one image file per URL, up to 20 per profile) with **Add URL**, **Remove Selected**, and **Refresh now** buttons. Every action gives visible success/error feedback, and the list persists with the profile like every other source setting.
  - Configured URLs are downloaded into `<working folder>/web_sources/` (atomic writes, SHA-256-named files, 64 MiB download cap, 30 s timeout, an identifiable user agent) and then join the rotation pool exactly like local folders — every display mode, per-monitor assignment, effects, and the Never Show Again list all work on them.
  - **Fail-open by design**: an unreachable, oversized, or non-image URL is reported for that source only and never blocks rotation; a previously downloaded copy keeps rotating while the URL is offline. Each URL is re-downloaded at most once every 24 hours; **Refresh now** re-downloads immediately. Cache files for removed URLs are pruned so removed sources stop rotating.
  - CLI for automation: `mint-background-switcher web-source add <url> [--profile NAME]`, `web-source remove <url> [--profile NAME]`, `web-source list [--profile NAME]`, and `web-source refresh [--profile NAME] [--dry-run]` (dry runs report cache state without touching the network). `next` and `Save & Apply Now` now include a `web_sources` status section showing each URL's outcome (`refreshed`, `cached`, `stale-kept`, or `failed`).
  - The source interface (per-profile entry list + shared cache directory) is stable, so later releases can add keyless providers (for example public image search) without touching the rotation pipeline, which only ever sees local folders.

### Changed

- Compacted the Sources settings page spacing (shared-sources list now 3 lines instead of 5) to fit the new Web picture sources section inside the fixed 944×668 settings window.
- Bumped the package version to `0.2.22`.

## [0.2.21] - 2026-11-07

### Fixed

- **Profile switch to an unavailable drive no longer freezes the app.** When a profile's picture collection lives on a drive that is not currently available (a dead network mount, a disconnected share), filesystem calls on that path block in the kernel indefinitely with no error, so the first scan after switching to such a profile froze the settings window and the background loop. Every switch now starts with a bounded reachability probe of the profile's collection folders (5 second deadline, run in a short-lived child process that is abandoned — never waited on — if the mount is wedged):
  - **Settings "Save & Apply Now"** — a switch to a profile with an unresponsive collection is rejected with a warning dialog; the activation is rolled back (in memory and on disk) and the previous profile remains active, so MBS keeps operating exactly as before.
  - **Background loop** — a scheduled switch whose collection is unresponsive is skipped with a log line ("keeping the current wallpaper and retrying on the next tick"); the loop keeps running and picks the switch up automatically once the drive is reachable again.
  - **CLI `next` / `resume`** — report a one-line error and a non-zero exit code instead of hanging.
  - A folder that is merely *missing* (a plain local path that was removed) is intentionally **not** rejected: the established black-fallback / per-monitor fallback behavior is unchanged.

### Changed

- Bumped the package version to `0.2.21`.

## [0.2.20] - 2026-11-07

### Added

- **Settings import / export** (JBS CFG-01), inspired by John's Background Switcher's config save/restore:
  - **Settings → Storage → Import / Export** gains **Export Settings...** and **Import Settings...** buttons with an on-page status line and success/error dialogs.
  - Export writes the complete settings — every profile, shared and per-monitor folders, and all per-profile options — as a versioned JSON document. Exporting onto the live `config.json` is refused, and a config file that was overwritten with an export document by mistake is recovered instead of reset to the defaults.
  - Import restores a previous export (or a saved copy of `config.json`) in one step. The file is fully validated before anything is applied, and a confirmation dialog makes explicit that every profile and setting in this installation will be replaced. Cancelling either dialog leaves the current settings untouched.
  - Imported values apply immediately: the settings editor shows the imported profiles right away, and the background loop picks the imported settings up on its next rotation.
- CLI for automation: `mint-background-switcher export [DESTINATION]` writes the export to a file (or prints the document to stdout when no destination is given), and `mint-background-switcher import SOURCE [--dry-run]` validates a file and — without `--dry-run` — replaces the settings. An invalid file fails with a clear message and leaves the settings byte-for-byte unchanged.

### Changed

- Bumped the package version to `0.2.20`.

## [0.2.19] - 2026-11-06

### Added

- **Rebindable global hotkeys** (JBS CTL-15), inspired by John's Background Switcher's customizable shortcuts: the single fixed black-screen hotkey becomes three per-profile Cinnamon custom hotkeys:
  - **Next** (default `<Primary><Alt>n`) — advance to the next picture immediately, from anywhere.
  - **Pause/Resume** (default `<Primary><Alt>p`) — flips the rotation pause state without switching pictures; on resume the loop applies the next rotation on its normal schedule.
  - **Black screen** (default `<Primary><Alt>b`, the historic fixed binding).
- **Settings → Rotation & Shortcuts → Shortcuts** shows all three bindings as editable fields plus a **Register hotkeys** button that registers (or re-registers) all three Cinnamon custom keybindings in one step, with a success dialog listing the active bindings and an error dialog on failure.
- CLI: `register-hotkey` now accepts `--action next|pause-resume|black-screen` (default stays `black-screen`, the historic behavior) and `--all` to register every hotkey from the saved profile bindings at once; both support `--dry-run`, which prints the exact `gsettings` commands without applying them.
- New `pause-toggle` command flips the pause state (and reports the resulting runtime state) for use from a terminal or a registered hotkey.

### Changed

- Existing profiles without the new fields fall back to the default bindings, and saved bindings are validated (non-empty, at most 64 characters, no control characters) with invalid values replaced by the defaults.
- The managed updater now rebinds every registered hotkey — not only the black-screen hotkey — to the stable launcher after an update.
- Bumped the package version to `0.2.19`.

## [0.2.18] - 2026-11-05

### Added

- Per-profile **Never Show Again (exclusion list)** on a new **Settings → Never Show Again** page, inspired by John's Background Switcher's "do not show again" control (JBS CTL-06):
  - **Never Show Again (current wallpaper)** excludes every source picture of the currently applied wallpaper in one click — multi-picture layouts exclude all of their sources at once — using the sources recorded at the last rotation.
  - The page lists the excluded pictures with a live count; entries are removed individually (**Remove Selected**, multi-select) or all at once (**Clear All...**, with confirmation).
  - The **Current Pictures** dialog gains a **Never Show Again** button for selected entries (multi-select) and marks already-excluded sources with an `[excluded]` suffix.
- Exclusions persist per profile in the config file (bounded to 1000 entries of at most 4096 characters each, de-duplicated) and survive saving or renaming a profile.
- Excluded pictures are skipped on every rotation path (dry-run preview, cached library draws, and per-slot orientation matching); the remaining pool rotates as usual and wraps around without ever resurrecting an excluded picture. If every picture of a profile is excluded, the existing safe black fallback applies instead of an empty wallpaper.
- Added unit coverage for config coercion/round-trip and bounds, add/remove/clear persistence, library draw exclusion with cycle wrap, service-level never-rotates / all-excluded black fallback / recorded-source exclusion, and 944×668 Xvfb Settings visibility, exclude, remove, clear, and save-preservation tests for the new page and dialog.

### Changed

- The Settings window now has eight task-based pages (Never Show Again sits between Conditions and Public Collections); the fixed 944×668 minimum geometry is unchanged and every page still fits it under the default and `clam` themes.
- Bumped the package version to `0.2.18`.

## [0.2.17] - 2026-11-03

### Added

- Per-profile **run conditions** on a new **Settings → Conditions** page, inspired by John's Background Switcher's switching conditions (SW-07..SW-11): each of the five conditions is an independent toggle that pauses *scheduled* background switching while it holds:
  - **Pause scheduled switching while a named process is running** — watch for a process by exact name (Linux process names are limited to 15 characters; longer names are rejected on save).
  - **Pause scheduled switching while running on battery** — laptops only; desktops without a battery are unaffected.
  - **Pause scheduled switching while a remote (VNC) session is active** — detects common VNC/remote-desktop server processes (`x11vnc`, `vncserver`, TigerVNC, TurboVNC, KasmVNC, ...).
  - **Only switch when the session has been idle** — require N seconds of idle time (via `xprintidle`) before a due switch.
  - **Pause scheduled switching while the session is locked or the screensaver is active** — probed through the desktop's screensaver/locker D-Bus service (Cinnamon, GNOME, LightDM).
- Conditions pause the background loop only: **Save & Apply Now**, `mint-background-switcher next`, and resuming from a black screen always apply, and the dry-run preview ignores conditions. While a condition holds the loop retries on a short cadence (at most 60 s), so a clearing condition resumes the schedule without waiting a full interval; the rotate-at-startup skip is not consumed while suppressed, matching the existing pause/black-screen handling. A night-window resume is deferred the same way.
- Every probe fails open: a condition that cannot be detected (no battery, no `xprintidle`, no reachable locker service) never blocks switching.
- The Settings window validates the new controls on save (empty process name while the toggle is on, more than 15 characters, non-numeric or out-of-range idle seconds are rejected with a message box), and the value fields are greyed out while their toggle is off.
- Added unit coverage for every probe and the fail-open rules, config round-trip and coercion, `run_loop` suppression/resume/skip-first/dry-run/night-exit behavior, and 944×668 Xvfb Settings visibility, save, reject, and reload tests for the new Conditions page.

### Changed

- The Settings window now has seven task-based pages (Conditions sits between Rotation & Shortcuts and Public Collections); the fixed 944×668 minimum geometry is unchanged and every page still fits it under the default and `clam` themes.
- Bumped the package version to `0.2.17`.

## [0.2.16] - 2026-11-02

### Added

- Per-profile **Mirror wallpaper to the lock screen** toggle under **Settings → Rotation & Shortcuts → Desktop integration**, inspired by John's Background Switcher's lock/logon-screen overlay: when enabled, the generated wallpaper is also written to the session lock screen on every rotation.
- **GNOME** exposes a per-user lock-screen image (`org.gnome.desktop.screensaver`), so the same generated wallpaper is written there explicitly on each rotation, including the black screen, so the lock screen never shows a stale picture. **Cinnamon** shows the desktop wallpaper on its lock screen by itself, so enabling the toggle there needs no extra write and reports that the lock screen already matches. Other desktops (Mate, XFCE, ...) do not expose a per-user lock-screen image setting; the toggle reports that the lock screen keeps its own image.
- A failed lock-screen write never breaks the desktop wallpaper path: the rotation still completes, and the result carries a short note that **Save & Apply Now**, `mint-background-switcher next`, and the background loop report.
- Added unit coverage for the per-desktop mirror behavior (GNOME schema writes, Cinnamon no-op, unsupported desktops, dry runs, and failure reporting), service-level propagation for rotations, black-screen, and empty-folder fallbacks, config round-trip and coercion, and 944×668 Xvfb Settings visibility plus save/reload tests for the new control.

## [0.2.15] - 2026-11-01

### Added

- Per-profile **Display fit mode** under **Settings → Layout & Appearance → Appearance**, inspired by John's Background Switcher's display modes: choose **Fit with bars**, **Center (border color)**, **Scale to fit**, **Stretch**, **Scale and crop (overscale)**, or **Scale and blur edges**. The mode applies to every fitted panel in Shared, Same, Per-monitor, and Span layouts and to each cell of Montage and Collage layouts.
- **Fit with bars** (the default) keeps the historical behavior exactly: the picture is scaled down only, the whole picture stays visible, and unused space uses the chosen letterbox bar style. **Center** places the unscaled picture on the bar-color background and shows the central region of oversized pictures. **Scale to fit** enlarges small pictures so one edge touches the panel, unlike the bar modes that keep them at native size. **Stretch** fills the panel exactly, distorting the aspect ratio when necessary. **Scale and crop (overscale)** scales to fully cover the panel and center-crops the overflow with no bars and no distortion. **Scale and blur edges** fills unused space with a heavily blurred copy of the picture, like the existing blurred letterbox bar as a first-class mode.
- The **Letterbox bars** control (black, auto, blurred) still chooses the bar style for the bar-based modes; Stretch and Scale and crop ignore it because they leave no unused space.
- Added unit coverage for all six fit modes (pixel-level geometry, distortion checks, bar-style interaction, one-pixel edge cases, and historical byte-identity of the default), config round-trip and coercion, service-level mode propagation to every composer, and 944×668 Xvfb Settings visibility plus save/reload tests for the new control.

### Changed

- Bumped the package version to `0.2.15`.

## [0.2.14] - 2026-10-31

### Added

- Per-profile **Image types** filter under **Settings → Sources → Folder scanning**, inspired by John's Background Switcher's file-type selection: enter comma-separated image types (for example `jpg, png, webp`; a leading dot is accepted and case is ignored) to keep rotation limited to those picture formats. The option is empty by default, which keeps every supported type in rotation, so existing profiles behave exactly as before.
- The filter is part of the scan signature, so changing it refreshes the library index exactly once; it applies to shared, per-monitor, and individually selected pictures, to recursive and flat scans, and to dry-run previews as well as live rotations.
- Settings validates the list on save: unknown types (anything outside `jpg, jpeg, png, webp, bmp, gif, tif, tiff`) are rejected with a message box that names the supported types, and duplicate entries collapse to one.
- Added unit coverage for type normalization and scan filtering (recursive, flat, and explicit-picture roots), config round-trip and coercion, scan-signature stability, and 944×668 Xvfb Settings visibility plus save/reject tests for the new control.

### Changed

- Bumped the package version to `0.2.14`.

## [0.2.13] - 2026-10-30

### Added

- Per-profile **night schedule** under **Settings → Rotation & Shortcuts → Rotation**, inspired by John's Background Switcher's time-of-day switching: enable "Keep the desktop black during a nightly window", pick a start and end time (zero-padded `HH:MM`, for example `22:00` to `06:00`), and the background loop turns every monitor black when the window opens and restores rotation by itself when it ends. Windows may cross midnight, the start minute is included, and the end minute is not.
- Scheduled black screens are tracked separately from the manual black screen: when the night window ends the app resumes on its own, while a manually triggered black screen stays sticky until you resume it (hotkey, `mint-background-switcher resume`, or **Save & Apply Now**).
- The Settings window validates night-window times on save (zero-padded `HH:MM` only, start and end must differ) and reports errors with a message box; the time fields are greyed out while the schedule is off and default to `22:00`–`06:00` for new profiles.
- Dry runs never trigger the scheduled black screen or its automatic resume.
- Added unit coverage for the window math, config round-trip and coercion, the per-tick schedule decision, the `run_loop` enter/hold/resume cycle, manual-black-screen immunity, and 944×668 Xvfb Settings visibility and save/reject tests for the new controls.

### Changed

- Bumped the package version to `0.2.13`.

## [0.2.12] - 2026-10-29

### Added

- Per-profile **Rotate at startup** option under **Settings → Rotation & Shortcuts → Rotation**, inspired by John's Background Switcher's switch-at-startup option: when unchecked, the safe login start-up keeps the current background instead of rotating right after Cinnamon becomes ready, and the normal interval takes over from there. The option is on by default, so existing profiles behave exactly as before.
- Black-screen and pause cycles never consume the skipped first rotation: resuming from privacy mode or an earlier pause still switches on the next cycle, and manual commands (`next`, `resume`, `Save & Apply Now`) are unaffected by the option.
- Added config round-trip, loop-skip, safe-start wiring, and 944×668 Xvfb Settings coverage for the new control.

### Changed

- Bumped the package version to `0.2.12`.

## [0.2.11] - 2026-10-28

### Added

- Per-profile **Show photo captions** options for the Postcard and Polaroid layouts, inspired by John's Background Switcher's captions-on-postcards feature: Postcard photos display their file name (without extension) inside the bottom of the picture, and Polaroid prints display their file name on the bottom border of the frame. Both options default to off, so existing layouts are unchanged.
- Caption text scales to the photo width, very long file names are shortened with an ellipsis, and the text is drawn with a soft outline for readability over any picture. Captions never change placement, stacking, tilt, or the random rotation sequence.
- Exposed both options as checkbuttons under **Settings → Layout & Appearance** next to the existing Postcard and Polaroid tilt controls, with the existing Save Profile success/error feedback.

### Changed

- Bumped the package version to `0.2.11`.

## [0.2.10] - 2026-10-27

### Added

- Per-profile **Match monitor orientation** option inspired by John’s Background Switcher’s monitor-orientation matching: when enabled, single-picture layouts prefer landscape pictures on landscape monitors and portrait pictures on portrait monitors, with the option off by default.
- Exposed it under **Settings → Sources → Folder scanning** next to the other scanning filters, with the existing Save Profile success/error feedback.
- Orientation preferences apply to the Shared, Same, Span, and Per-monitor layouts, to dry-run previews, and to live rotations; multi-picture layouts (Montage, Collage, Postcard, Polaroid) are intentionally left unfiltered. Square pictures fit any monitor, unreadable headers never block rotation, and a monitor whose pool holds no matching picture falls back to whatever remains so rotation never blocks on shape alone.
- Orientation results are cached in the image-library index with file-change invalidation, so warm rotations resolve them from one small table lookup.

### Changed

- Bumped the package version to `0.2.10`.

## [0.2.9] - 2026-10-26

### Added

- Per-profile **Ignore name patterns** filter inspired by John's Background Switcher's wildcard picture ignoring: comma-separated wildcard patterns (for example `thumb*.jpg, banner*.png`) that skip matching picture file names when the library is scanned, with the option empty by default.
- Exposed it under **Settings → Sources → Folder scanning**, with Save Profile error feedback when a pattern is longer than 120 characters or more than 20 patterns are entered.
- Patterns are case-insensitive globs matched against picture file names only; explicitly configured individual pictures stay in rotation even when they match, and editing the patterns refreshes the library index exactly once.

### Changed

- Bumped the package version to `0.2.9`.

## [0.2.8] - 2026-10-25

### Added

- Per-profile **folder-order rotation** inspired by John’s Background Switcher’s in-order playback: when enabled, pictures cycle in folder order and restart from the beginning after the last picture, instead of the random no-repeat order, with the option off by default.
- Exposed it under **Settings → Rotation & Shortcuts → Rotation** next to the interval, with the existing Save Profile success/error feedback.
- Folder order applies to every layout mode, to dry-run previews, and to live rotations; each picture still appears exactly once per cycle.

### Changed

- Bumped the package version to `0.2.8`.

## [0.2.7] - 2026-10-24

### Added

- Per-profile **Ignore hidden files and folders** filter inspired by John’s Background Switcher’s hidden-file handling: pictures and folders whose names start with a dot are excluded from rotation when enabled, with the option off by default.
- Exposed under **Settings → Sources → Folder scanning** next to the recursive and minimum-image-size options.
- Hidden filtering is part of the scan signature, so toggling the option refreshes the library index exactly once. Explicitly configured folders and individual pictures stay in rotation even when their own names start with a dot.

### Changed

- Bumped the package version to `0.2.7`.

## [0.2.6] - 2026-10-23

### Added

- Per-profile **Minimum image size** filter inspired by John’s Background Switcher’s minimum-picture-size option: pictures whose smallest side is smaller than the limit are excluded from rotation, with no limit by default.
- Exposed it under **Settings → Sources → Folder scanning**, with Save Profile error feedback for non-numeric values.
- Header-only dimension checks that read only image headers during library scans, a filter-aware scan signature so changing the limit refreshes the index exactly once, and scan-completeness semantics that treat a filter-emptied folder as scanned instead of rescanning it forever.

### Changed

- Bumped the package version to `0.2.6`.

## [0.2.5] - 2026-10-22

### Added

- Task-based Settings navigation inspired by John’s Background Switcher’s simplified workflow: profile **Sources**, **Layout & Appearance**, and **Rotation & Shortcuts**, followed by application-wide **Public Collections**, **Storage**, and **Updates & About**.
- Explicit profile/application scope labels, selected-profile collection targeting with profile switching locked during active operations, and keyboard traversal across the six pages.
- A forced 944×668 Xvfb check for page order, keyboard navigation, scope labels, moved-control presence, all eight layouts, built-in theme geometry, and complete context/footer visibility.

### Changed

- Moved existing controls into their task pages without changing profile persistence, rendering, collection, storage, update, or apply behavior.
- Bumped the package version to `0.2.5`.

### Fixed

- Storage page working-files row: shortened the row label to "Working directory:" and narrowed the path entry so the whole row fits the minimum 944×668 Settings window under wider font metrics.
- Profile and layout strip: narrowed the profile entry, renamed Rename to Edit, and tightened padding so the strip fits the minimum window width under the clam theme as well.
- Footer action row: shortened "Save Current Wallpaper..." to "Save Wallpaper..." and "View Current Pictures..." to "View Pictures..." so the full row, including the version label, fits the minimum window width under the clam theme.

## [0.2.4] - 2026-10-21

### Added

- One unified **Layout** workspace, inspired by John’s Background Switcher’s single picture-mode workflow, with a plain-language description and only the contextual controls for the pending layout.
- Xvfb-backed 1024×768 coverage for all eight layout selections, profile-driven synchronization, contextual Postcard, Polaroid, and per-monitor controls, and non-mutating page navigation.

### Changed

- Replaced the eight peer layout tabs with one **Layout** page; choosing a layout from the persistent strip opens the synchronized workspace without saving or applying pending edits.
- Bumped the package version to `0.2.4`.

## [0.2.3] - 2026-10-18

### Added

- A persistent Settings context strip above the top-level notebook, keeping Profile, New, Rename, Delete, Layout, and Save Profile visible on all 11 existing pages.
- Xvfb-backed 1024×768 coverage that visits every page, checks the context and footer controls stay mapped and inside the window, verifies all eight Layout values, and proves page navigation does not change the pending layout.

### Changed

- Renamed **Save** to **Save Profile** and **Apply Next Now** to **Save & Apply Now** without changing either callback or action semantics.
- Reflowed the remaining General common settings after moving Layout and bounded the active working-folder path shown in status so long paths cannot hide the footer or make a typed candidate look active.
- Bumped the package version to `0.2.3`.

## [0.2.2] - 2026-08-19

### Added

- An optional per-profile Darken effect, inspired by John’s Background Switcher’s post-processing effects, that applies a fixed 0.85× brightness factor to the completed wallpaper.
- **darken** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, config, source/state safety, black-screen non-regression, and 1024×768 Xvfb-backed Settings coverage for the new effect.

### Changed

- Expanded the per-rotation **random** effect pool from ten to eleven concrete effects by including Darken.
- Bumped the package version to `0.2.2`.

## [0.2.1] - 2026-08-13

### Added

- An optional per-profile Brighten effect, inspired by John’s Background Switcher’s post-processing effects, that applies a fixed 1.15× brightness enhancement to the completed wallpaper.
- **brighten** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, config, source/state safety, black-screen non-regression, and 1024×768 Xvfb-backed Settings coverage for the new effect.

### Changed

- Expanded the per-rotation **random** effect pool from nine to ten concrete effects by including Brighten.
- Bumped the package version to `0.2.1`.

## [0.2.0] - 2026-08-12

### Added

- An optional per-profile Contrast effect, inspired by John’s Background Switcher’s post-processing effects, that applies a fixed 1.25× contrast enhancement to the completed wallpaper.
- **contrast** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, config, source/state safety, black-screen non-regression, and 1024×768 Xvfb-backed Settings coverage for the new effect.

### Changed

- Expanded the per-rotation **random** effect pool from eight to nine concrete effects by including Contrast.
- Bumped the package version to `0.2.0`.

## [0.1.33] - 2026-08-07

### Added

- Ten deterministic, asset-free procedural Postcard surfaces: felt, linen, kraft paper, watercolor paper, slate, plaster, concrete, brushed metal, sandstone, and terrazzo.
- Shared bounded high-DPI noise and material-detail primitives, stable per-style seeds, per-monitor variation, and continuous spanning textures.
- Config round-trip, Settings/Apply, service forwarding, material determinism, distinctness, photo-geometry/RNG isolation, visual, and performance coverage for the complete surface set.

### Changed

- Expanded **Settings → Postcard → Background** from dark and corkboard to twelve choices without changing the accepted corkboard generator, solid dark default, source photos, or bare-photo composition behavior.
- Documented that v0.1.32 and older display the ten new profile values as Dark and replace the new selection with Dark if that profile is saved from an older release.
- Bumped the package version to `0.1.33`.

## [0.1.32] - 2026-08-07

### Added

- A deterministic, procedurally generated cork surface with multi-scale grain plus sparse pores and fibers for the Postcard `corkboard` background.
- Texture and monitor-variation tests, solid-dark non-regression coverage, visual comparison, and high-resolution performance verification.

### Changed

- Replaced the flat corkboard-colored fill without adding a downloaded or bundled photographic texture, while keeping dark backgrounds and bare-photo layout behavior unchanged.
- Bumped the package version to `0.1.32`.

## [0.1.31] - 2026-08-06

### Added

- A per-profile **Background** selector under **Settings → Postcard**, with the existing dark background and a new warm corkboard option behind bare photos.
- Backward-compatible config, exact background-color composition coverage for per-screen and spanning layouts, service wiring, Apply/Save validation, and 1024×768 Xvfb-backed Settings coverage.

### Changed

- Kept `dark` as the default for existing profiles while allowing `corkboard` to be saved and applied independently for each profile.
- Bumped the package version to `0.1.31`.

## [0.1.30] - 2026-08-04

### Added

- An optional per-profile straight-photo setting for Postcard layouts, inspired by John’s Background Switcher, that keeps random placement and stacking while rendering every bare photo without rotation.
- **Randomly tilt photos** under **Settings → Postcard**, enabled by default for backward compatibility; clear it, then choose Save or **Apply Next Now** for visible success/error feedback.
- Backward-compatible config, per-screen and spanning composition, service wiring, and 1024×768 Xvfb-backed Settings coverage for the new option.

### Changed

- Bumped the package version to `0.1.30`.

## [0.1.29] - 2026-08-03

### Added

- A **Collections** Settings tab with user-triggered downloads for NASA Space, NASA Earth from Space, Wikimedia Commons sunsets and insects, and the official NPS Alaska Region import.
- Exact CC0/public-domain Wikimedia filtering, conservative NASA copyright-metadata filtering, trusted HTTPS host allowlists, bounded streaming, image verification, atomic no-overwrite installation, cancellation rollback, duplicate avoidance, and per-file provenance manifests.
- An option to add the downloaded collection folder to the current profile and save, plus links to USDA ARS, Smithsonian Open Access, and National Park Service sources requiring manual access or personal API keys.
- Fixture-backed downloader safety tests, live-provider verification, cancellable non-daemon Settings worker coverage, and 1024×768 Xvfb layout checks.

### Changed

- Bumped the package version to `0.1.29`.

## [0.1.28] - 2026-08-02

### Added

- A local blurred-edge letterbox fill, inspired by John’s Background Switcher, that places a scaled, softened copy behind the complete uncropped picture instead of using solid bars.
- **blurred** under **Settings → General → Settings applying to all modes → Letterbox bars**, with an explanatory label plus Save and **Apply Next Now** success/error feedback.
- Deterministic composition, source/state safety, black-screen non-regression, config, service, and 1024×768 Xvfb-backed Settings coverage for the new fill.

### Changed

- Bumped the package version to `0.1.28`.

## [0.1.27] - 2026-08-01

### Added

- An optional per-profile straight-print option for Polaroid layouts, inspired by John’s Background Switcher, that keeps random placement and stacking while rendering every print without rotation.
- **Randomly tilt prints** under **Settings → Polaroid**, enabled by default for backward compatibility; clear it, then choose Save or **Apply Next Now** for visible success/error feedback.
- Backward-compatible config, per-screen and spanning composition, service wiring, and 1024×768 Xvfb-backed Settings coverage for the new option.

### Changed

- Bumped the package version to `0.1.27`.

## [0.1.26] - 2026-07-31

### Added

- Individual local picture sources, inspired by John’s Background Switcher, alongside existing recursive source folders.
- **Add picture...** under **Settings → General → Shared picture sources**, with supported-file validation plus visible added, duplicate, and error feedback before Save and **Apply Next Now**.
- Individual-file discovery/index coverage and Xvfb-backed Settings visibility and persistence coverage.

### Changed

- Bumped the package version to `0.1.26`.

## [0.1.25] - 2026-07-30

### Added

- A per-profile Random effect, inspired by John’s Background Switcher, that independently chooses one existing concrete wallpaper effect for each successful rotation.
- **random** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Deterministic effect-selection, source-safety, dry-run/state-safety, and Xvfb-backed Settings coverage for the new option.

### Changed

- Bumped the package version to `0.1.25`.

## [0.1.24] - 2026-07-29

### Added

- An optional per-profile Saturate effect, inspired by John’s Background Switcher, that boosts the complete generated wallpaper to 1.5× color intensity while preserving neutral tones.
- **saturate** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Exact-pixel, source-safety, dry-run/state-safety, black-screen, and Xvfb-backed Settings coverage for the new effect.

### Changed

- Bumped the package version to `0.1.24`.

## [0.1.23] - 2026-07-28

### Added

- Per-profile Postcard controls for 1–100 photos, Small-to-Large size, and optional spanning across all screens, matching Polaroid count and placement behavior.

### Changed

- Postcard mode now displays bare native-aspect photos in randomized positions, tilt, overlap, and stacking order on the Polaroid dark background, with no generated white frames or pins.
- Postcard Span uses one combined virtual-desktop layout so photos may cross monitor seams or be clipped by the outer desktop edge.
- Bumped the package version to `0.1.23`.

## [0.1.22] - 2026-07-28

### Added

- A per-profile **Span across all screens** Polaroid option that composes one virtual-desktop layout, allowing prints to cross monitor boundaries and be clipped by the outer desktop edge.

### Changed

- Increased the Polaroid photo-count maximum from 20 to 100. The count remains per screen normally and becomes the total across the combined desktop when Span is enabled.
- Enlarged the Polaroid size-slider handle for easier grabbing.
- Bumped the package version to `0.1.22`.

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
