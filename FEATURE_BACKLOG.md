# MBS Feature Backlog (JBS-inspired, in delivery order)

The daily release job consumes this list **top to bottom**. Each day it takes
the first `PENDING` item, implements it (with Settings UI when user-facing),
tests it, bumps the version, publishes, and marks the item `DONE` with the
release tag and date. If the top item turns out to be infeasible in one run,
the job reports why and leaves it `PENDING` (or moves it to `BLOCKED`) rather
than skipping to a later item, unless the item is explicitly marked `SKIP`.

Order chosen by Paul (2026-10-30) from the JBS 6.1 gap analysis:
display-mode variety → lock/logon-screen → run-conditions → Never Show Again →
rebindable hotkeys → settings import/export → web sources → desktop overlays.

## Backlog

| # | Status | Feature (JBS reference) | Notes for the daily job |
|---|--------|--------------------------|--------------------------|
| 1 | DONE (v0.2.15, 2026-11-01) | **Display-mode variety** (JBS MODE-01..10) | Shipped as per-profile Display fit mode in Settings: fit with bars (default, historical), center, scale to fit, stretch, scale and crop (overscale), and scale and blur edges, applied to every fitted panel in Shared, Same, Per-monitor, Span, Montage, and Collage. Montage/collage per-cell modes were included in the same release. |
| 2 | DONE (v0.2.16, 2026-11-02) | **Lock / logon-screen mirror** (JBS OVR-07) | Shipped as per-profile **Mirror wallpaper to the lock screen** under Settings → Rotation & Shortcuts → Desktop integration. GNOME's per-user lock-screen image (`org.gnome.desktop.screensaver`) is written on every rotation including the black screen; Cinnamon already shows the desktop wallpaper on its lock screen (reported as automatic); other desktops report that the lock screen keeps its own image. A failed mirror never breaks the wallpaper path; the note is reported by Save & Apply Now, `next`, and the background loop. |
| 3 | PENDING | **Rich run-conditions** (JBS SW-07, SW-08, SW-09, SW-10, SW-11) | Add suppress-switching conditions: stop while a named process is running, stop on battery (laptop), stop over an active remote/VNC session, idle-only (require N seconds idle before a due switch), and stop while the session is locked/screensaver active. Each condition is an independent toggle in Settings. Must compose with the existing pause/black-screen behavior. |
| 4 | PENDING | **Never Show Again (exclusion list)** (JBS CTL-06) | Let the user exclude the currently displayed picture (and, for composites, an individual picked picture) from future rotation. Persist the exclusion list per profile. Provide a Settings view to see, remove individual exclusions, and clear the whole list. |
| 5 | PENDING | **Rebindable global hotkeys** (JBS CTL-15) | Extend the single black-screen hotkey into a small set of rebindable Cinnamon custom hotkeys: Next, Pause/Resume, and Black-screen. `register-hotkey` should accept an action + binding, and Settings should show the current bindings with the ability to change them. |
| 6 | PENDING | **Settings import / export** (JBS CFG-01) | Export the full config (all profiles, folders, per-mode settings) to a file and import a previous export. Imported values apply immediately; Cancel reverts. Provide Settings buttons for both, plus a CLI `export`/`import` for automation. |
| 7 | PENDING | **Web / cloud picture sources** (JBS SRC-03..14) | The largest gap. Add at least one non-local source as a proof of the source-plugin architecture, then expand. Prefer a keyless, low-friction source first (e.g. Pexels or Pixabay public search, or a direct-image-URL / RSS feed). Design a source interface so more providers can be added later. This item may span multiple daily releases — implement incrementally, one provider per release, and keep the source interface stable. |
| 8 | PENDING | **Desktop overlays** (JBS OVR-01..05) | Draw optional overlays on top of the wallpaper: picture title/photographer metadata, picture date, and no-draw zones (blank regions in px, per-monitor or all). Calendar overlay is a sub-item. Overlays must be renderable at physical panel resolution (fractional-scale aware) and composable with the existing fit modes. |

## Blocked / skipped

(none yet)

## Done

(none yet — this backlog was created 2026-10-30; the first daily run after this
date takes item 1)
