# Mint Background Switcher Roadmap

This roadmap turns the John’s Background Switcher 6.1 parity audit into an implementation order for Mint Background Switcher. It is ordered by user value and dependency, not by raw feature count.

## Product principles

- Local-first and usable without an account or cloud service.
- Keep every foreground picture visible by default: the default display fit mode (fit with bars) never fill-crops or distorts; stretch and scale-and-crop exist only as opt-in per-profile modes chosen in `0.2.15`.
- Preserve deterministic per-monitor source assignment and database-backed no-repeat rotation.
- Treat source folders and files as read-only.
- Keep privacy mode, recovery, state writes, updates, and downloads fail-safe.
- Make ordinary workflows discoverable in Settings before adding more CLI-only controls.
- Prefer a shared provider/cache/provenance architecture over one-off integrations.

## Implementation order

### 1. Settings UI redesign — active

Before `0.2.3`, the Settings window exposed most features through navigation that reflected implementation history rather than user tasks: Profile context and Save were limited to General, while the selected layout was separate from the layout tab being viewed. Increment 1 made Profile, Layout, and Save persistent; Increment 2 replaced the eight peer layout tabs with one synchronized Layout workspace; Increment 3 grouped the remaining controls into profile tasks and application tasks.

**Status:** Increments 1–3 are complete in `0.2.3` through `0.2.5`; Increment 4 is complete in `0.2.31`; Increment 5 is complete in `0.2.32`; Increment 6 is in progress — part 1 (nonmodal status feedback) shipped in `0.2.35`, with the remaining label/keyboard/focus/screen-reader/1024×768 polish next.

Implement the redesign in small, testable increments:

1. **Persistent editing context and clearer actions — complete in `0.2.3`** — Profile, profile management, Layout, and Save Profile now remain above the page tabs; Apply Next Now is now Save & Apply Now. Existing behavior and all 11 pages are preserved.
2. **Unified Layout workspace — complete in `0.2.4`** — the eight peer layout tabs are now one Layout page. Selecting a layout opens its plain-language description and the relevant Postcard, Polaroid, or per-monitor controls, so the visible workspace and pending selection cannot disagree.
3. **Task-based navigation — complete in `0.2.5`** — profile controls now live under Sources, Layout & Appearance, and Rotation & Shortcuts; application controls live under Public Collections, Storage, and Updates & About. Scope labels name the selected profile or shared application scope, and keyboard traversal covers all six pages.
4. **Structured source management — complete in `0.2.31`** — source lists are read-only rows showing source type, location, scope, and availability, with explicit Add, Remove, and Reveal actions.
5. **Safe edit lifecycle — complete in `0.2.32`** — an Unsaved indicator, a Revert button, and save/discard/cancel protection when switching profiles or closing; emergency Black Screen applies from the saved settings without persisting unrelated pending edits.
6. **Responsive and accessible polish — in progress** — improve labels, keyboard traversal, focus, nonmodal status feedback, screen-reader meaning, and 1024×768 behavior. Nonmodal status feedback (the persistent Settings status line) shipped in `0.2.35`.

UI work must preserve all profile/config fields, callbacks, update safety, source immutability, and wallpaper rendering behavior. Every increment requires focused Tk/Xvfb coverage and the full suite.

### 2. Reliability before feature breadth

1. Skip and transactionally discard corrupt or unreadable images in every rendering mode rather than aborting a rotation.
2. Make safe-start fail when `xrandr` or monitor discovery fails instead of reporting false readiness.
3. Add real Linux Mint acceptance coverage for monitor hotplug, fractional scaling, Cinnamon application, tray behavior, privacy transitions, suspend/resume, and long-running schedules.

### 3. Online-source foundation

Build one provider contract for identity, configuration, authentication, paging, rate limits, retries, local caching, durable IDs, deduplication, attribution, provenance, and source navigation.

Initial provider order:

1. RSS, Media RSS, and direct-image URLs.
2. Immich.
3. Pexels, Pixabay, Unsplash, and Wallhaven.
4. Flickr, Dropbox, OneDrive, and SmugMug.
5. Last.fm and Vladstudio only if their value justifies their maintenance burden.

Migrate the existing NASA and Wikimedia collection downloaders onto the shared provider/provenance foundation where practical.

### 4. Source, filtering, and scheduling controls

- Independent source-set add, edit, enable, disable, and cross-source mixing.
- Ignored folders, path exclusions, and temporary-unavailability handling. Orientation matching shipped in `0.2.10` as a per-profile selection preference; minimum dimensions (smallest side) shipped in `0.2.6`, hidden files/folders (dot names) in `0.2.7`, and filename pattern exclusions in `0.2.9` as per-profile Settings filters; optional folder-order rotation shipped in `0.2.8` as a per-profile rotation mode.
- Broader intervals, switch at startup, startup delay, and topology-change refresh. Switch-at-startup shipped in `0.2.12` as a per-profile Rotate-at-startup toggle under Rotation & Shortcuts. Startup delay shipped in `0.2.36` as a per-profile **Startup delay (minutes)** field under Rotation & Shortcuts → Rotation: it postpones the first scheduled wallpaper change after the background loop starts by a user-set number of minutes (0 = switch on the normal schedule), composing with the safe-start readiness guard and the rotation interval. Topology-change refresh shipped in `0.2.37` as a per-profile toggle under Settings → Conditions → Reactions (on by default): when the connected monitor layout changes, the background loop re-applies the current wallpaper — from its own source pictures — for the new layout within about half a minute, without picking a new picture or clearing a black screen.
- Optional suppression while locked, on battery, not idle, or while selected applications are running. Rich run-conditions shipped in `0.2.17` as five per-profile toggles on the Settings → Conditions page (named process, battery, remote/VNC session, idle-only, locked/screensaver), pausing scheduled switching only and failing open when a condition cannot be detected.
- Optional post-switch command hook. Shipped in 0.2.29 as a per-profile single-line command (split with `shlex.split`, no shell, 30 second timeout) under Settings → Rotation & Shortcuts → Rotation; failures surface as a `post_switch` note and never break the switch.

### 5. History and current-wallpaper actions

- Never Show Again exclusions, including one image in a composite. Shipped in `0.2.18` (whole-current-wallpaper one-click exclusion; single-image exclusion within a composite remains future work).
- Previous and redraw-current actions. Previous shipped in `0.2.27` as a per-profile 10-step history with tray, CLI, and hotkey access; redraw-current shipped in `0.2.28` as a re-apply-the-active-wallpaper action with tray, CLI, and hotkey access.
- Shuffle current monitor assignments. Shipped in `0.2.33` as the **Shuffle Assignments** button on the Layout & Appearance per-monitor section (a pending edit kept with Save Profile / Save & Apply Now), the tray **Shuffle Monitors** item, and `shuffle-monitor [--dry-run]`: per-monitor folders are redistributed across the assigned screens (each keeps its folder count), and a live action persists the new assignment and applies a new wallpaper immediately. Clear background remains future work (the emergency Black screen is the current closest equivalent).
- Browse recent cached pictures and navigate to their original sources. Shipped in `0.2.38` as the **Cached Pictures…** button on the Settings → Sources web picture source row, the tray **Cached Pictures** item, and `cached-pictures [--json] [--limit N]`: a read-only browser over `<working folder>/web_sources` that lists every cached picture newest first with file name, source (direct URL, `[feed] <feed URL>`, or orphan when the source was removed from the settings), date, and size, and can open a picture or its containing folder; it never deletes or prunes cache files.
- Configurable global shortcuts and manual Next while automatic switching is paused.

### 6. Presentation depth

- Configurable collage image count. Shipped in `0.2.34` as the **Pictures per collage** spinbox (2–6, default 5) on the Layout & Appearance collage section, saved per profile; the default 5 keeps the classic asymmetric mosaic exactly while 2, 3, 4, and 6 use deterministic grids that tile the whole panel.
- Richer pile size, spacing, overlap, rotation, and backdrop controls.
- Optional title, photographer, and date overlays.
- No-draw zones, one- and three-month calendar choices, and fade transitions.
- Selected-monitor-only rendering, monitor assignment shuffle, and orientation matching.

### 7. Administration and optional parity

- Settings import/export shipped in `0.2.20` as **Settings → Storage → Import / Export** (export every profile, folder, and per-profile option to a versioned JSON file; import validates first and applies after a confirmation). Reset to defaults shipped in `0.2.30` as **Reset to Defaults...** on the same page (plus `reset-defaults [--dry-run]` CLI): every profile is replaced by the factory default profile with every option at its default value, while the working-folder setting is kept and the rotation state is untouched.
- First-run guidance, integrated help, diagnostics, and cache controls.
- Proxy support, localization, and optional Cinnamon lock-screen integration.
- Provider-specific or sharing conveniences only when they have clear current value.

## Capabilities intentionally not copied

- JBS features removed from its current release are not parity targets.
- Generic website scraping is not supported; providers require a stable public or self-hosted API.
- Fill-crop and aspect-distorting stretch modes are no longer non-goals: the user-approved feature backlog (2026-10-30) requested them, and `0.2.15` shipped them as opt-in per-profile display fit modes. The default remains whole-picture fit with bars.
- Cloud accounts must never be required for the core local-library experience.
- Mint’s no-repeat pools and per-monitor source binding remain advantages even though JBS does not guarantee them.

## Release discipline

Each increment should be independently useful, tested, documented, committed, tagged, and installable. Avoid adding more wallpaper effects until the active UI work, reliability defects, and provider foundation are addressed.
