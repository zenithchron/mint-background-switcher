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
| 3 | DONE (v0.2.17, 2026-11-03) | **Rich run-conditions** (JBS SW-07, SW-08, SW-09, SW-10, SW-11) | Shipped as five per-profile toggles on a new Settings → Conditions page: pause while a named process is running (≤15 chars, exact comm match), on battery, during a remote/VNC session, idle-only (N seconds via xprintidle), and while locked/screensaver active (D-Bus). Conditions pause the scheduled loop only (manual/Save & Apply switches always apply; dry runs ignore them), retry on a ≤60 s cadence while held, compose with pause/black-screen/night-schedule, and fail open when undetectable. |
| 4 | DONE (v0.2.18, 2026-11-05) | **Never Show Again (exclusion list)** (JBS CTL-06) | Shipped as a per-profile exclusion list on a new Settings → Never Show Again page: one-click **Never Show Again (current wallpaper)** (excludes every source picture of the applied wallpaper), Remove Selected / Clear All for the list, and a **Never Show Again** button plus `[excluded]` markers in the Current Pictures dialog. Exclusions persist per profile (capped at 1000 entries), are skipped on every rotation path with normal wrap-around of the remaining pool, and a fully excluded pool falls back to the existing safe black screen. |
| 5 | DONE (v0.2.19, 2026-11-06) | **Rebindable global hotkeys** (JBS CTL-15) | Shipped as three per-profile rebindable Cinnamon custom hotkeys — Next (`<Primary><Alt>n`), Pause/Resume (`<Primary><Alt>p`), and Black screen (historic `<Primary><Alt>b`) — with a **Shortcuts** section on Settings → Rotation & Shortcuts (editable bindings + **Register hotkeys** button with success/error feedback), CLI `register-hotkey --action next\|pause-resume\|black-screen` / `--all` / `--dry-run` (default stays black-screen, the historic behavior), and a new `pause-toggle` command. The managed updater rebinds every registered hotkey to the stable launcher after updates. |
| 6 | DONE (v0.2.20, 2026-11-07) | **Settings import / export** (JBS CFG-01) | Shipped as **Settings → Storage → Import / Export** with **Export Settings...** / **Import Settings...** buttons: export writes every profile, folder, and per-profile option to a versioned JSON document; import validates the file first, confirms the full replacement, and applies it immediately (cancel leaves everything unchanged). CLI `export [DESTINATION]` (file or stdout) and `import SOURCE [--dry-run]` cover automation; invalid imports fail without touching the settings. |
| 7 | PENDING | **Web / cloud picture sources** (JBS SRC-03..14) | The largest gap. Add at least one non-local source as a proof of the source-plugin architecture, then expand. Prefer a keyless, low-friction source first (e.g. Pexels or Pixabay public search, or a direct-image-URL / RSS feed). Design a source interface so more providers can be added later. This item may span multiple daily releases — implement incrementally, one provider per release, and keep the source interface stable. |
| 8 | PENDING | **Desktop overlays** (JBS OVR-01..05) | Draw optional overlays on top of the wallpaper: picture title/photographer metadata, picture date, and no-draw zones (blank regions in px, per-monitor or all). Calendar overlay is a sub-item. Overlays must be renderable at physical panel resolution (fractional-scale aware) and composable with the existing fit modes. |

## Blocked / skipped

(none yet)

## Done

(none yet — this backlog was created 2026-10-30; the first daily run after this
date takes item 1)
