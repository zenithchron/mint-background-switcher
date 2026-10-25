# Mint Background Switcher Roadmap

This roadmap turns the John’s Background Switcher 6.1 parity audit into an implementation order for Mint Background Switcher. It is ordered by user value and dependency, not by raw feature count.

## Product principles

- Local-first and usable without an account or cloud service.
- Keep every foreground picture visible: no fill-cropping or distortion.
- Preserve deterministic per-monitor source assignment and database-backed no-repeat rotation.
- Treat source folders and files as read-only.
- Keep privacy mode, recovery, state writes, updates, and downloads fail-safe.
- Make ordinary workflows discoverable in Settings before adding more CLI-only controls.
- Prefer a shared provider/cache/provenance architecture over one-off integrations.

## Implementation order

### 1. Settings UI redesign — active

Before `0.2.3`, the Settings window exposed most features through navigation that reflected implementation history rather than user tasks: Profile context and Save were limited to General, while the selected layout was separate from the layout tab being viewed. Increment 1 made Profile, Layout, and Save persistent; Increment 2 replaced the eight peer layout tabs with one synchronized Layout workspace; Increment 3 grouped the remaining controls into profile tasks and application tasks.

**Status:** Increments 1–3 are complete in `0.2.3` through `0.2.5`; Increment 4 is next.

Implement the redesign in small, testable increments:

1. **Persistent editing context and clearer actions — complete in `0.2.3`** — Profile, profile management, Layout, and Save Profile now remain above the page tabs; Apply Next Now is now Save & Apply Now. Existing behavior and all 11 pages are preserved.
2. **Unified Layout workspace — complete in `0.2.4`** — the eight peer layout tabs are now one Layout page. Selecting a layout opens its plain-language description and the relevant Postcard, Polaroid, or per-monitor controls, so the visible workspace and pending selection cannot disagree.
3. **Task-based navigation — complete in `0.2.5`** — profile controls now live under Sources, Layout & Appearance, and Rotation & Shortcuts; application controls live under Public Collections, Storage, and Updates & About. Scope labels name the selected profile or shared application scope, and keyboard traversal covers all six pages.
4. **Structured source management — next** — replace editable path syntax with rows showing source type, location, scope, and availability, plus explicit Add, Remove, and Reveal actions.
5. **Safe edit lifecycle** — add a dirty indicator, Revert, and save/discard/cancel protection when switching profiles or closing. Make emergency Black Screen independent of unrelated pending edits.
6. **Responsive and accessible polish** — improve labels, keyboard traversal, focus, nonmodal status feedback, screen-reader meaning, and 1024×768 behavior.

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
- Orientation matching, ignored folders, path exclusions, and temporary-unavailability handling. Minimum dimensions (smallest side) shipped in `0.2.6` and hidden files/folders (dot names) shipped in `0.2.7` as per-profile Settings filters; optional folder-order rotation shipped in `0.2.8` as a per-profile rotation mode.
- Broader intervals, switch at startup, startup delay, and topology-change refresh.
- Optional suppression while locked, on battery, not idle, or while selected applications are running.
- Optional post-switch command hook.

### 5. History and current-wallpaper actions

- Never Show Again exclusions, including one image in a composite.
- Previous and redraw-current actions.
- Shuffle current monitor assignments and clear background.
- Browse recent cached pictures and navigate to their original sources.
- Configurable global shortcuts and manual Next while automatic switching is paused.

### 6. Presentation depth

- Configurable collage image count.
- Richer pile size, spacing, overlap, rotation, and backdrop controls.
- Optional title, photographer, and date overlays.
- No-draw zones, one- and three-month calendar choices, and fade transitions.
- Selected-monitor-only rendering, monitor assignment shuffle, and orientation matching.

### 7. Administration and optional parity

- Settings import/export and reset to defaults.
- First-run guidance, integrated help, diagnostics, and cache controls.
- Proxy support, localization, and optional Cinnamon lock-screen integration.
- Provider-specific or sharing conveniences only when they have clear current value.

## Capabilities intentionally not copied

- JBS features removed from its current release are not parity targets.
- Generic website scraping is not supported; providers require a stable public or self-hosted API.
- Fill-crop and aspect-distorting stretch modes conflict with the whole-image design and remain non-goals unless that product decision changes.
- Cloud accounts must never be required for the core local-library experience.
- Mint’s no-repeat pools and per-monitor source binding remain advantages even though JBS does not guarantee them.

## Release discipline

Each increment should be independently useful, tested, documented, committed, tagged, and installable. Avoid adding more wallpaper effects until the active UI work, reliability defects, and provider foundation are addressed.
