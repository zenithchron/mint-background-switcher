# Settings UI Redesign Implementation Plan

> Implement this plan one verified increment at a time, completing its review and release gates before starting the next increment.

**Goal:** Replace the accumulated feature-oriented Settings layout with an intuitive, profile-scoped workflow while preserving every existing wallpaper and safety behavior.

**Architecture:** Refactor only the Tk presentation and edit lifecycle around the existing `Config`, `Profile`, and callback methods. Keep rendering, persistence, update, collection, desktop, and service code unchanged unless a later increment explicitly changes an action contract. Ship each increment independently with focused unit/Tk tests, a 1024×768 Xvfb visual smoke, the full suite, documentation, and a patch-version release.

**Tech stack:** Python 3.10+, Tk/ttk, pytest, Xvfb, Pillow screenshot smoke.

---

## Success criteria / testable proof

- Users can always see which profile and layout they are editing.
- Navigation is organized around Sources, Layout & Appearance, and Rotation & Shortcuts rather than one top-level page per implementation mode.
- The visible layout controls and pending layout value cannot disagree after the unified Layout increment.
- Profile-scoped and application-scoped settings are clearly separated.
- No user must edit serialized path or monitor-assignment syntax.
- Unsaved edits cannot be silently lost through profile switching or closing.
- Black Screen remains immediately reachable and eventually becomes independent of unrelated pending edits.
- All controls remain reachable at 1024×768; normal desktops retain a roomy initial window.
- Existing config files, profiles, callbacks, source immutability, rendering output, updater behavior, and privacy state remain compatible.

## Increment 1: Persistent editing context and clearer actions — complete in `0.2.3`

**Objective:** Keep profile/layout context and saving available on every page without changing persistence or wallpaper behavior.

**Status:** Implemented for `0.2.3`. The 70-test Settings suite and 469-test full suite pass under Xvfb, and a 1024×768 smoke checks all 11 pages with the persistent context strip and complete footer mapped inside the window. Increment 2 followed in `0.2.4`.

**Files:**
- Modify: `mint_background_switcher/settings_ui.py`
- Modify: `tests/test_settings_ui.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `mint_background_switcher/__init__.py`
- Update status: `ROADMAP.md`

**Steps:**

1. Add an Xvfb-backed failing test that visits every existing notebook page and requires a persistent Profile selector, profile-management buttons, Layout selector, and Save Profile button to remain mapped and inside the window.
2. Add assertions that the profile strip is outside `general_tab`, that layout selection still updates `mode_var`, and that changing pages does not silently change the pending layout.
3. Move the existing profile row and mode selector into a profile-context frame above the notebook. Reflow the remaining General fields without changing their variables or callbacks.
4. Rename **Save** to **Save Profile** and **Apply Next Now** to **Save & Apply Now**. Update current user-facing guidance but do not rewrite historical changelog entries.
5. Run focused non-display tests, the Settings Xvfb suite, and a 1024×768 screenshot/geometry smoke.
6. Run the complete suite and package/version checks, independently review the diff, then commit, push, and verify the remote commit/tag.

## Increment 2: Unified Layout workspace — complete in `0.2.4`

**Objective:** Replace eight peer mode tabs with one Layout page whose selected controls and pending mode are always synchronized.

**Status:** Implemented for `0.2.4`. The 71-test Settings suite and 470-test full suite pass under Xvfb. A forced 944×668 client smoke covers all eight layout selections, descriptions, contextual Postcard, Polaroid, and per-monitor controls, profile-driven synchronization, complete footer visibility, and non-mutating navigation across the four Settings pages. Increment 3 is next.

**Files:**
- Modify: `mint_background_switcher/settings_ui.py`
- Modify: `tests/test_settings_ui.py`
- Modify: `README.md`, `CHANGELOG.md`, `ROADMAP.md`
- Bump package version surfaces.

**Steps:**

1. Add bidirectional synchronization tests for profile loading, layout selection, and visible option panels.
2. Create one Layout page with a plain-language layout chooser, description, and a single contextual options container.
3. Reuse the current Postcard, Polaroid, and per-monitor controls inside that container; show descriptive empty-state content for layouts without options.
4. Remove the old peer mode tabs and verify selecting a layout changes pending form state only until Save Profile or Save & Apply Now.
5. Run 1024×768, all-layout, Save/Apply, profile-switch, full-suite, and review gates.

## Increment 3: Task-based navigation and setting scope

**Objective:** Organize Settings into profile tasks and application tasks.

**Target navigation:**

- Profile: Sources; Layout & Appearance; Rotation & Shortcuts.
- Application: Public Collections; Storage; Updates & About.

**Steps:**

1. Add navigation-order, keyboard, scope-label, and control-presence tests.
2. Move existing widgets without changing callback/service behavior.
3. Clearly label the selected profile on collection actions and distinguish application-wide storage/update settings.
4. Verify all old controls remain reachable and update documentation.

## Increment 4: Structured source management

**Objective:** Replace editable multiline configuration syntax with safe, typed source rows.

**Steps:**

1. Introduce a source view model with type, location, scope, and availability while keeping the existing config schema compatible.
2. Add Folder, Add Picture, Remove, Reveal, and per-display assignment workflows.
3. Remove ordinary-user dependence on `MONITOR=/path;/path` text editing.
4. Test duplicate paths, unavailable volumes, invalid images, malformed legacy data, multi-monitor changes, and read-only source guarantees.

## Increment 5: Safe edit lifecycle and action semantics

**Objective:** Make pending edits visible and prevent accidental loss or unrelated persistence.

**Steps:**

1. Add deterministic dirty-state comparison for the loaded profile.
2. Add a visible unsaved indicator plus Revert.
3. Add save/discard/cancel prompts for profile switching and closing.
4. Separate emergency Black Screen from saving unrelated edits while preserving sticky privacy behavior.
5. Replace routine success dialogs with a persistent status area where safe; retain modal confirmation/errors where decisions are required.

## Increment 6: Responsive and accessible polish

**Objective:** Complete the redesign for small screens, keyboard use, and clear language.

**Steps:**

1. Replace implementation-oriented labels with task language and add concise help where needed.
2. Define tab order, mnemonics/shortcuts, focus behavior, and meaningful widget labels.
3. Wrap or elide long paths/status text without inflating requested window width.
4. Add representative 2560×1440, 1366×768, 1280×720, 1024×768, and multi-monitor seam smokes.
5. Capture and inspect final General/Sources/Layout/Application screenshots before release.

## End-of-increment update loop

For every completed increment:

1. Mark its status and evidence in `ROADMAP.md` and this plan.
2. Update current README instructions and the new changelog entry without editing historical release records.
3. Run `git diff --check`, focused tests, Xvfb visual/geometry checks, and the full suite.
4. Perform spec-compliance review followed by code-quality review; fix and rerun until both pass.
5. Synchronize version surfaces, build and install-test artifacts, commit, push, verify remote refs and CI, then publish the release when GitHub API/web authentication is available.
