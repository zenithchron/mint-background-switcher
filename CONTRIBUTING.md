# Contributing

Thanks for helping improve Mint Background Switcher.

## Development setup

```bash
git clone https://github.com/zenithchron/mint-background-switcher.git
cd mint-background-switcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

On Linux Mint or Ubuntu, install desktop dependencies when testing settings/tray behavior:

```bash
sudo apt update
sudo apt install -y python3-pil python3-tk python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

## Before opening a pull request

Run:

```bash
git diff --check
python -m pytest -q
```

For changes that touch desktop startup, wallpaper application, Cinnamon settings, tray behavior, or rescue logic, also test the relevant command with temporary config/cache directories when practical:

```bash
MBS_CONFIG_DIR=/tmp/mbs-config MBS_CACHE_DIR=/tmp/mbs-cache \
  mint-background-switcher next --dry-run
```

## Design constraints

- Never crop wallpapers. Preserve the full source image and use the configured letterbox bars as needed.
- Keep dry-runs side-effect free.
- Avoid touching Cinnamon/Muffin/Nemo settings beyond the wallpaper keys needed for the requested action.
- Treat login autostart as safety-critical: startup should wait for Cinnamon readiness and should not immediately mutate desktop state.
- Keep optional GUI dependencies lazy so core CLI commands work on minimal/headless systems.

## Publishing a release

The `Publish GitHub Release` workflow publishes from an existing `vMAJOR.MINOR.PATCH` tag; it never creates or moves a tag. Before pushing the tag, update the package version and changelog, run the normal CI suite, and create an annotated tag on the reviewed commit.

On a matching tag push, the workflow verifies that the remotely peeled annotated tag still identifies the resolved commit, checks out that exact commit in a read-only build job, reruns the complete Xvfb suite, builds the wheel and source distribution, runs `twine check`, and fresh-installs both artifacts outside the checkout. That job creates a run-scoped bundle containing the exact artifacts, a commit-bound manifest, exact changelog-derived notes, SHA-256 hashes, byte sizes, and a checksum-pinned validation helper. A fresh write-enabled job never checks out, installs, or imports the tagged package or its dependencies; it preflights the artifact allowlist with isolated standard-library code, runs the pinned helper in isolated mode, independently fetches the tagged changelog, and checks the remote tag before touching a Release. Release operations use only the workflow's built-in `GITHUB_TOKEN`. Because GitHub denies that token when a target commit adds or modifies workflow files relative to the current default branch, every mutation path compares those Git trees first and fails before mutation if Workflows-write authorization would be required.

A push to `main` also checks the tag matching the current package version. A successful no-op requires both local and authoritative remote absence of that tag; lookup failures are errors. This path backfills a missing or repairable incomplete Release for an already-pushed tag and otherwise verifies the existing Release without republishing its assets. Maintainers can use the manual workflow input to repair another existing version tag. Asset publication is serialized per resolved tag, and each writer rechecks the current Release under that lock so branch, tag, and manual triggers cannot modify the same assets concurrently.

A complete existing Release is validated against its own embedded commit-bound manifest, the exact tagged changelog and notes bytes, its exact two-asset allowlist, API byte sizes, and downloaded hashes, so a later nondeterministic rebuild cannot churn stable published checksums. Creation and actual repair must instead match the independently validated bundle produced by the current run. Malformed API data, unsupported manifests, transport failures, and parser failures stop without authorizing repair; only well-formed semantic incompleteness can enter the repair path. The writer resolves drafts through a direct GraphQL tag lookup, retains the REST-created Release ID, and binds every read, delete, upload, transition, and readback to numeric Release and asset IDs rather than tag-based CLI commands or the eventually consistent REST list index. An ambiguous create response is reconciled with bounded direct lookups and is never followed by another create in the same run.

Creation starts as a non-Latest draft. Before repairing an existing final Release, one API update both clears Latest and moves it to draft; destructive asset replacement occurs only while hidden. Failures during draft mutation leave the Release hidden as a non-Latest draft. The workflow verifies the complete draft, rechecks the remote tag, and only then publishes it as a final Release with Latest disabled. An incomplete immutable Release, or a Release whose immutable field is absent or malformed, fails before mutation; an actually immutable incomplete Release requires a new version.

A separate globally serialized reconciliation derives versions from the complete remote peeled-tag inventory rather than the REST Release list. It resolves each candidate directly through GraphQL and numeric ID, fetches that candidate's exact tagged changelog and assets by ID, and accepts only a fully manifest-verified final Release. It also requires the just-published Release ID to remain complete and directly resolvable. Latest is updated and read back by numeric Release ID, with bounded stabilization retries. The highest complete eligible strict version therefore wins, and historical backfills cannot displace a newer verified final Release.

## Reporting bugs

Please include:

- Linux Mint/Cinnamon version.
- Python version.
- Monitor layout and scale settings.
- Command run and output.
- Relevant log file, especially `~/.cache/mint-background-switcher/startup.log` for startup issues.
