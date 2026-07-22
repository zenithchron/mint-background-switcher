# Security Policy

## Supported versions

The latest release receives security fixes.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. If private vulnerability reporting is not available, open a public issue that requests a private reporting path, but do not include vulnerability details, secrets, private image paths, or exploit steps in the public issue.

For desktop-session safety issues, include:

- Linux Mint/Cinnamon version.
- Whether the issue happened during manual use or login autostart.
- The contents of `~/.cache/mint-background-switcher/startup.log`, after removing any private paths you do not want to share.
- Recovery steps that worked.

## Scope

Mint Background Switcher is a local desktop utility. It does not intentionally transmit images, file paths, or configuration data to network services.

The updater's release-check and source-download layer contacts only the public GitHub API and GitHub/codeload download hosts for this repository. It resolves a stable semantic-version tag to a commit, downloads that commit's source archive over HTTPS, validates archive paths and package versions, rechecks the tag before activation, and records the downloaded archive's SHA-256 digest. The digest detects local corruption but is not an independent signature because the archive and tag come from the same trusted GitHub repository.

After the user confirms installation, the updater creates a Python virtual environment and invokes `pip`. Depending on the local pip cache and environment, pip may contact the user's configured Python package index to obtain declared build requirements and runtime dependencies such as setuptools, wheel, Pillow, and (on Python 3.10) tomli. That dependency traffic is governed by pip's own index, proxy, certificate, and trusted-host configuration; it is not restricted by the updater's GitHub host allowlist.

The updater trusts the operating system, Python packaging tools, HTTPS certificate validation, GitHub, this repository's release tags, and package dependencies installed by pip. A compromised local user account, root account, GitHub account/repository, Python package index, or operating system is outside its threat model. Updates are never installed silently, never invoke `sudo`, and never modify system-package-managed files.

## Working-folder boundary

Wallpaper source folders are read-only inputs. MBS stores generated wallpapers, its SQLite image index, and database-backed no-repeat pools in its working folder; it does not place thumbnails, resized copies, or metadata in source folders. A custom working folder must be empty or contain MBS's ownership marker, must not overlap a configured source folder or the current working folder, and must pass directory, symbolic-link, availability, and writability checks. The marker prevents accidental adoption and cleanup of unrelated directories; it is not a security boundary against the same local user or root.

Working-folder migration copies only recognized generated PNG and index filenames, verifies copied content, rejects destination collisions, switches configuration only after verified installation, and retains the old files. If an activated custom volume is unavailable, generation fails explicitly instead of silently falling back to the default cache. Configuration, runtime state, logs, managed installations, launchers, autostart entries, hotkeys, and source images remain outside the selected working folder.
