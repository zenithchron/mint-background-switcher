# Mint Background Switcher

Mint Background Switcher is a Linux Mint/Cinnamon wallpaper switcher for multi-monitor desktops. It rotates local image folders, supports one shared image pool or per-monitor folders, and fits each whole image inside its monitor with black, automatically color-matched, or blurred scaled-image fills instead of cropping the displayed picture.

## Features

- Local image folders with recursive scanning plus individually selected picture files.
- Optional per-profile minimum image size (smallest side) that keeps small pictures out of rotation.
- Optional per-profile ignore for hidden files and folders (names starting with a dot) in rotation.
- Optional per-profile ignore name patterns (case-insensitive wildcards such as `thumb*.jpg`) that keep matching picture file names out of rotation.
- Optional per-profile **Image types** filter (comma-separated list such as `jpg, png, webp`) that keeps rotation limited to the chosen picture formats; empty means all supported types.
- Optional per-profile monitor-orientation matching that prefers landscape pictures on landscape monitors and portrait pictures on portrait monitors.
- Random no-repeat rotation until each pool is exhausted, with an optional per-profile folder-order mode that cycles pictures in folder order and restarts from the beginning.
- Optional per-profile **Rotate at startup** toggle that keeps the current background after login instead of rotating right away; the normal interval takes over from there.
- Optional per-profile **night schedule** that keeps every monitor black during a configured nightly window (for example `22:00` to `06:00`, crossing midnight supported) and resumes rotation by itself when the window ends, while a manually triggered black screen stays sticky until resumed. Manually resuming inside an active window does not keep the desktop awake: the schedule re-applies the black screen on the next tick.
- Shared, same-image, 2x2 montage, asymmetric collage, postcard, Polaroid, per-monitor, and spanned wallpaper modes.
- Fractional-scale aware monitor composition for Cinnamon/X11.
- Named profiles for different folder/layout setups.
- Settings with a persistent Profile, Layout, and Save Profile strip above nine task-based pages: Sources, Layout & Appearance, Overlays, Rotation & Shortcuts, Conditions, Never Show Again, Public Collections, Storage, and Updates & About.
- Configurable Postcard layouts with 1–100 bare native-aspect photos, a Small-to-Large size slider, randomized placement/stacking, optional random tilt, optional photo captions, twelve selectable solid or procedurally textured backgrounds, and optional virtual-desktop spanning.
- Configurable Polaroid layouts with 1–100 native-aspect prints, a larger Small-to-Large size slider, randomized placement/stacking, optional random tilt, optional photo captions, and optional virtual-desktop spanning that permits monitor-boundary crossing and edge clipping.
- Selectable, validated working-file storage for generated wallpapers and the image-library index.
- Full **settings import / export** under **Settings → Storage → Import / Export** (and via the `export` / `import` CLI commands): export every profile, folder, and per-profile option to a JSON file, then restore a previous export with a single confirmed step; invalid import files are rejected without touching the current settings.
- Cached SQLite discovery and database-backed no-repeat rotation for very large local libraries.
- User-triggered managed updates from Settings with versioned per-user installs, atomic activation, restart, and rollback.
- Optional tray menu for quick actions.
- Save the current generated multi-monitor background to a PNG file from Settings or the CLI.
- View every unique original picture used in the current wallpaper, open a selected source or its containing folder, and keep selected pictures out of future rotation with a per-profile **Never Show Again** list (one click for the whole current wallpaper, individual remove, and clear-all with confirmation).
- User-triggered Public Collections downloads from NASA and rights-filtered Wikimedia Commons CC0/public-domain sets, with provenance manifests and optional profile-source setup.
- Per-profile **Web picture sources** under **Settings → Sources → Web picture sources**: up to 20 entries (http/https) per profile — direct image URLs or RSS/Atom picture feeds (feed lines carry a `[feed]` prefix) — downloaded and cached in the working folder, and rotated exactly like local pictures; unreachable, oversized, or non-image sources are reported per source and never block rotation (CLI: `web-source add <url> [--feed] | remove <url> | list | refresh [--dry-run]`).
- Optional per-profile random selection, grayscale, half-color desaturation, 1.5× saturation, 1.25× contrast, 1.15× brightening, 0.85× darkening, sepia, inverted-colors, soft-focus blur, vignette, and three-month calendar wallpaper effects.
- Black, automatically color-matched, or blurred scaled-image letterbox fills that keep each source picture whole.
- Per-profile display fit modes for fitted panels and montage/collage cells: fit with bars (default, historical), center, scale to fit, stretch, scale and crop (overscale), and scale and blur edges.
- Optional per-profile **Mirror wallpaper to the lock screen** toggle: GNOME gets an explicit lock-screen image on every rotation (Cinnamon already shows the desktop wallpaper on its lock screen; other desktops keep their own lock screen).
- Per-profile **picture overlays** under **Settings → Overlays**: optional title / photographer / date text and an optional **monthly calendar card with today highlighted** (corner choice: bottom right — default —, bottom left, top right, top left) drawn on top of the wallpaper for Shared, Same, Per-monitor, and Span layouts (multi-picture layouts never draw overlays), with per-profile **no-draw zones** (whole-desktop or per-monitor, pixel coordinates, up to 8) that the overlay panel always respects. Rendering happens at physical panel resolution, so overlays stay sharp on fractional-scale displays; anything that prevents drawing (a full zone, missing metadata, an error) skips that panel only and is reported as an `overlays` note. CLI: `mint-background-switcher overlay-info <image>` and `overlay-preview <image> [--out FILE] [--width N] [--height N] [--profile NAME]`.
- Per-profile **run conditions** that pause scheduled switching while a local condition holds: a named process is running, the laptop is on battery, a remote (VNC) session is active, the session has not been idle long enough, or the session is locked / the screensaver is active. Explicit switches (Save & Apply Now, `next`, resuming) always apply, and a condition that cannot be detected never blocks.
- Safe login autostart that waits for Cinnamon before rotating.
- Black-screen/privacy mode that stays black until resumed.
- Per-profile **rebindable global hotkeys** as Cinnamon custom keybindings: **Next** (default `<Primary><Alt>n`), **Previous** (default `<Primary><Alt>Left`), **Redraw Current** (default `<Primary><Alt>r`), **Pause/Resume** (default `<Primary><Alt>p`), and **Black screen** (default `<Primary><Alt>b`), edited under **Settings → Rotation & Shortcuts → Shortcuts** and registered in one step (or via `mint-background-switcher register-hotkey --all`).
- **Previous wallpaper**: step back one to the previously applied wallpaper — a per-profile history of the last 10 composed snapshots (newest first) restorable from the tray **Previous** item, `mint-background-switcher previous [--dry-run]`, or the **Previous** hotkey; restoring re-applies the exact snapshot (effects and overlays included) and clears a black screen or pause like a manual switch.
- **Redraw Current**: re-apply the wallpaper that is currently active (including the black screen, while one is active) without changing anything — from the tray **Redraw Current** item, `mint-background-switcher redraw-current [--dry-run]`, or the **Redraw Current** hotkey; it never advances the rotation, touches the history, or clears a pause or black screen.
- Built-in rescue command for disabling startup and resetting Cinnamon wallpaper/session settings from a TTY.

The Settings redesign is being delivered in independently verified increments. See the [product roadmap](ROADMAP.md) and [Settings UI redesign plan](docs/plans/settings-ui-redesign.md) for the implemented and planned work.

## Change log

### 0.2.28 - 2026-11-14

- Added **Redraw Current**: re-apply the wallpaper that is currently active without changing anything — from the tray **Redraw Current** item, the CLI (`mint-background-switcher redraw-current [--dry-run] [--profile NAME]`), or a new fifth rebindable Cinnamon hotkey (**Redraw Current**, default `<Primary><Alt>r`, configured like the other hotkeys under **Settings → Rotation & Shortcuts → Shortcuts**). It restores a wallpaper the desktop lost or reset (e.g. after a compositor glitch or manual change): the last applied composed file — or the black-screen composite while a black screen is active — is applied again on the same profile's desktops, and the lock-screen mirror is re-applied when enabled. It never picks a new picture, never advances the no-repeat rotation, never touches the history stack, and never clears a pause or black screen; `redraw-current --dry-run` is read-only (no state rewrite), and with no applicable wallpaper or a missing current file every path reports a one-line error (CLI exits 1). `register-hotkey --all` now registers all five hotkeys. Bumped the package version to `0.2.28`.

### 0.2.27 - 2026-11-13

- Added **Previous wallpaper**: step back one to the previously applied wallpaper of the active profile from the tray **Previous** item, the CLI (`mint-background-switcher previous [--dry-run] [--profile NAME]`), or a new fourth rebindable Cinnamon hotkey (**Previous**, default `<Primary><Alt>Left`, configured like the other hotkeys under **Settings → Rotation & Shortcuts → Shortcuts**). Every switch and black screen keeps a per-profile history of the composed snapshots it displaces (newest first, capped at 10, kept contiguous), so a step back restores exactly the wallpaper that was applied — effects and overlays included — into the alternating active slot, clears a black screen or pause, and re-applies the lock-screen mirror when enabled. `previous --dry-run` is read-only; with no recorded history every path reports a one-line error (CLI exits 1). Working-folder moves remap the recorded history, and `register-hotkey --all` registers all four hotkeys. Bumped the package version to `0.2.27`.

### 0.2.26 - 2026-11-12

- Added **RSS/Atom picture feeds** as the second keyless provider of **Settings → Sources → Web picture sources**: a new **Add feed** button (next to **Add URL**) lets a profile list RSS/Atom feeds whose items carry pictures; feed lines are shown with a `[feed] ` prefix in the same list and share its 20-entry cap. Each item contributes one picture, in feed order (up to 10 per feed), chosen as image `enclosure` → `media:content` → `media:thumbnail` → first `<img>` in the item content/description (including RSS `content:encoded`); relative URLs resolve against the feed URL. Feeds refresh on the same 24-hour window as direct URLs, keep pictures still listed, download new ones, and prune only their own pictures (per-feed sidecar), so a removed feed never touches another source's cache. A feed that is unreachable, unparseable, or lists no pictures is reported for that source only and never blocks rotation; cached feed pictures keep rotating while it is offline. CLI: `web-source add <url> --feed`. Bumped the package version to `0.2.26`.

### 0.2.25 - 2026-11-11

- Added the **calendar overlay** (JBS OVR-06) under **Settings → Overlays → Picture information**: a **Show calendar (current month, today highlighted)** checkbox plus a **Position** choice (Bottom right, Bottom left, Top right, Top left). The monthly calendar card draws on top of the composed wallpaper with today highlighted, composes independently of the title / photographer / date lines, honors the per-profile no-draw zones (an obstructed corner falls back to the next clear one; a fully covered panel is skipped without breaking rotation), works with the Shared, Same, Per-monitor, and Span layouts at physical panel resolution, and is reported through the same `overlays` note as the picture-information text. `overlay-preview` includes the calendar per profile. Bumped the package version to `0.2.25`.

### 0.2.24 - 2026-11-10

- The Settings window's nine pages now open from a **two-row tab bar** (top: Sources, Layout & Appearance, Overlays, Rotation & Shortcuts; bottom: Conditions, Never Show Again, Public Collections, Storage, Updates & About): selecting a tab in either row shows its page and dims the other row, Ctrl+Tab / Ctrl+Shift+Tab cycles pages across both rows, and every tab's behavior, accelerator letters, and the save/apply flow are unchanged. Page spacing was compacted so all nine pages still fit unclipped in the fixed 944×668 window (default and clam themes). Bumped the package version to `0.2.24`.

### 0.2.23 - 2026-11-09

- Added per-profile **picture overlays** (JBS OVR-01..OVR-05) under **Settings → Overlays** (new page): optional title / photographer / date text drawn on top of the composed wallpaper for Shared, Same, Per-monitor, and Span layouts (multi-picture layouts never draw overlays), plus up to 8 per-profile **no-draw zones** in pixel coordinates (whole-desktop or per-monitor) that the overlay panel always respects. Overlays compose with the selected display fit mode and render at physical panel resolution, so they stay sharp on fractional-scale displays; anything that prevents drawing skips that panel only and is reported as an `overlays` note by Save & Apply Now, the background loop, and the CLI.
- CLI: `mint-background-switcher overlay-info <image>` (title/photographer/date as JSON) and `overlay-preview <image> [--out FILE] [--width N] [--height N] [--profile NAME]` (standalone preview image). Bumped the package version to `0.2.23`.

### 0.2.22 - 2026-11-08

- Added per-profile **Web picture sources** (JBS SRC-03, first non-local source) under **Settings → Sources → Web picture sources**: up to 20 direct image URLs (http/https) with Add URL / Remove Selected / Refresh now and visible success/error feedback; downloaded images are cached in the working folder and rotate in every mode exactly like local pictures, and an unreachable, oversized, or non-image URL is reported for that source only — rotation is never blocked.
- CLI: `mint-background-switcher web-source add <url> | remove <url> | list | refresh [--dry-run]` (all with `--profile NAME`); `next` and Save & Apply Now report a `web_sources` status section. The stable source interface (per-profile entry list + shared cache directory) is the extension point for later keyless providers; bumped the package version to `0.2.22`.

### 0.2.21 - 2026-11-07

- Fixed a hang: switching to a profile whose picture collection is on an unavailable drive (dead network mount, disconnected share) no longer freezes the app — the switch is rejected with a warning (Settings rolls the activation back and keeps the previous profile active; the background loop skips the tick and retries automatically; CLI `next`/`resume` exit with a one-line error). A merely missing local folder keeps the established black-fallback behavior.

### 0.2.20 - 2026-11-07

- Added **settings import / export** under **Settings → Storage → Import / Export**, inspired by John's Background Switcher's config save/restore: **Export Settings...** writes every profile, folder, and per-profile option to a versioned JSON file, and **Import Settings...** restores a previous export (or a saved `config.json` copy) after a confirmation that names the full replacement.
- Import validates the file before anything is applied, and cancelling either dialog leaves the current settings untouched; imported values apply immediately (the editor shows the imported profiles, and the background loop uses them from its next rotation). CLI: `mint-background-switcher export [DESTINATION]` (file or stdout) and `mint-background-switcher import SOURCE [--dry-run]`; bumped the package version to `0.2.20`.

### 0.2.19 - 2026-11-06

- Added per-profile **rebindable global hotkeys** as Cinnamon custom keybindings — **Next** (default `<Primary><Alt>n`), **Pause/Resume** (default `<Primary><Alt>p`), and **Black screen** (default `<Primary><Alt>b`, the historic fixed binding) — editable under **Settings → Rotation & Shortcuts → Shortcuts** with a one-step **Register hotkeys** button.
- CLI: `register-hotkey --action next|pause-resume|black-screen` (default stays `black-screen`) plus `--all` and `--dry-run`, and a new `pause-toggle` command; the managed updater now rebinds every registered hotkey to the stable launcher after updates; bumped the package version to `0.2.19`.

### 0.2.18 - 2026-11-05

- Added a per-profile **Never Show Again (exclusion list)** on a new **Settings → Never Show Again** page: one click excludes every source picture of the currently applied wallpaper, with Remove Selected / Clear All for the list, a **Never Show Again** button and `[excluded]` markers in the Current Pictures dialog.
- Exclusions persist per profile (bounded to 1000 entries) and are skipped on every rotation path with normal wrap-around of the remaining pool; a fully excluded profile falls back to the existing safe black screen; bumped the package version to `0.2.18`.

### 0.2.17 - 2026-11-03

- Added per-profile **run conditions** on a new **Settings → Conditions** page, inspired by John's Background Switcher's switching conditions: five independent toggles pause *scheduled* background switching while a local condition holds — a named process is running (process names are limited to 15 characters), the laptop is on battery, a remote (VNC) session is active, the session has not been idle for the configured number of seconds, or the session is locked / the screensaver is active.
- Conditions pause the background loop only: **Save & Apply Now**, `mint-background-switcher next`, and resuming from a black screen always apply, and dry-run previews ignore conditions. While a condition holds the loop retries on a short cadence (at most 60 s) so a clearing condition resumes the schedule quickly; a night-window resume is deferred the same way; bumped the package version to `0.2.17`.

### 0.2.16 - 2026-11-02

- Added a per-profile **Mirror wallpaper to the lock screen** toggle under **Settings → Rotation & Shortcuts → Desktop integration**, inspired by John's Background Switcher's lock/logon-screen overlay: when enabled, the generated wallpaper is also written to the session lock screen on every rotation.
- GNOME exposes a per-user lock-screen image, so the same generated wallpaper is written there explicitly (including the black screen, so the lock screen never shows a stale picture); Cinnamon already shows the desktop wallpaper on its lock screen, so no extra write is needed there; desktops without a per-user lock-screen image setting report that the lock screen keeps its own image. A failed lock-screen write never breaks the desktop wallpaper path — the rotation completes and the note is reported by **Save & Apply Now**, `mint-background-switcher next`, and the background loop; bumped the package version to `0.2.16`.

### 0.2.15 - 2026-11-01

- Added a per-profile **Display fit mode** under **Settings → Layout & Appearance → Appearance**, inspired by John's Background Switcher's display modes: **Fit with bars** (the default, identical to the previous behavior), **Center (border color)**, **Scale to fit**, **Stretch**, **Scale and crop (overscale)**, and **Scale and blur edges**. The mode applies to every fitted panel in Shared, Same, Per-monitor, and Span layouts and to each cell of Montage and Collage layouts.
- The **Letterbox bars** control still chooses the bar style for the bar-based modes; Stretch and Scale and crop leave no unused space, so they ignore it; bumped the package version to `0.2.15`.

### 0.2.14 - 2026-10-31

- Added a per-profile **Image types** filter under **Settings → Sources → Folder scanning**, inspired by John's Background Switcher's file-type selection: enter comma-separated image types (for example `jpg, png, webp`; a leading dot is accepted and case is ignored) to keep rotation limited to those picture formats. Empty means all supported types, so existing profiles behave exactly as before.
- The filter is part of the scan signature, so changing it refreshes the library index exactly once; it applies to shared, per-monitor, and individually selected pictures, to recursive and flat scans, and to dry-run previews as well as live rotations; unknown types are rejected by **Save Profile** with a message box that names the supported types; bumped the package version to `0.2.14`.

### 0.2.13 - 2026-10-30

- Added a per-profile **night schedule** under **Settings → Rotation & Shortcuts → Rotation**, inspired by John's Background Switcher's time-of-day switching: enable **Keep the desktop black during a nightly window**, enter zero-padded `HH:MM` start and end times (for example `22:00` to `06:00`), and the background loop turns every monitor black when the window opens and restores rotation by itself when it ends. Windows may cross midnight, the start minute is included, and the end minute is not.
- Scheduled black screens are tracked separately from the manual black screen: the app resumes on its own when the night window ends, while a manually triggered black screen stays sticky until you resume it (hotkey, `mint-background-switcher resume`, or **Save & Apply Now**); dry runs never trigger the schedule; bumped the package version to `0.2.13`.

### 0.2.12 - 2026-10-29

- Added a per-profile **Rotate at startup** option under **Settings → Rotation & Shortcuts → Rotation**, inspired by John's Background Switcher's switch-at-startup option: when unchecked, the safe login start-up keeps the current background instead of rotating right after Cinnamon becomes ready, and the normal interval takes over from there.
- Black-screen and pause cycles never consume the skipped first rotation, resuming from privacy mode or an earlier pause still switches on the next cycle, and manual commands such as `next`, `resume`, and **Save & Apply Now** are unaffected; the option is on by default, so existing profiles behave exactly as before; bumped the package version to `0.2.12`.

### 0.2.11 - 2026-10-28

- Added per-profile **Show photo captions** options inspired by John's Background Switcher's captions-on-postcards feature: each Postcard photo can display its file name (without extension) inside the bottom of the picture, and each Polaroid print can display its file name on the bottom border of the frame. Both options are off by default, so existing layouts render exactly as before.
- The caption font scales to the photo width (with very long file names shortened with an ellipsis) and is drawn with a soft outline so it stays readable over any picture; captions never change placement, stacking, or random rotation behavior.
- Exposed both options as checkbuttons under **Settings → Layout & Appearance** next to the existing Postcard and Polaroid tilt controls, with the usual Save Profile / Save & Apply Now feedback; bumped the package version to `0.2.11`.

### 0.2.10 - 2026-10-27

- Added a per-profile **Match monitor orientation** option under **Settings → Sources → Folder scanning**, inspired by John’s Background Switcher’s monitor-orientation matching: when enabled, single-picture layouts prefer landscape pictures on landscape monitors and portrait pictures on portrait monitors, and the option is off by default.
- Orientation preferences apply to the Shared, Same, Span, and Per-monitor layouts, to dry-run previews, and to live rotations; multi-picture layouts (Montage, Collage, Postcard, Polaroid) are intentionally left unfiltered. Square pictures fit any monitor, unreadable headers never block rotation, and a monitor whose pool holds no matching picture falls back to whatever remains so rotation never blocks on shape alone; bumped the package version to `0.2.10`.

### 0.2.9 - 2026-10-26

- Added a per-profile **Ignore name patterns** option under **Settings → Sources → Folder scanning**, inspired by John's Background Switcher's wildcard picture ignoring: comma-separated case-insensitive wildcard patterns (for example `thumb*.jpg, banner*.png`) skip matching picture file names when the library is scanned, and the option is empty by default.
- Patterns match file names only; explicitly configured individual pictures stay in rotation even when they match, and editing the patterns refreshes the library index exactly once. Save Profile reports an error when a pattern exceeds 120 characters or more than 20 patterns are entered; bumped the package version to `0.2.9`.

### 0.2.8 - 2026-10-25

- Added a per-profile **folder-order rotation** option under **Settings → Rotation & Shortcuts → Rotation**, inspired by John’s Background Switcher’s in-order playback: when enabled, pictures cycle in folder order and restart from the beginning after the last picture instead of the random no-repeat order, and the option is off by default.
- Folder order applies to every layout mode, dry-run previews, and live rotations, and each picture still appears exactly once per cycle; bumped the package version to `0.2.8`.

### 0.2.7 - 2026-10-24

- Added a per-profile **Ignore hidden files and folders** option under **Settings → Sources → Folder scanning**, inspired by John’s Background Switcher’s hidden-file handling: pictures and folders whose names start with a dot are skipped when the library is scanned, and the option is off by default.
- Toggling the option refreshes the index exactly once; explicitly configured folders and individual pictures stay in rotation even when their own names start with a dot; bumped the package version to `0.2.7`.

### 0.2.6 - 2026-10-23

- Added a per-profile **Minimum image size** filter under **Settings → Sources → Folder scanning**, inspired by John’s Background Switcher’s minimum-picture-size option: pictures whose smallest side is smaller than the limit are skipped when the library is scanned, so mixed folders no longer rotate thumbnails.
- The limit uses the smallest side of each picture, defaults to 0 (no limit), needs only one library rescan when changed, and reports an error on Save Profile when the value is not a whole number; bumped the package version to `0.2.6`.

### 0.2.5 - 2026-10-22

- Reorganized Settings around user tasks, inspired by John’s Background Switcher’s simplified workflow: profile Sources, Layout & Appearance, and Rotation & Shortcuts, plus application-wide Public Collections, Storage, and Updates & About.
- Added explicit profile/application scope labels, selected-profile collection targeting with profile switching locked during active operations, and keyboard traversal without changing the underlying save, apply, rendering, download, storage, or update behavior.
- Added forced 944×668 Xvfb coverage for the six-page order, moved controls, scope labels, keyboard navigation, built-in theme geometry, all eight layouts, and persistent context/footer visibility; bumped the package version to `0.2.5`.

### 0.2.4 - 2026-10-21

- Replaced the eight separate layout tabs with one unified **Layout** workspace inspired by John’s Background Switcher’s single picture-mode workflow.
- Choosing a layout from the persistent strip now opens that workspace and immediately shows its description plus the relevant Postcard, Polaroid, or per-monitor controls; profile loading keeps the same workspace synchronized without saving pending edits.
- Added 1024×768 Xvfb-backed coverage for all eight layouts, profile loading, pending selection, contextual controls, and page navigation; bumped the package version to `0.2.4`.

### 0.2.3 - 2026-10-18

- Added a persistent Profile and Layout context strip above all 11 Settings pages, with New, Rename, Delete, and Save Profile available while any page is selected.
- Renamed the footer action to **Save & Apply Now**, reflowed the remaining General fields, and kept all profile persistence, rendering, and apply behavior unchanged.
- Added 1024×768 Xvfb-backed coverage for every page, all eight Layout values, non-mutating page changes, and in-window context/footer visibility; bumped the package version to `0.2.3`.

### 0.2.2 - 2026-08-19

- Added an optional 0.85× **darken** effect for the complete generated wallpaper, inspired by John’s Background Switcher’s post-processing effects.
- Exposed it under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Included Darken in the per-rotation **random** pool and added exact-pixel, source/state safety, black-screen, config, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.2.2`.

### 0.2.1 - 2026-08-13

- Added an optional 1.15× **brighten** effect for the complete generated wallpaper, inspired by John’s Background Switcher’s post-processing effects.
- Exposed it under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Included Brighten in the per-rotation **random** pool and added exact-pixel, source/state safety, black-screen, config, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.2.1`.

### 0.2.0 - 2026-08-12

- Added an optional 1.25× **contrast** effect for the complete generated wallpaper, inspired by John’s Background Switcher’s post-processing effects.
- Exposed it under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Included Contrast in the per-rotation **random** pool and added exact-pixel, source/state safety, black-screen, config, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.2.0`.

### 0.1.33 - 2026-08-07

- Added ten asset-free procedural Postcard surfaces: felt, linen, kraft paper, watercolor paper, slate, plaster, concrete, brushed metal, sandstone, and terrazzo.
- Kept the accepted corkboard rendering and solid dark default unchanged while preserving identical photo geometry and caller random-state behavior across every surface.
- Added shared bounded high-DPI rendering, deterministic per-surface and per-monitor seeds, full Settings/config/service coverage, and visual/performance verification.
- Compatibility note: v0.1.32 and older display these new profile values as Dark; saving that profile from an older release replaces the new selection with Dark.
- Bumped the package version to `0.1.33`.

### 0.1.32 - 2026-08-07

- Replaced the flat corkboard-colored Postcard fill with a subtle procedurally generated cork surface using multi-scale grain plus sparse pores and fibers.
- Kept the texture deterministic and asset-free, with no downloaded or bundled photographic texture and no changes to dark backgrounds or photo layout behavior.
- Added deterministic texture, monitor-variation, solid-dark non-regression, visual, and high-resolution performance coverage.
- Bumped the package version to `0.1.32`.

### 0.1.31 - 2026-08-06

- Added a per-profile **Background** selector under **Settings → Postcard**, with the existing dark background and a new warm corkboard option.
- Kept dark as the backward-compatible default and applied either background consistently to per-screen and virtual-desktop-spanning Postcard layouts.
- Added config, pixel-level composition, service, Apply/Save, validation, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.31`.

### 0.1.30 - 2026-08-04

- Added **Randomly tilt photos** under **Settings → Postcard**; clear it to keep the randomly placed bare photos straight.
- Added backward-compatible config, per-screen and spanning composition, service, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.30`.

### 0.1.29 - 2026-08-03

- Added a **Collections** Settings tab with optional NASA Space, NASA Earth from Space, public-domain/CC0 sunsets, insects, and NPS Alaska national-park downloads.
- Added explicit rights filtering, trusted HTTPS host allowlists, bounded streaming, image verification, atomic installation, cancellation rollback, duplicate avoidance, and per-file provenance manifests.
- Added an option to save the downloaded collection folder to the current profile, plus links to USDA ARS, Smithsonian Open Access, and National Park Service sources that require manual access or personal API keys.
- Added fixture-backed safety/lifecycle tests, live-provider checks, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.29`.

### 0.1.28 - 2026-08-02

- Added a local blurred-edge letterbox fill that places a scaled, softened copy behind the complete uncropped picture.
- Added **blurred** under **Settings → General → Settings applying to all modes → Letterbox bars**, with an explanatory label plus Save and **Apply Next Now** success/error feedback.
- Added deterministic composition, source/state safety, black-screen non-regression, config, service, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.28`.

### 0.1.27 - 2026-08-01

- Added an optional straight-print Polaroid layout that keeps random placement and stacking without rotating prints.
- Added **Randomly tilt prints** under **Settings → Polaroid**, enabled by default; clear it, then Save or choose **Apply Next Now** for visible success/error feedback.
- Added backward-compatible config, per-screen and spanning composition, service, and 1024×768 Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.27`.

### 0.1.26 - 2026-07-31

- Added individual local picture sources alongside recursive source folders.
- Added **Add picture...** under **Settings → General → Shared picture sources**, with supported-file validation plus visible added, duplicate, and error feedback before Save and **Apply Next Now**.
- Added individual-file discovery/index tests and Xvfb-backed Settings visibility and persistence coverage.
- Bumped the package version to `0.1.26`.

### 0.1.25 - 2026-07-30

- Added a **random** per-profile effect that independently chooses one existing concrete wallpaper effect for every successful rotation.
- Added **random** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Added deterministic selection, source-safety, dry-run/state-safety, and Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.25`.

### 0.1.24 - 2026-07-29

- Added an optional **saturate** effect that boosts the complete generated wallpaper to 1.5× color intensity while preserving neutral tones.
- Added **saturate** under **Settings → General → Settings applying to all modes → Effect**, with Save and **Apply Next Now** success/error feedback.
- Added exact-pixel, source-safety, dry-run/state-safety, black-screen, and Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.24`.

### 0.1.23 - 2026-07-28

- Replaced Postcard frames, pins, fixed four-cell layout, and corkboard background with bare native-aspect photos using Polaroid-style randomized placement, tilt, overlap, stacking, and dark background.
- Added separate per-profile Postcard controls for 1–100 photos, Small-to-Large size, and Span across all screens.
- Postcard count is per screen normally and total across the combined desktop while spanning; spanning photos may cross monitor seams or be clipped at the outer desktop edge.
- Bumped the package version to `0.1.23`.

### 0.1.22 - 2026-07-28

- Added **Span across all screens** to Polaroid settings so prints can cross monitor boundaries or extend beyond the outer desktop edge.
- Increased the Polaroid count maximum to 100; the count is per screen normally and total across the combined desktop while spanning.
- Enlarged the Polaroid size-slider handle and added focused config, composition, service, and Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.22`.

### 0.1.21 - 2026-07-28

- Added **Open Containing Folder** under **Settings → View Current Pictures...** to send the selected source's folder to the desktop file manager.
- Added selected-source revalidation, fixed-argument/no-shell launching, responsive success/error feedback, and Xvfb-backed Settings coverage.
- Bumped the package version to `0.1.21`.

### 0.1.20 - 2026-07-27

- Reorganized Settings into General, one tab per wallpaper mode, and About & Updates. Shared sources remain in General; monitor assignments live under Per-monitor.
- Added per-profile Polaroid photo-count and size controls with backward-compatible defaults of four medium prints.
- Removed Polaroid letterbox bars and changed each render to use snug native-aspect frames with randomized positions, tilt, overlap, and stacking order.
- Bumped the package version to `0.1.20`.

### 0.1.19 - 2026-07-27

- Managed updates now automatically restart active tray, safe-start, or background-loop processes through the newly activated launcher.
- Added focused process-discovery, graceful-stop, zombie-state, relaunch, and Settings feedback coverage.
- Bumped the package version to `0.1.19`.

### 0.1.18 - 2026-07-27

- Added a local `collage` mode that arranges five uncropped photos per monitor in a deterministic asymmetric mosaic.
- Added **collage** under **Settings → Profile settings → Mode**; save the profile or choose **Apply Next Now** for success/error and explicit safe-black-fallback feedback.
- Added deterministic composition, source-edge, bounded malformed/oversized-image fallback, dry-run/source/state safety, black-screen, no-repeat selection, and Xvfb-backed Settings/About tests.
- Bumped the package version to `0.1.18`.

### 0.1.17 - 2026-07-26

- Added a local `polaroid` mode that arranges four uncropped photos per monitor as individually tilted, bottom-heavy white prints on a dark background.
- Added **polaroid** under **Settings → Profile settings → Mode**; save the profile or choose **Apply Next Now** for success/error and explicit safe-black-fallback feedback.
- Added deterministic composition, source-edge, malformed-image fallback, dry-run/source/state safety, black-screen, no-repeat selection, and Xvfb-backed Settings/About tests.
- Bumped the package version to `0.1.17`.

### 0.1.16 - 2026-07-25

- Added **View Current Pictures...** to list every unique original image used in the current wallpaper and open a selected source with the default desktop application.
- Added no-picture, launch-success, missing-file, unavailable-opener, and nonzero launch-error feedback, plus stale-list refresh and pre-open revalidation, while keeping wallpaper state and source files unchanged.
- Added read-only service tests and Xvfb-backed Settings visibility, refresh, selection, version, asynchronous success, and error coverage.
- Bumped the package version to `0.1.16`.

### 0.1.15 - 2026-07-24

- Added an optional half-color desaturation effect for the complete generated wallpaper in every layout mode.
- Added **desaturate** under **Settings → Profile settings → Effect**; save the profile or choose **Apply Next Now** for success/error feedback.
- Added exact-pixel, source-safety, black-screen, and Xvfb-backed Settings tests.
- Bumped the package version to `0.1.15`.

### 0.1.14 - 2026-07-23

- Added an optional inverted-colors effect for the complete generated wallpaper in every layout mode.
- Added **invert** under **Settings → Profile settings → Effect**; save the profile or choose **Apply Next Now** for success/error feedback.
- Added exact-pixel, source-safety, black-screen/fallback, and Xvfb-backed Settings tests.
- Bumped the package version to `0.1.14`.

### 0.1.13 - 2026-07-22

- Added a persistent image-library index and database-backed no-repeat pools for responsive rotation with approximately 64,000 images and larger accidental recursive trees.
- Added **Working files** controls to browse for or explicitly create a dedicated generated-file folder, with ownership, overlap, nesting, collision, permission, and availability validation.
- Added staged, verified, cancellable migration that retains the old generated files and never moves or modifies source images.
- Moved tray rotation and Settings **Apply Next Now** off their GUI event loops, coalesced repeated tray **Next** actions, and launch Settings independently from the tray.
- Bumped the package version to `0.1.13`.

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
- `xdg-open` from `xdg-utils` for opening current source pictures or their containing folders from Settings.
- GTK/AppIndicator bindings for optional tray mode.

On Linux Mint or Ubuntu, install the usual system packages with:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pil python3-tk python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 xdg-utils
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

The persistent strip above the Settings pages always shows the current **Profile** and **Layout**, along with **New**, **Rename**, **Delete**, and **Save Profile**. Choosing a Layout opens **Layout & Appearance**, whose description and contextual Postcard, Polaroid, or per-monitor controls always match the pending layout. Visiting **Sources**, **Rotation & Shortcuts**, or any application page does not change that pending selection. **Save Profile** saves without changing the desktop, while **Save & Apply Now** keeps the existing save-then-generate-and-apply behavior. Use `Ctrl+Tab` and `Ctrl+Shift+Tab` to move between pages.

The Settings window exposes user-facing wallpaper controls, including the **collage**, **polaroid**, **postcard**, and **montage** layouts, profile effects such as **random**, **brighten**, **darken**, **contrast**, **saturate**, **desaturate**, **invert**, and the three-month **calendar**, plus **Black Screen**, **Save Current Wallpaper...**, and **View Current Pictures...**. Profile-scoped pages show the selected profile by name; application-wide pages are labeled separately. Under **Sources → Shared picture sources**, choose **Add folder...** for a local library or **Add picture...** for one individual local file, then choose **Save Profile** or **Save & Apply Now**. **Folder scanning** also offers a **Minimum image size** in pixels on the smallest side (0 means no limit); smaller pictures are skipped when the library is scanned. Enabling **Ignore hidden files and folders** additionally skips pictures and folders whose names start with a dot, while any folder or picture you configured explicitly stays in rotation. **Ignore name patterns** accepts comma-separated case-insensitive wildcards such as `thumb*.jpg, banner*.png`; matching picture file names are skipped when the library is scanned, and explicitly configured individual pictures stay in rotation even when they match. **Match monitor orientation** is a selection preference rather than a scan filter: with it enabled, Shared, Same, Span, and Per-monitor layouts prefer pictures whose orientation matches each monitor, while Montage, Collage, Postcard, and Polaroid layouts keep their existing behavior. Under **Public Collections**, choose a rights-filtered public collection, a count from 10 to 100, and a local library folder; downloads happen only after **Download Collection** is selected, and the page names the profile that optional source setup will modify. Profile switching stays disabled while the download is active so completion cannot target a different profile. Under **Layout & Appearance → Appearance → Letterbox bars**, choose **blurred** to fill unused space with a scaled, softened copy while keeping the whole picture visible. Under **Layout & Appearance → Appearance → Display fit mode**, choose how each fitted picture fills its panel: **Fit with bars** (default, the historical downscale-only letterbox behavior), **Center (border color)** (unscaled picture on the bar-color background, with oversized pictures showing their central region), **Scale to fit** (small pictures are enlarged so one edge touches the panel), **Stretch** (fills the panel exactly, distorting the aspect ratio when necessary), **Scale and crop (overscale)** (covers the panel and center-crops the overflow), or **Scale and blur edges** (unused space filled with a heavily blurred copy of the picture). Choose **postcard** in the Layout selector and clear **Randomly tilt photos** to keep randomly placed bare photos straight; choose **polaroid** and clear **Randomly tilt prints** to keep those prints straight. In either layout, enable **Show photo captions** to print each picture's file name (without its extension) inside the Postcard photo or on the Polaroid frame border; both caption options are off by default. **Rotation & Shortcuts** contains the interval, the optional **night schedule** (a nightly window in zero-padded `HH:MM` times, able to cross midnight, during which the desktop stays black and rotation resumes by itself when the window ends — a manually triggered black screen is never touched by the schedule), the **Shortcuts** section with the five rebindable Cinnamon hotkeys (**Next**, **Previous**, **Redraw Current**, **Pause/Resume**, and **Black screen**) plus a **Register hotkeys** button, and desktop integration. In the Current Pictures window, select a source and choose **Open Picture** or **Open Containing Folder**. **Storage → Working files** selects where generated wallpapers and the image-library index live, and **Storage → Import / Export** backs up the full settings — every profile, folder, and per-profile option — to a JSON file with **Export Settings...**, or restores them from a previous export with **Import Settings...** (the confirmation dialog makes clear that importing replaces every profile and setting; cancelling leaves the current settings untouched, and an invalid file is rejected before anything is applied). The footer shows the installed version; choose **Updates & About** for the version, project details, **Check for Updates...**, and **Roll Back...**. Follow the [roadmap](ROADMAP.md) and detailed [Settings UI redesign plan](docs/plans/settings-ui-redesign.md) for later source-management and edit-lifecycle increments.

## Public Collections

Public Collections are opt-in and never run in the background. MBS currently offers NASA Space, NASA Earth from Space, Wikimedia Commons sunsets, Wikimedia Commons insects, and an official NPS Alaska Region import. Wikimedia results are accepted only when their current item metadata says **CC0** or **Public domain**. NASA search records with a nonempty copyright field are rejected. NASA material remains subject to NASA's media-use, branding, endorsement, and identifiable-person guidance.

Images stream directly from exact allowlisted NASA or Wikimedia HTTPS hosts into a collection-specific subfolder. Each response is size-bounded and verified as an image before an atomic no-overwrite install. Cancellation removes files newly installed by that operation while retaining earlier collection files and their manifest. Repeating a download verifies and reuses existing manifest-owned images rather than replacing them. The hidden `.mbs-public-collection.json` manifest records the source page, provider identifier, creator, license or usage guidance, download URL, filename, and SHA-256 digest for each image.

The downloader does not guarantee that every legally reusable file is aesthetically suitable or free of embedded text. Public-domain or CC0 status addresses copyright only; review trademarks, privacy/publicity rights, people, artwork, and provider guidance before redistributing a pack. Additional USDA ARS, Smithsonian Open Access, and National Park Service links are shown for manual use; they are not scraped, and shared API credentials are not embedded in the desktop application.

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

Profiles, runtime state, startup logs, generated wallpapers, the image-library index, and other user data remain outside the managed installation. Generated wallpapers and the index use the default MBS cache unless a dedicated working folder is selected in Settings. Existing safe-start/tray autostart mode and delay are rewritten to the stable launcher. Every registered Mint Background Switcher hotkey is rebound to the same stable launcher. After activation, any active tray, safe-start, or background-loop process is stopped and relaunched through the new stable launcher; if that restart fails, Settings reports the failure while leaving the verified update active.

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

# Register the Cinnamon hotkeys (Next, Previous, Redraw Current, Pause/Resume, Black screen) from saved bindings
mint-background-switcher register-hotkey --all

# Register only one action with an explicit binding (default action: black-screen)
mint-background-switcher register-hotkey --action next --binding '<Primary><Alt>n'

# Toggle rotation pause/resume without switching pictures
mint-background-switcher pause-toggle

# Export all profiles and settings to a JSON file (omit the destination to print to stdout)
mint-background-switcher export ~/settings-backup.json

# Validate an export file without changing anything
mint-background-switcher import ~/settings-backup.json --dry-run

# Replace the current settings with a previous export
mint-background-switcher import ~/settings-backup.json
```

## Configuration paths

- Config and profiles: `~/.config/mint-background-switcher/config.json`
- Runtime state: `~/.config/mint-background-switcher/state.json`
- Startup guard: `~/.config/mint-background-switcher/startup-guard.json`
- Generated wallpapers and image-library index: `~/.cache/mint-background-switcher/` by default, or the dedicated folder selected under **Storage → Working files**
- Startup log: `~/.cache/mint-background-switcher/startup.log` (not relocated with working files)
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

## Working files and large libraries

MBS treats configured wallpaper folders and individual picture files as read-only sources. It does not create thumbnails, resized copies, metadata files, or indexes beside those sources. Discovery metadata and no-repeat pools live in `library-index.sqlite3` in the MBS working folder. A fresh or stale index is refreshed transactionally; warm rotations reuse it for five minutes. When a profile sets a **Minimum image size**, the scan reads only image headers and skips pictures whose smallest side is smaller than the limit; when it enables **Ignore hidden files and folders**, the scan skips names starting with a dot while still honoring explicitly configured roots; when it sets **Ignore name patterns**, the scan skips picture file names matching any of the case-insensitive wildcard patterns while still honoring explicitly configured individual pictures. Changing any of these settings refreshes the index exactly once instead of on every rotation, and a folder whose pictures are all filtered out still counts as scanned. A separate **Match monitor orientation** setting changes selection instead of scanning: single-picture layouts prefer pictures whose orientation matches each monitor, orientation results are cached in the image-library index with file-change invalidation, and a monitor with no matching picture available falls back to any remaining picture. A no-repeat pool is refilled near-linearly once per cycle, then ordinary draws fetch only the bounded rows needed for the next wallpaper. Scanning, selection, decoding, composition, and Settings migration run outside GTK/Tk event loops.

The default working folder is `~/.cache/mint-background-switcher/`. To use another disk or location, open **Settings → Storage → Working files** and choose **Browse...** for an empty or previously MBS-owned folder, or **Create Folder...** to explicitly create one child folder under a chosen parent. A typed nonexistent path is created only after confirmation and only when its parent already exists. **Use Folder...** validates the destination and copies only generated wallpaper PNGs and image-index files. Copy contents are verified before configuration changes, name collisions are rejected, and the old files are retained for recovery.

MBS rejects a working folder that overlaps any source-image folder, contains or is contained by the current working folder, is a foreign nonempty directory, has an invalid ownership marker, is not writable, or is unavailable. If an activated custom volume later disappears, rotation reports that exact failure and does not fall back to an unrelated cache. Configuration, `state.json`, startup logs, managed installations, desktop integration, autostart entries, and hotkeys are not relocated.

## Profile modes

Each profile has a mode:

- `shared`: all monitors draw from one shared image pool, without duplicates within the same rotation when possible.
- `same`: one image is picked from the shared image pool and fitted independently on every monitor.
- `montage`: four images from the shared pool are arranged in a 2x2 grid on each monitor, with every complete image fitted inside its tile instead of cropped.
- `collage`: five images from the shared pool are fitted without cropping into a deterministic asymmetric mosaic independently on each monitor.
- `postcard`: 1–100 bare images from the shared pool are placed at native aspect ratios with randomized positions, overlap, stacking, optional tilt, and optional file-name captions on a dark background. By default the count applies per screen and each photo stays fully visible on its screen; optional Postcard Span makes the count desktop-wide and allows photos to cross screen boundaries or be clipped at the virtual desktop edge.
- `polaroid`: 1–100 images from the shared pool are placed at native aspect ratios inside bottom-heavy white print frames with random placement, stacking, optional tilt, and optional file-name captions on the frame border. By default the count applies per screen and each print stays fully visible on its screen; optional Polaroid Span makes the count desktop-wide and allows prints to cross screen boundaries or be clipped at the virtual desktop edge.
- `per-monitor`: each monitor uses its own folder list. If a monitor has no explicit folders, it falls back to the shared folders.
- `span`: one image is fit with configured letterbox bars across the full virtual desktop canvas.

In fitted layouts, the default **Fit with bars** display fit mode keeps every foreground picture fully visible and never fill-crops it. Other per-profile display fit modes trade that guarantee for fuller panels: **Center** shows the unscaled picture (center-cropping oversized ones), **Scale to fit** enlarges small pictures, **Stretch** distorts to fill exactly, and **Scale and crop (overscale)** fills and center-crops. **Scale and blur edges** keeps the whole picture visible like the default, but fills unused space with a blurred copy of the picture. Letterbox bars are black by default; choose `auto` in Settings to match each panel's bars to the average source color, or `blurred` to place a scaled, center-cropped, softened duplicate behind the complete foreground picture. Only that decorative blurred backdrop is cropped. In `span` mode, the single source image determines the fill for the full canvas. If Cinnamon monitor scale is set to 75%, 125%, 150%, 175%, or 200%, monitor detection composes wallpapers at the physical panel resolution instead of the scaled logical desktop size.

Each profile can optionally apply a `grayscale`, half-color `desaturate`, vivid `saturate`, tone-deepening `contrast`, gently lifting `brighten`, softly dimming `darken`, warm vintage-style `sepia`, complementary-color `invert`, soft-focus `blur`, edge-darkening `vignette`, or three-month `calendar` effect after composing the complete multi-monitor wallpaper. The `random` setting independently chooses one of those eleven concrete effects for each successful rotation; it never resolves to `none` or another `random` choice. Desaturation blends each RGB pixel halfway toward grayscale so muted color remains; saturation raises color intensity to 1.5× while leaving neutral tones neutral; contrast applies a fixed 1.25× enhancement; brighten applies a fixed 1.15× brightness factor; darken applies a fixed 0.85× brightness factor; invert complements every RGB channel after composition. The calendar shows the previous, current, and next months near the bottom of the wallpaper and highlights today. Choose the effect under **Settings → Layout & Appearance → Appearance → Effect**, choose **Save Profile**, then use **Save & Apply Now** (or run `next`) to preview the result on the desktop. The default `none` setting leaves image colors unchanged.

## Monitor names

Monitor names come from `xrandr`, for example `DP-1`, `HDMI-1`, or `eDP-1`. Open settings after connecting monitors to see current names. In settings, use **Add per-monitor folder...** to browse to a folder first, then choose the screen in the dialog. Use **Remove per-monitor folder...** to delete an assignment.

For tests, you can provide virtual monitor geometry:

```bash
MBS_TEST_MONITORS='Left:1920x1080+0+0,Middle:2560x1440+1920+0,Right:1920x1080+4480+0' \
  mint-background-switcher next --dry-run
```

Add `@150%`, `@1.25`, etc. when you want the test geometry to simulate Cinnamon monitor scale.

## Switching behavior

Live wallpaper changes are rendered to an off-screen active file first, then applied by switching the desktop URI. The app alternates between two active files so the image currently displayed by Cinnamon/GNOME is not overwritten in place. Tray rotation and Settings **Save & Apply Now** use non-daemon background workers so their interfaces remain responsive; repeated tray **Next** requests coalesce to one pending rotation. Normal Cinnamon wallpaper changes only update the desktop background URI/options; they do not modify Muffin/Nemo transition or panel settings automatically.

`save-current` copies that generated PNG, including the complete multi-monitor composition, without selecting new source images or changing runtime state. In Settings, choose **Save Current Wallpaper...** and select a PNG destination; Settings asks before replacing an existing file. From the CLI, the destination must end in `.png` and existing files are protected unless `--force` is supplied.

**View Current Pictures...** reads the last successful wallpaper's source list without advancing rotation or changing persistent state. Its local selection window de-duplicates originals used across monitors or multi-photo layouts, refreshes when revisited, and revalidates the list immediately before asynchronously sending the selected existing file or its resolved parent folder to `xdg-open`. Choose **Open Picture** for the default image application or **Open Containing Folder** for the desktop file manager. Missing files, unavailable launchers, and nonzero opener exits stay in Settings as actionable errors. The source library remains read-only.

Black-screen mode uses Cinnamon/GNOME solid-black color mode before doing monitor detection or fallback PNG work, so the visible switch should be near-instant. If a configured image folder is empty or temporarily unavailable, normal rotation applies a non-sticky black fallback instead of erroring, then retries on the next rotation.

## Safe login startup and recovery

`autostart --enable` writes a guarded `safe-start` desktop entry. Safe-start waits before doing readiness checks, confirms Cinnamon/gsettings/monitor detection are sane, writes progress to `~/.cache/mint-background-switcher/startup.log`, and marks startup state in `~/.config/mint-background-switcher/startup-guard.json`.

If a previous startup never reached the ready phase, the next safe-start disables autostart and exits instead of trying again at boot.

If Cinnamon ever comes up without panel/menu, switch to a TTY with `Ctrl+Alt+F3`, log in, go to the repository checkout, and run:

```bash
./scripts/mint-background-switcher rescue --full --reboot
```

`rescue --light` disables Mint Background Switcher, backs up its normal cache plus any marker-validated custom working folder, and resets wallpaper without touching source-image folders. `rescue --full` also backs up and resets Cinnamon/Nemo dconf settings and `monitors.xml`, which is more disruptive but is the recovery path for an icons-only desktop failure.

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
