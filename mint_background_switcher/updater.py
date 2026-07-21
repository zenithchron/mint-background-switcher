"""User-triggered managed updates for Mint Background Switcher."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job.
    import tomli as tomllib  # type: ignore[import-not-found]
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Protocol
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux Mint provides fcntl.
    fcntl = None  # type: ignore[assignment]

from . import APP_ID
from .autostart import AUTOSTART_MARKERS, disable_autostart, enable_autostart
from .hotkeys import CUSTOM_PATH, _existing_custom_list, register_cinnamon_black_hotkey, shell_command
from .paths import autostart_file
from .storage import atomic_write_json_unlocked

REPOSITORY = "zenithchron/mint-background-switcher"
GITHUB_API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
GITHUB_ARCHIVE_ROOT = f"https://github.com/{REPOSITORY}/archive"
NETWORK_TIMEOUT_SECONDS = 30
MAX_JSON_BYTES = 1_000_000
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_UNPACKED_BYTES = 150 * 1024 * 1024
RECEIPT_NAME = "install-receipt.json"
UPDATE_LOCK_NAME = "update.lock"
TRUSTED_DOWNLOAD_HOSTS = {"github.com", "codeload.github.com"}
_VERSION_RE = re.compile(r"^(\d{1,9})\.(\d{1,9})\.(\d{1,9})$")
_TAG_RE = re.compile(r"^v(\d{1,9})\.(\d{1,9})\.(\d{1,9})$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """A safe, user-facing update failure."""


class UpdateBusyError(UpdateError):
    """Another update or rollback currently owns the update lock."""


class ReleaseClient(Protocol):
    def download_release(self, release: "ReleaseInfo", destination: Path) -> str: ...

    def resolve_tag_commit(self, tag: str) -> str: ...


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    commit_sha: str
    archive_url: str


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str
    latest: ReleaseInfo

    @property
    def update_available(self) -> bool:
        return version_key(self.latest.version) > version_key(self.current_version)


@dataclass(frozen=True)
class ArchiveMetadata:
    project_name: str
    version: str
    root_name: str


@dataclass(frozen=True)
class InstallRecord:
    version: str
    commit_sha: str
    archive_sha256: str
    installed_at: str
    path: Path


@dataclass(frozen=True)
class InstallResult:
    record: InstallRecord
    previous: InstallRecord | None
    launcher: Path
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutostartPreference:
    enabled: bool
    tray: bool = False
    delay_seconds: int = 20


@dataclass(frozen=True)
class _FileSnapshot:
    path: Path
    content: bytes
    mode: int


def version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(str(version))
    if not match or any(len(part) > 1 and part.startswith("0") for part in match.groups()):
        raise ValueError(f"Invalid release version: {version!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_from_tag(tag: str) -> str:
    match = _TAG_RE.fullmatch(str(tag))
    if not match or any(len(part) > 1 and part.startswith("0") for part in match.groups()):
        raise ValueError(f"Invalid release tag: {tag!r}")
    return ".".join(match.groups())


def _validated_sha(value: object, *, label: str = "commit SHA") -> str:
    text = str(value).lower()
    if not _SHA_RE.fullmatch(text):
        raise UpdateError(f"GitHub returned an invalid {label}.")
    return text


def archive_url_for_commit(commit_sha: str) -> str:
    commit = _validated_sha(commit_sha)
    return f"{GITHUB_ARCHIVE_ROOT}/{commit}.tar.gz"


def managed_install_root() -> Path:
    override = os.environ.get("MBS_INSTALL_ROOT")
    if override:
        return Path(override).expanduser().absolute()
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")).expanduser()
    return (data_home / APP_ID).absolute()


def managed_launcher() -> Path:
    override = os.environ.get("MBS_USER_BIN_DIR")
    bin_dir = Path(override).expanduser() if override else Path.home() / ".local" / "bin"
    return bin_dir.absolute() / APP_ID


def _versions_dir() -> Path:
    return managed_install_root() / "versions"


def _current_link() -> Path:
    return managed_install_root() / "current"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class GitHubClient:
    """Minimal public GitHub API client for tagged source releases."""

    def __init__(self, *, opener: Callable[..., Any] | None = None) -> None:
        self._opener = opener or urlopen

    def _get_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{APP_ID}-updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != "api.github.com":
                    raise UpdateError("GitHub API redirected to an untrusted host.")
                declared = response.headers.get("Content-Length")
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise UpdateError("GitHub returned an invalid response size.") from exc
                    if declared_size < 0 or declared_size > MAX_JSON_BYTES:
                        raise UpdateError("GitHub returned an unexpectedly large response.")
                payload = response.read(MAX_JSON_BYTES + 1)
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f"Could not contact GitHub: {exc}") from exc
        if len(payload) > MAX_JSON_BYTES:
            raise UpdateError("GitHub returned an unexpectedly large response.")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub returned malformed update information.") from exc

    def resolve_tag_commit(self, tag: str) -> str:
        version_from_tag(tag)
        data = self._get_json(f"{GITHUB_API_ROOT}/git/ref/tags/{quote(tag, safe='')}")
        try:
            obj = data["object"]
        except (KeyError, TypeError) as exc:
            raise UpdateError("GitHub returned malformed tag information.") from exc
        for _depth in range(4):
            object_type = obj.get("type") if isinstance(obj, dict) else None
            sha = _validated_sha(obj.get("sha") if isinstance(obj, dict) else "", label="tag object SHA")
            if object_type == "commit":
                return sha
            if object_type != "tag":
                raise UpdateError(f"Release tag points to unsupported Git object type: {object_type!r}.")
            tag_data = self._get_json(f"{GITHUB_API_ROOT}/git/tags/{sha}")
            obj = tag_data.get("object") if isinstance(tag_data, dict) else None
        raise UpdateError("Release tag nesting is unexpectedly deep.")

    def latest_release(self) -> ReleaseInfo:
        data = self._get_json(f"{GITHUB_API_ROOT}/tags?per_page=100")
        if not isinstance(data, list):
            raise UpdateError("GitHub returned malformed tag information.")
        candidates: list[tuple[tuple[int, int, int], str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            tag = item.get("name")
            if not isinstance(tag, str):
                continue
            try:
                version = version_from_tag(tag)
            except ValueError:
                continue
            candidates.append((version_key(version), version, tag))
        if not candidates:
            raise UpdateError("No stable Mint Background Switcher release tags were found.")
        _key, version, tag = max(candidates)
        commit = self.resolve_tag_commit(tag)
        return ReleaseInfo(version, tag, commit, archive_url_for_commit(commit))

    def download_release(self, release: ReleaseInfo, destination: Path) -> str:
        expected_url = archive_url_for_commit(release.commit_sha)
        request = Request(expected_url, headers={"User-Agent": f"{APP_ID}-updater"})
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in TRUSTED_DOWNLOAD_HOSTS:
                    raise UpdateError("GitHub redirected the update to an untrusted download host.")
                declared_raw = response.headers.get("Content-Length")
                if declared_raw:
                    try:
                        declared = int(declared_raw)
                    except ValueError as exc:
                        raise UpdateError("GitHub returned an invalid download size.") from exc
                    if declared < 0 or declared > MAX_ARCHIVE_BYTES:
                        raise UpdateError("The update archive is unexpectedly large.")
                digest = hashlib.sha256()
                total = 0
                with destination.open("xb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_ARCHIVE_BYTES:
                            raise UpdateError("The update archive is unexpectedly large.")
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except UpdateError:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise
        except Exception as exc:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise UpdateError(f"Could not download the update: {exc}") from exc
        if total == 0:
            destination.unlink(missing_ok=True)
            raise UpdateError("GitHub returned an empty update archive.")
        return digest.hexdigest()


def check_for_updates(current_version: str, *, client: GitHubClient | None = None) -> UpdateCheck:
    version_key(current_version)
    latest = (client or GitHubClient()).latest_release()
    return UpdateCheck(current_version=current_version, latest=latest)


def _safe_archive_name(name: str) -> PurePosixPath:
    if not name or "\x00" in name:
        raise UpdateError("The release contains an unsafe archive path.")
    if name.startswith("/"):
        raise UpdateError(f"The release contains an unsafe archive path: {name!r}.")
    normalized_name = name[:-1] if name.endswith("/") else name
    parts = normalized_name.split("/")
    if not normalized_name or any(part in ("", ".", "..") for part in parts):
        raise UpdateError(f"The release contains an unsafe archive path: {name!r}.")
    path = PurePosixPath(*parts)
    return path


def _read_tar_member(archive: tarfile.TarFile, member: tarfile.TarInfo, *, limit: int = 1_000_000) -> bytes:
    if member.size < 0 or member.size > limit:
        raise UpdateError(f"Release metadata file is unexpectedly large: {member.name!r}.")
    handle = archive.extractfile(member)
    if handle is None:
        raise UpdateError(f"Could not read release metadata file: {member.name!r}.")
    payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise UpdateError(f"Release metadata file is unexpectedly large: {member.name!r}.")
    return payload


def validate_release_archive(path: str | Path, expected_version: str) -> ArchiveMetadata:
    version_key(expected_version)
    archive_path = Path(path)
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise UpdateError("The downloaded update is not a valid gzip tar archive.") from exc
    with archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise UpdateError("The release contains an unexpected number of files.")
        roots: set[str] = set()
        seen: set[str] = set()
        unpacked = 0
        member_by_name: dict[str, tarfile.TarInfo] = {}
        for member in members:
            if member.name.endswith("/") and not member.isdir():
                raise UpdateError(f"The release contains an unsafe archive path: {member.name!r}.")
            safe_path = _safe_archive_name(member.name)
            roots.add(safe_path.parts[0])
            normalized_name = safe_path.as_posix()
            if normalized_name in seen:
                raise UpdateError(f"The release contains a duplicate archive member: {member.name!r}.")
            seen.add(normalized_name)
            if not (member.isdir() or member.isfile()):
                raise UpdateError(f"The release contains an unsupported archive member: {member.name!r}.")
            if member.isfile():
                if member.size < 0:
                    raise UpdateError(f"The release contains an invalid archive member size: {member.name!r}.")
                unpacked += member.size
                if unpacked > MAX_ARCHIVE_UNPACKED_BYTES:
                    raise UpdateError("The release expands to an unexpectedly large size.")
            member_by_name[normalized_name] = member
        if len(roots) != 1:
            raise UpdateError("The release archive must contain exactly one top-level directory.")
        root = next(iter(roots))
        pyproject_name = f"{root}/pyproject.toml"
        init_name = f"{root}/mint_background_switcher/__init__.py"
        pyproject_member = member_by_name.get(pyproject_name)
        init_member = member_by_name.get(init_name)
        if pyproject_member is None or init_member is None or not pyproject_member.isfile() or not init_member.isfile():
            raise UpdateError("The release archive is missing required package metadata.")
        try:
            project = tomllib.loads(_read_tar_member(archive, pyproject_member).decode("utf-8"))["project"]
            project_name = str(project["name"])
            project_version = str(project["version"])
            init_text = _read_tar_member(archive, init_member).decode("utf-8")
        except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
            raise UpdateError("The release contains malformed package metadata.") from exc
        init_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', init_text, re.MULTILINE)
        if project_name != APP_ID:
            raise UpdateError(f"The release package name is unexpected: {project_name!r}.")
        if project_version != expected_version or init_match is None or init_match.group(1) != expected_version:
            raise UpdateError(
                f"The release version does not match {expected_version}: metadata={project_version!r}, runtime={init_match.group(1) if init_match else None!r}."
            )
        return ArchiveMetadata(project_name, expected_version, root)


def _receipt_data(record: InstallRecord) -> dict[str, str]:
    return {
        "version": record.version,
        "commit_sha": record.commit_sha,
        "archive_sha256": record.archive_sha256,
        "installed_at": record.installed_at,
    }


def _load_install_record(path: Path) -> InstallRecord | None:
    receipt = path / RECEIPT_NAME
    executable = path / "venv" / "bin" / APP_ID
    if path.is_symlink() or not path.is_dir() or not receipt.is_file() or not executable.is_file():
        return None
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
        version = str(data["version"])
        commit = str(data["commit_sha"])
        archive_digest = str(data["archive_sha256"])
        installed_at = str(data["installed_at"])
        version_key(version)
        _validated_sha(commit)
        if not _SHA256_RE.fullmatch(archive_digest):
            return None
        datetime.fromisoformat(installed_at.replace("Z", "+00:00"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, UpdateError):
        return None
    return InstallRecord(version, commit, archive_digest, installed_at, path)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def active_install() -> InstallRecord | None:
    current = _current_link()
    if not current.is_symlink():
        return None
    try:
        resolved = current.resolve(strict=True)
        versions = _versions_dir().resolve(strict=True)
    except OSError:
        return None
    if not _path_is_within(resolved, versions):
        return None
    return _load_install_record(resolved)


def _install_records() -> list[InstallRecord]:
    versions = _versions_dir()
    if not versions.is_dir() or versions.is_symlink():
        return []
    records = [record for path in versions.iterdir() if not path.name.startswith(".") if (record := _load_install_record(path))]
    return sorted(records, key=lambda record: (record.installed_at, version_key(record.version)), reverse=True)


def rollback_candidate() -> InstallRecord | None:
    active = active_install()
    if active is None:
        return None
    active_key = version_key(active.version)
    candidates = [
        record
        for record in _install_records()
        if record.path != active.path and version_key(record.version) < active_key
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda record: (version_key(record.version), record.installed_at))


def is_managed_runtime() -> bool:
    active = active_install()
    if active is None:
        return False
    try:
        executable = Path(sys.executable).resolve(strict=True)
        venv = (active.path / "venv").resolve(strict=True)
    except OSError:
        return False
    return _path_is_within(executable, venv)


def _known_autostart_entries() -> list[Path]:
    primary = autostart_file()
    candidates = [primary]
    if primary.parent.is_dir():
        candidates.extend(path for path in primary.parent.glob("*.desktop") if path != primary)
    result: list[Path] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(marker in text for marker in AUTOSTART_MARKERS):
            result.append(path)
    return result


def read_autostart_preference() -> AutostartPreference:
    entries = _known_autostart_entries()
    if not entries:
        return AutostartPreference(False)
    primary = autostart_file()
    selected = primary if primary in entries else entries[0]
    try:
        text = selected.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return AutostartPreference(False)
    if re.search(r"^X-GNOME-Autostart-enabled\s*=\s*false\s*$", text, re.IGNORECASE | re.MULTILINE):
        return AutostartPreference(False)
    exec_match = re.search(r"^Exec=(.*)$", text, re.MULTILINE)
    exec_line = exec_match.group(1) if exec_match else ""
    tray = bool(re.search(r"(?:^|\s)tray(?:\s|$)", exec_line))
    delay_match = re.search(r"^X-GNOME-Autostart-Delay\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    delay = int(delay_match.group(1)) if delay_match else 20
    return AutostartPreference(True, tray=tray, delay_seconds=max(0, delay))


def _snapshot_autostart_entries() -> list[_FileSnapshot]:
    snapshots: list[_FileSnapshot] = []
    for path in _known_autostart_entries():
        try:
            snapshots.append(_FileSnapshot(path, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
        except OSError:
            continue
    return snapshots


def _restore_autostart_entries(snapshots: list[_FileSnapshot]) -> None:
    disable_autostart()
    for snapshot in snapshots:
        snapshot.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot.path.write_bytes(snapshot.content)
        snapshot.path.chmod(snapshot.mode)


def black_hotkey_registered() -> bool:
    try:
        return CUSTOM_PATH in _existing_custom_list()
    except Exception:
        return False


def _atomic_symlink(target: str | Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        os.symlink(str(target), temporary)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _restore_symlink(path: Path, previous_target: str | None) -> None:
    if previous_target is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_symlink(previous_target, path)


def _base_python() -> str:
    override = os.environ.get("MBS_UPDATE_PYTHON")
    if override:
        return str(Path(override).expanduser())
    base = getattr(sys, "_base_executable", None)
    return str(base or sys.executable)


def _clean_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env.update({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
    return env


def _run_checked(argv: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"Update command timed out: {Path(argv[0]).name}.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "command failed").strip()[-2000:]
        raise UpdateError(f"Update command failed: {detail}") from exc
    except OSError as exc:
        raise UpdateError(f"Could not start update command {Path(argv[0]).name}: {exc}") from exc


def _install_payload(archive: Path, staging: Path, version: str) -> None:
    venv = staging / "venv"
    _run_checked([_base_python(), "-m", "venv", "--system-site-packages", str(venv)])
    python = venv / "bin" / "python"
    _run_checked([str(python), "-m", "pip", "install", "--upgrade", str(archive)])
    probe = _run_checked(
        [
            str(python),
            "-I",
            "-c",
            (
                "from pathlib import Path; import mint_background_switcher as m; "
                "print(m.__version__); print(Path(m.__file__).resolve())"
            ),
        ],
        timeout=60,
    )
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if len(lines) != 2 or lines[0] != version:
        raise UpdateError("The managed installation reported the wrong version.")
    module_path = Path(lines[1])
    if not _path_is_within(module_path, venv.resolve()):
        raise UpdateError("The managed installation imported code from outside its versioned environment.")
    _run_checked([str(python), "-I", "-c", "import tkinter; import PIL"], timeout=60)


def _probe_installed_version(executable: Path) -> str:
    result = _run_checked([str(executable), "--version"], timeout=60)
    prefix = f"{APP_ID} "
    value = result.stdout.strip()
    if not value.startswith(prefix):
        raise UpdateError("The managed launcher returned unexpected version output.")
    version = value[len(prefix) :]
    version_key(version)
    return version


def _probe_tray_runtime(staging: Path) -> None:
    python = staging / "venv" / "bin" / "python"
    _run_checked(
        [
            str(python),
            "-I",
            "-c",
            "from mint_background_switcher.tray import _load_gtk; _load_gtk()",
        ],
        timeout=60,
    )


def _record_for_release(release: ReleaseInfo) -> InstallRecord | None:
    for record in _install_records():
        if record.version == release.version and record.commit_sha == release.commit_sha:
            try:
                if _probe_installed_version(record.path / "venv" / "bin" / APP_ID) == release.version:
                    return record
            except (OSError, UpdateError):
                continue
    return None


def _new_version_path(versions: Path, release: ReleaseInfo) -> Path:
    base_name = f"{release.version}-{release.commit_sha[:12]}"
    for name in (base_name, f"{base_name}-repair-{uuid.uuid4().hex[:8]}"):
        candidate = versions / name
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return candidate
    raise UpdateError("Could not reserve a versioned installation directory.")


@contextmanager
def _update_lock() -> Iterator[None]:
    root = managed_install_root()
    if root.is_symlink():
        raise UpdateError("Managed install root must not be a symbolic link.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    lock_path = root / UPDATE_LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UpdateBusyError("Another update or rollback is already running.") from exc
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _activate_record(
    record: InstallRecord,
    *,
    autostart_preference: AutostartPreference,
    hotkey_was_registered: bool,
) -> tuple[Path, tuple[str, ...]]:
    current = _current_link()
    launcher = managed_launcher()
    root = managed_install_root()
    if os.path.lexists(current) and not current.is_symlink():
        raise UpdateError("Managed current path is not a symbolic link; refusing to replace it.")
    previous_current = os.readlink(current) if current.is_symlink() else None
    desired_launcher_target = root / "current" / "venv" / "bin" / APP_ID
    backup_launcher: Path | None = None
    launcher_already_managed = launcher.is_symlink() and os.readlink(launcher) == str(desired_launcher_target)
    snapshots = _snapshot_autostart_entries()
    warnings: list[str] = []
    try:
        relative_record = os.path.relpath(record.path, root)
        _atomic_symlink(relative_record, current)
        if not launcher_already_managed:
            if os.path.lexists(launcher):
                backup_launcher = launcher.with_name(f"{launcher.name}.pre-managed-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
                os.replace(launcher, backup_launcher)
            _atomic_symlink(desired_launcher_target, launcher)
        if autostart_preference.enabled:
            disable_autostart()
            command = [str(launcher), "tray" if autostart_preference.tray else "safe-start"]
            enable_autostart(command, delay_seconds=autostart_preference.delay_seconds)
    except Exception:
        try:
            _restore_autostart_entries(snapshots)
        finally:
            if not launcher_already_managed:
                try:
                    launcher.unlink()
                except FileNotFoundError:
                    pass
                if backup_launcher is not None and backup_launcher.exists():
                    os.replace(backup_launcher, launcher)
            _restore_symlink(current, previous_current)
        raise
    if hotkey_was_registered:
        try:
            register_cinnamon_black_hotkey(command=shell_command([str(launcher), "black-screen"]))
        except Exception as exc:
            warnings.append(f"Updated the application, but could not rebind the black-screen hotkey: {exc}")
    return launcher, tuple(warnings)


def install_release(release: ReleaseInfo, *, client: ReleaseClient | None = None) -> InstallResult:
    version_key(release.version)
    if release.tag != f"v{release.version}":
        raise UpdateError("Release tag and version do not match.")
    _validated_sha(release.commit_sha)
    client = client or GitHubClient()
    with _update_lock():
        previous = active_install()
        if previous is not None:
            previous_key = version_key(previous.version)
            release_key = version_key(release.version)
            if release_key < previous_key:
                raise UpdateError(
                    f"Refusing to install older version {release.version} over {previous.version}. "
                    "Use Roll Back for an intentional downgrade."
                )
            if release_key == previous_key and release.commit_sha != previous.commit_sha:
                raise UpdateError(
                    f"Version {release.version} was previously installed from a different commit; "
                    "refusing a rewritten release tag."
                )
        known_records = _install_records()
        if previous is not None:
            known_records.append(previous)
        if any(
            record.version == release.version and record.commit_sha != release.commit_sha
            for record in known_records
        ):
            raise UpdateError(
                f"Version {release.version} was previously installed from a different commit; "
                "refusing a rewritten release tag."
            )
        preference = read_autostart_preference()
        hotkey_was_registered = black_hotkey_registered()
        existing = _record_for_release(release)
        if existing is not None:
            if client.resolve_tag_commit(release.tag) != release.commit_sha:
                raise UpdateError("The release tag moved before the existing installation could be activated.")
            launcher, warnings = _activate_record(
                existing,
                autostart_preference=preference,
                hotkey_was_registered=hotkey_was_registered,
            )
            return InstallResult(existing, previous, launcher, warnings)

        versions = _versions_dir()
        if versions.is_symlink():
            raise UpdateError("Managed versions path must not be a symbolic link.")
        versions.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidate: Path | None = None
        completed = False
        with tempfile.TemporaryDirectory(prefix=f"{APP_ID}-download-") as download_dir:
            archive = Path(download_dir) / f"{release.tag}.tar.gz"
            digest = client.download_release(release, archive)
            if not _SHA256_RE.fullmatch(digest) or sha256_file(archive) != digest:
                raise UpdateError("The downloaded update changed during local verification.")
            validate_release_archive(archive, release.version)
            resolved = client.resolve_tag_commit(release.tag)
            if resolved != release.commit_sha:
                raise UpdateError("The release tag moved while the update was downloading; no changes were activated.")
            candidate = _new_version_path(versions, release)
            try:
                _install_payload(archive, candidate, release.version)
                executable = candidate / "venv" / "bin" / APP_ID
                if _probe_installed_version(executable) != release.version:
                    raise UpdateError("The managed launcher reported the wrong version.")
                if preference.enabled and preference.tray:
                    _probe_tray_runtime(candidate)
                installed_at = datetime.now(timezone.utc).isoformat()
                record = InstallRecord(release.version, release.commit_sha, digest, installed_at, candidate)
                atomic_write_json_unlocked(candidate / RECEIPT_NAME, _receipt_data(record))
                completed = True
            finally:
                if not completed and candidate is not None and candidate.exists():
                    shutil.rmtree(candidate)
        if client.resolve_tag_commit(release.tag) != release.commit_sha:
            raise UpdateError("The release tag moved before the new installation could be activated.")
        launcher, warnings = _activate_record(
            record,
            autostart_preference=preference,
            hotkey_was_registered=hotkey_was_registered,
        )
        return InstallResult(record, previous, launcher, warnings)


def rollback_install() -> InstallResult:
    with _update_lock():
        current = active_install()
        candidate = rollback_candidate()
        if current is None or candidate is None:
            raise UpdateError("No previous managed version is available to roll back to.")
        preference = read_autostart_preference()
        hotkey_was_registered = black_hotkey_registered()
        if _probe_installed_version(candidate.path / "venv" / "bin" / APP_ID) != candidate.version:
            raise UpdateError("The previous managed version failed validation; rollback was not activated.")
        if preference.enabled and preference.tray:
            _probe_tray_runtime(candidate.path)
        launcher, warnings = _activate_record(
            candidate,
            autostart_preference=preference,
            hotkey_was_registered=hotkey_was_registered,
        )
        return InstallResult(candidate, current, launcher, warnings)


def restart_settings() -> None:
    launcher = managed_launcher()
    if not launcher.exists():
        raise UpdateError("The managed launcher is missing; cannot restart Settings.")
    subprocess.Popen([str(launcher), "settings"], start_new_session=True, close_fds=True)
