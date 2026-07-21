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
