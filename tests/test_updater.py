import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from mint_background_switcher import updater


class _Response:
    def __init__(self, payload: bytes, *, url: str, headers: dict[str, str] | None = None):
        self._stream = io.BytesIO(payload)
        self._url = url
        self.headers = headers or {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _json_response(value, url: str) -> _Response:
    return _Response(json.dumps(value).encode("utf-8"), url=url)


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes, *, mode: int = 0o644) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = mode
    archive.addfile(member, io.BytesIO(data))


def _make_release_archive(
    path: Path,
    version: str,
    *,
    member_name: str | None = None,
    symlink: bool = False,
    init_payload: bytes | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> Path:
    root = "mint-background-switcher-source"
    with tarfile.open(path, "w:gz") as archive:
        root_member = tarfile.TarInfo(f"{root}/")
        root_member.type = tarfile.DIRTYPE
        root_member.mode = 0o755
        archive.addfile(root_member)
        _add_bytes(
            archive,
            f"{root}/pyproject.toml",
            (
                "[build-system]\n"
                'requires = ["setuptools>=68", "wheel"]\n'
                'build-backend = "setuptools.build_meta"\n\n'
                "[project]\n"
                'name = "mint-background-switcher"\n'
                f'version = "{version}"\n'
            ).encode("utf-8"),
        )
        _add_bytes(
            archive,
            f"{root}/mint_background_switcher/__init__.py",
            init_payload if init_payload is not None else f'__version__ = "{version}"\n'.encode("utf-8"),
        )
        if member_name:
            if symlink:
                member = tarfile.TarInfo(member_name)
                member.type = tarfile.SYMTYPE
                member.linkname = "/tmp/escape"
                archive.addfile(member)
            else:
                _add_bytes(archive, member_name, b"unexpected")
        for extra_name, extra_payload in extra_members:
            _add_bytes(archive, extra_name, extra_payload)
    return path


class _FakeClient:
    def __init__(self, archive: Path, commit: str):
        self.archive = archive
        self.commit = commit
        self.resolved = []

    def download_release(self, release, destination: Path) -> str:
        shutil.copyfile(self.archive, destination)
        return updater.sha256_file(destination)

    def resolve_tag_commit(self, tag: str) -> str:
        self.resolved.append(tag)
        return self.commit


class _UnexpectedClient:
    def download_release(self, *_args, **_kwargs):
        raise AssertionError("rejected release must not be downloaded")

    def resolve_tag_commit(self, *_args, **_kwargs):
        raise AssertionError("rejected release must not resolve a tag")


def _fake_payload_installer(archive: Path, staging: Path, version: str) -> None:
    assert archive.exists()
    interpreter = staging / "venv" / "bin" / "python"
    executable = staging / "venv" / "bin" / "mint-background-switcher"
    executable.parent.mkdir(parents=True)
    interpreter.write_text(
        '#!/bin/sh\nscript="$1"\nshift\nexec /bin/sh "$script" "$@"\n',
        encoding="utf-8",
    )
    interpreter.chmod(0o755)
    executable.write_text(
        f"#!{interpreter}\necho mint-background-switcher {version}\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def test_version_parsing_and_ordering_rejects_non_release_tags():
    assert updater.version_key("0.1.12") > updater.version_key("0.1.9")
    assert updater.version_from_tag("v2.3.4") == "2.3.4"
    for value in ("1.2", "v1.2", "v1.2.3-rc1", "v1.2.3/../../x", "1.2.3\n"):
        with pytest.raises(ValueError):
            updater.version_from_tag(value)


@pytest.mark.parametrize(
    "value",
    [
        "v1.2.3",
        "1.2",
        "1.2.3-beta",
        "1.2.3.4",
        "../../1.2.3",
        "01.2.3",
        "1.2.000000003",
        "1" * 10 + ".2.3",
    ],
)
def test_semantic_version_parser_rejects_nonstable_values(value):
    with pytest.raises(ValueError):
        updater.version_key(value)


@pytest.mark.parametrize("tag", ["v01.2.3", "v1.2.000000003", "v" + "1" * 10 + ".2.3"])
def test_release_tag_parser_rejects_noncanonical_semver(tag):
    with pytest.raises(ValueError):
        updater.version_from_tag(tag)


def test_github_client_selects_latest_release_and_peels_annotated_tag():
    tag_object = "a" * 40
    commit = "b" * 40
    calls = []

    def opener(request, timeout):
        url = request.full_url
        calls.append((url, timeout))
        if url.endswith("/tags?per_page=100"):
            return _json_response(
                [
                    {"name": "v0.1.9", "commit": {"sha": "9" * 40}},
                    {"name": "not-a-release", "commit": {"sha": "8" * 40}},
                    {"name": "v0.1.12", "commit": {"sha": commit}},
                ],
                url,
            )
        if url.endswith("/git/ref/tags/v0.1.12"):
            return _json_response({"object": {"type": "tag", "sha": tag_object}}, url)
        if url.endswith(f"/git/tags/{tag_object}"):
            return _json_response({"object": {"type": "commit", "sha": commit}}, url)
        raise AssertionError(url)

    client = updater.GitHubClient(opener=opener)
    release = client.latest_release()

    assert release.version == "0.1.12"
    assert release.tag == "v0.1.12"
    assert release.commit_sha == commit
    assert release.archive_url.endswith(f"/{commit}.tar.gz")
    assert all(timeout == updater.NETWORK_TIMEOUT_SECONDS for _url, timeout in calls)


def test_github_client_rejects_untrusted_download_redirect(monkeypatch, tmp_path):
    payload = b"archive"

    def opener(_request, timeout):
        assert timeout == updater.NETWORK_TIMEOUT_SECONDS
        return _Response(payload, url="https://evil.example/update.tar.gz")

    client = updater.GitHubClient(opener=opener)
    destination = tmp_path / "update.tar.gz"
    release = updater.ReleaseInfo("0.1.12", "v0.1.12", "a" * 40, "https://github.com/zenithchron/mint-background-switcher/archive/a.tar.gz")

    with pytest.raises(updater.UpdateError, match="untrusted download host"):
        client.download_release(release, destination)
    assert not destination.exists()


def test_github_client_rejects_malformed_content_length():
    def opener(request, timeout):
        return _Response(b"[]", url=request.full_url, headers={"Content-Length": "not-a-number"})

    with pytest.raises(updater.UpdateError, match="invalid response size"):
        updater.GitHubClient(opener=opener).latest_release()


def test_validate_release_archive_accepts_matching_release(tmp_path):
    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")

    metadata = updater.validate_release_archive(archive, "0.1.12")

    assert metadata.project_name == "mint-background-switcher"
    assert metadata.version == "0.1.12"
    assert metadata.root_name == "mint-background-switcher-source"


def test_validate_release_archive_rejects_version_mismatch_and_unsafe_members(tmp_path):
    mismatch = _make_release_archive(tmp_path / "mismatch.tar.gz", "0.1.11")
    traversal = _make_release_archive(tmp_path / "traversal.tar.gz", "0.1.12", member_name="../escape")
    link = _make_release_archive(
        tmp_path / "link.tar.gz",
        "0.1.12",
        member_name="mint-background-switcher-source/link",
        symlink=True,
    )
    invalid_utf8 = _make_release_archive(
        tmp_path / "invalid-utf8.tar.gz",
        "0.1.12",
        init_payload=b"\xff\xfe",
    )
    ambiguous_metadata = _make_release_archive(
        tmp_path / "ambiguous-metadata.tar.gz",
        "0.1.12",
        extra_members=(
            (
                "mint-background-switcher-source/./pyproject.toml",
                b"[project]\nname='mint-background-switcher'\nversion='9.9.9'\n",
            ),
        ),
    )

    with pytest.raises(updater.UpdateError, match="version"):
        updater.validate_release_archive(mismatch, "0.1.12")
    with pytest.raises(updater.UpdateError, match="unsafe archive path"):
        updater.validate_release_archive(traversal, "0.1.12")
    with pytest.raises(updater.UpdateError, match="unsupported archive member"):
        updater.validate_release_archive(link, "0.1.12")
    with pytest.raises(updater.UpdateError, match="malformed package metadata"):
        updater.validate_release_archive(invalid_utf8, "0.1.12")
    with pytest.raises(updater.UpdateError, match="unsafe|duplicate"):
        updater.validate_release_archive(ambiguous_metadata, "0.1.12")


def test_update_command_os_error_is_user_facing(monkeypatch):
    monkeypatch.setattr(updater.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")))

    with pytest.raises(updater.UpdateError, match="Could not start update command"):
        updater._run_checked(["missing-python", "--version"])


def test_install_release_atomically_manages_launcher_and_preserves_tray_autostart(monkeypatch, tmp_path):
    install_root = tmp_path / "data" / "mint-background-switcher"
    user_bin = tmp_path / "bin"
    config_home = tmp_path / "config-home"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sentinel = config_dir / "config.json"
    sentinel.write_text('{"keep": true}\n', encoding="utf-8")
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(install_root))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(user_bin))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("MBS_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "_probe_installed_version", lambda _path: "0.1.12")
    monkeypatch.setattr(updater, "_probe_tray_runtime", lambda _staging: None)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)

    autostart = config_home / "autostart" / "mint-background-switcher.desktop"
    autostart.parent.mkdir(parents=True)
    autostart.write_text(
        "[Desktop Entry]\nExec=/old/mint-background-switcher tray\nX-GNOME-Autostart-Delay=90\n",
        encoding="utf-8",
    )
    user_bin.mkdir(parents=True)
    old_launcher = user_bin / "mint-background-switcher"
    old_launcher.write_text("old launcher\n", encoding="utf-8")

    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    commit = "c" * 40
    release = updater.ReleaseInfo(
        "0.1.12",
        "v0.1.12",
        commit,
        f"https://github.com/zenithchron/mint-background-switcher/archive/{commit}.tar.gz",
    )
    result = updater.install_release(release, client=_FakeClient(archive, commit))

    assert result.record.version == "0.1.12"
    assert result.record.commit_sha == commit
    assert updater.active_install().version == "0.1.12"
    finalized = subprocess.run(
        [str(result.record.path / "venv" / "bin" / "mint-background-switcher"), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert finalized.stdout.strip() == "mint-background-switcher 0.1.12"
    assert updater.managed_launcher().is_symlink()
    assert updater.managed_launcher().resolve() == (result.record.path / "venv" / "bin" / "mint-background-switcher").resolve()
    backups = list(user_bin.glob("mint-background-switcher.pre-managed-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "old launcher\n"
    autostart_text = autostart.read_text(encoding="utf-8")
    assert f"Exec={updater.managed_launcher()} tray" in autostart_text
    assert "X-GNOME-Autostart-Delay=90" in autostart_text
    assert sentinel.read_text(encoding="utf-8") == '{"keep": true}\n'
    receipt = json.loads((result.record.path / updater.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["archive_sha256"] == updater.sha256_file(archive)


def test_install_failure_leaves_active_install_launcher_and_autostart_unchanged(monkeypatch, tmp_path):
    install_root = tmp_path / "managed"
    user_bin = tmp_path / "bin"
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(install_root))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(user_bin))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)
    user_bin.mkdir(parents=True)
    launcher = user_bin / "mint-background-switcher"
    launcher.write_text("keep launcher\n", encoding="utf-8")
    autostart = config_home / "autostart" / "mint-background-switcher.desktop"
    autostart.parent.mkdir(parents=True)
    original_autostart = "[Desktop Entry]\nExec=/old/app safe-start\nX-GNOME-Autostart-Delay=20\n"
    autostart.write_text(original_autostart, encoding="utf-8")

    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    commit = "d" * 40
    release = updater.ReleaseInfo("0.1.12", "v0.1.12", commit, f"https://github.com/example/{commit}.tar.gz")

    def fail_install(*_args):
        raise RuntimeError("pip failed")

    monkeypatch.setattr(updater, "_install_payload", fail_install)

    with pytest.raises(RuntimeError, match="pip failed"):
        updater.install_release(release, client=_FakeClient(archive, commit))

    assert launcher.read_text(encoding="utf-8") == "keep launcher\n"
    assert autostart.read_text(encoding="utf-8") == original_autostart
    assert not os.path.lexists(install_root / "current")
    assert not list((install_root / "versions").glob("0.1.12-*"))


def test_missing_tray_runtime_aborts_before_activation(monkeypatch, tmp_path):
    install_root = tmp_path / "managed"
    user_bin = tmp_path / "bin"
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(install_root))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(user_bin))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)
    monkeypatch.setattr(
        updater,
        "_probe_tray_runtime",
        lambda _staging: (_ for _ in ()).throw(updater.UpdateError("tray runtime unavailable")),
    )
    autostart = config_home / "autostart" / "mint-background-switcher.desktop"
    autostart.parent.mkdir(parents=True)
    original = "[Desktop Entry]\nExec=/old/mint-background-switcher tray\nX-GNOME-Autostart-Delay=90\n"
    autostart.write_text(original, encoding="utf-8")
    user_bin.mkdir(parents=True)
    launcher = user_bin / "mint-background-switcher"
    launcher.write_text("old launcher\n", encoding="utf-8")
    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    commit = "5" * 40

    with pytest.raises(updater.UpdateError, match="tray runtime unavailable"):
        updater.install_release(
            updater.ReleaseInfo("0.1.12", "v0.1.12", commit, "https://github.com/example/release.tar.gz"),
            client=_FakeClient(archive, commit),
        )

    assert launcher.read_text(encoding="utf-8") == "old launcher\n"
    assert autostart.read_text(encoding="utf-8") == original
    assert updater.active_install() is None


def test_activation_failure_restores_previous_version_launcher_and_autostart(monkeypatch, tmp_path):
    install_root = tmp_path / "managed"
    user_bin = tmp_path / "bin"
    config_home = tmp_path / "config"
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(install_root))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(user_bin))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)

    first_archive = _make_release_archive(tmp_path / "first.tar.gz", "0.1.12")
    first_commit = "3" * 40
    first = updater.install_release(
        updater.ReleaseInfo("0.1.12", "v0.1.12", first_commit, "https://github.com/example/first.tar.gz"),
        client=_FakeClient(first_archive, first_commit),
    )
    autostart = config_home / "autostart" / "mint-background-switcher.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    original_autostart = (
        f"[Desktop Entry]\nExec={updater.managed_launcher()} safe-start\n"
        "X-GNOME-Autostart-Delay=45\n"
    )
    autostart.write_text(original_autostart, encoding="utf-8")

    second_archive = _make_release_archive(tmp_path / "second.tar.gz", "0.1.13")
    second_commit = "4" * 40
    monkeypatch.setattr(
        updater,
        "enable_autostart",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("desktop entry failed")),
    )

    with pytest.raises(RuntimeError, match="desktop entry failed"):
        updater.install_release(
            updater.ReleaseInfo("0.1.13", "v0.1.13", second_commit, "https://github.com/example/second.tar.gz"),
            client=_FakeClient(second_archive, second_commit),
        )

    active = updater.active_install()
    assert active is not None
    assert active.path == first.record.path
    assert updater.managed_launcher().resolve() == (first.record.path / "venv" / "bin" / "mint-background-switcher").resolve()
    assert autostart.read_text(encoding="utf-8") == original_autostart


def test_tag_movement_aborts_before_activation(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    expected = "e" * 40
    moved = "f" * 40
    release = updater.ReleaseInfo("0.1.12", "v0.1.12", expected, f"https://github.com/example/{expected}.tar.gz")

    with pytest.raises(updater.UpdateError, match="tag moved"):
        updater.install_release(release, client=_FakeClient(archive, moved))
    assert not os.path.lexists(tmp_path / "managed" / "current")


def test_tag_movement_during_payload_install_aborts_before_activation(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    expected = "a" * 40
    moved = "b" * 40
    release = updater.ReleaseInfo("0.1.12", "v0.1.12", expected, f"https://github.com/example/{expected}.tar.gz")

    class MovingClient(_FakeClient):
        def __init__(self):
            super().__init__(archive, expected)
            self._commits = iter((expected, moved))

        def resolve_tag_commit(self, tag: str) -> str:
            self.resolved.append(tag)
            return next(self._commits)

    with pytest.raises(updater.UpdateError, match="tag moved"):
        updater.install_release(release, client=MovingClient())

    assert not os.path.lexists(tmp_path / "managed" / "current")


def test_existing_verified_install_rechecks_tag_before_reactivation(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)
    archive = _make_release_archive(tmp_path / "release.tar.gz", "0.1.12")
    expected = "3" * 40
    moved = "4" * 40
    release = updater.ReleaseInfo("0.1.12", "v0.1.12", expected, f"https://github.com/example/{expected}.tar.gz")
    original = updater.install_release(release, client=_FakeClient(archive, expected))

    with pytest.raises(updater.UpdateError, match="tag moved"):
        updater.install_release(release, client=_FakeClient(archive, moved))

    active = updater.active_install()
    assert active is not None
    assert active.path == original.record.path


def test_inactive_installed_version_rejects_rewritten_tag_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)

    old_archive = _make_release_archive(tmp_path / "old.tar.gz", "0.1.11")
    old_commit = "1" * 40
    old_release = updater.ReleaseInfo("0.1.11", "v0.1.11", old_commit, "https://github.com/example/old.tar.gz")
    old = updater.install_release(old_release, client=_FakeClient(old_archive, old_commit))

    new_archive = _make_release_archive(tmp_path / "new.tar.gz", "0.1.12")
    original_commit = "2" * 40
    original_release = updater.ReleaseInfo(
        "0.1.12",
        "v0.1.12",
        original_commit,
        "https://github.com/example/new.tar.gz",
    )
    installed = updater.install_release(original_release, client=_FakeClient(new_archive, original_commit))
    updater.rollback_install()
    active = updater.active_install()
    assert active is not None
    assert active.path == old.record.path
    assert installed.record.path.exists()

    rewritten = updater.ReleaseInfo(
        "0.1.12",
        "v0.1.12",
        "3" * 40,
        "https://github.com/example/rewritten.tar.gz",
    )
    with pytest.raises(updater.UpdateError, match="different commit"):
        updater.install_release(rewritten, client=_UnexpectedClient())


@pytest.mark.parametrize(
    ("version", "commit", "message"),
    [
        ("0.1.12", "7" * 40, "Use Roll Back"),
        ("0.1.13", "8" * 40, "different commit"),
    ],
)
def test_normal_install_rejects_downgrade_and_same_version_tag_rewrite(
    monkeypatch,
    tmp_path,
    version,
    commit,
    message,
):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    active = updater.InstallRecord("0.1.13", "6" * 40, "a" * 64, "2026-07-21T20:00:00+00:00", tmp_path / "active")
    monkeypatch.setattr(updater, "active_install", lambda: active)
    release = updater.ReleaseInfo(version, f"v{version}", commit, "https://github.com/example/release.tar.gz")

    with pytest.raises(updater.UpdateError, match=message):
        updater.install_release(release, client=_UnexpectedClient())


def test_second_install_can_roll_back_to_previous_version(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater, "_install_payload", _fake_payload_installer)
    monkeypatch.setattr(updater, "black_hotkey_registered", lambda: False)

    first_archive = _make_release_archive(tmp_path / "first.tar.gz", "0.1.12")
    first_commit = "1" * 40
    first = updater.install_release(
        updater.ReleaseInfo("0.1.12", "v0.1.12", first_commit, f"https://github.com/example/{first_commit}.tar.gz"),
        client=_FakeClient(first_archive, first_commit),
    )
    second_archive = _make_release_archive(tmp_path / "second.tar.gz", "0.1.13")
    second_commit = "2" * 40
    second = updater.install_release(
        updater.ReleaseInfo("0.1.13", "v0.1.13", second_commit, f"https://github.com/example/{second_commit}.tar.gz"),
        client=_FakeClient(second_archive, second_commit),
    )

    assert updater.active_install().version == "0.1.13"
    assert updater.rollback_candidate().version == "0.1.12"
    autostart = tmp_path / "config" / "autostart" / "mint-background-switcher.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(
        f"[Desktop Entry]\nExec={updater.managed_launcher()} tray\nX-GNOME-Autostart-Delay=90\n",
        encoding="utf-8",
    )
    tray_probes = []
    monkeypatch.setattr(updater, "_probe_tray_runtime", lambda path: tray_probes.append(path))
    rolled_back = updater.rollback_install()
    assert rolled_back.record.version == "0.1.12"
    assert rolled_back.previous.version == "0.1.13"
    assert updater.active_install().path == first.record.path
    assert second.record.path.exists()
    assert tray_probes == [first.record.path]
    assert updater.rollback_candidate() is None


def test_rollback_without_previous_install_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))

    assert updater.rollback_candidate() is None
    with pytest.raises(updater.UpdateError, match="No previous managed version"):
        updater.rollback_install()


def test_update_lock_rejects_concurrent_operation(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))

    with updater._update_lock():
        with pytest.raises(updater.UpdateBusyError, match="already running"):
            with updater._update_lock():
                raise AssertionError("nested updater must not acquire the lock")


def test_restart_settings_uses_managed_launcher_without_shell(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_INSTALL_ROOT", str(tmp_path / "managed"))
    monkeypatch.setenv("MBS_USER_BIN_DIR", str(tmp_path / "bin"))
    launcher = updater.managed_launcher()
    launcher.parent.mkdir(parents=True)
    launcher.write_text("launcher", encoding="utf-8")
    calls = []

    monkeypatch.setattr(updater.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)) or object())

    updater.restart_settings()

    assert calls == [([str(launcher), "settings"], {"start_new_session": True, "close_fds": True})]
