import subprocess
import time
from pathlib import Path

from PIL import Image

from mint_background_switcher.availability import (
    CollectionUnavailableError,
    ProbeResult,
    probe_folders,
)


def test_collection_unavailable_error_is_a_runtime_error():
    assert issubclass(CollectionUnavailableError, RuntimeError)


def test_probe_empty_folder_list_is_available():
    assert probe_folders([]) == ProbeResult(status="ok", reason="")
    assert probe_folders(["  ", ""]) == ProbeResult(status="ok", reason="")


def test_probe_reports_ok_for_existing_directories_and_single_files(tmp_path: Path):
    folder = tmp_path / "pics"
    folder.mkdir()
    single = folder / "solo.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(single)
    other = tmp_path / "other"
    other.mkdir()
    result = probe_folders([str(folder), str(single), str(other)], timeout=10)
    assert result.status == "ok"
    assert result.reason == ""


def test_probe_reports_missing_folder(tmp_path: Path):
    result = probe_folders([str(tmp_path / "nope")], timeout=10)
    assert result.status == "missing"
    assert str(tmp_path / "nope") in result.reason


def test_probe_reports_missing_when_path_is_wrong_kind(tmp_path: Path):
    # A directory named as a folder is fine; a broken symlink is not.
    folder = tmp_path / "pics"
    folder.mkdir()
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "gone")
    result = probe_folders([str(folder), str(link)], timeout=10)
    assert result.status == "missing"


def test_probe_reports_unresponsive_when_check_times_out(monkeypatch, tmp_path: Path):
    # A child wedged in a dead mount: poll() never returns and kill() must
    # not block. The probe must give up at the deadline, kill, and report
    # unresponsive without waiting for the child to be reaped.
    folder = tmp_path / "pics"
    folder.mkdir()

    class _Wedged:
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    wedged = _Wedged()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: wedged)
    started = time.monotonic()
    result = probe_folders([str(folder)], timeout=0.2)
    elapsed = time.monotonic() - started
    assert result.status == "unresponsive"
    assert "no response" in result.reason
    assert wedged.killed is True
    # Bounded by the deadline plus poll granularity — never a long hang.
    assert elapsed < 2.0


def test_probe_reports_error_when_child_cannot_run(monkeypatch, tmp_path: Path):
    def boom(*_args, **_kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "Popen", boom)
    result = probe_folders([str(tmp_path)])
    assert result.status == "error"
    assert "spawn failed" in result.reason
