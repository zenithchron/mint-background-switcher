"""Web cache management: cache stats, clear, CLI commands, and the browser button."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from mint_background_switcher.sources import (
    FEED_SIDECAR_SUFFIX,
    clear_web_source_cache,
    web_source_cache_dir,
    web_source_cache_stats,
    web_source_stem,
)

# --- CacheStats / web_source_cache_stats -------------------------------------


def _owned_name(url: str, suffix: str) -> str:
    return web_source_stem(url) + suffix


def _write(cache_dir: Path, name: str, data: bytes = b"img") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    path.write_bytes(data)
    return path


def test_cache_stats_missing_dir_reports_zero(tmp_path):
    stats = web_source_cache_stats(tmp_path / "nope" / "web_sources")
    assert (
        stats.picture_count
        == stats.picture_bytes
        == stats.sidecar_count
        == stats.sidecar_bytes
        == stats.temp_file_count
        == stats.temp_file_bytes
        == 0
    )
    assert stats.total_bytes == 0
    assert stats.cache_dir == str(tmp_path / "nope" / "web_sources")


def test_cache_stats_counts_only_mbs_owned_files(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url_a = "https://example.com/a.jpg"
    url_b = "https://example.com/b.png"
    feed = "https://example.com/gallery.rss"
    _write(cache_dir, _owned_name(url_a, ".jpg"), b"x" * 100)
    _write(cache_dir, _owned_name(url_b, ".png"), b"x" * 250)
    _write(cache_dir, _owned_name(feed, FEED_SIDECAR_SUFFIX), b'["a"]')
    _write(cache_dir, ".tmpname.part", b"x" * 10)
    # Not owned by the cache: unrelated names, extensions, and subdirectories.
    _write(cache_dir, "notes.txt")
    _write(cache_dir, "randomphoto.jpg")
    sub = cache_dir / "subdir"
    sub.mkdir()
    _write(sub, "inside.jpg")

    stats = web_source_cache_stats(cache_dir)

    assert stats.picture_count == 2
    assert stats.picture_bytes == 350
    assert stats.sidecar_count == 1
    assert stats.sidecar_bytes == 5
    assert stats.temp_file_count == 1
    assert stats.temp_file_bytes == 10
    assert stats.total_bytes == 365


def test_cache_stats_accepts_str_path(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    _write(cache_dir, _owned_name("https://example.com/a.jpg", ".jpg"), b"x" * 5)
    assert web_source_cache_stats(str(cache_dir)).picture_count == 1


def test_cache_stats_to_dict_is_json_safe(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    _write(cache_dir, _owned_name("https://example.com/a.jpg", ".jpg"), b"x" * 5)
    payload = web_source_cache_stats(cache_dir).to_dict()
    assert set(payload) == {
        "cache_dir",
        "pictures",
        "picture_bytes",
        "feed_sidecars",
        "sidecar_bytes",
        "temp_files",
        "temp_file_bytes",
        "total_bytes",
    }
    json.dumps(payload)


# --- clear_web_source_cache ---------------------------------------------------


def _seeded_cache(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    cache_dir = web_source_cache_dir(tmp_path)
    url_a = "https://example.com/a.jpg"
    feed = "https://example.com/gallery.rss"
    return cache_dir, {
        "pic_a": _write(cache_dir, _owned_name(url_a, ".jpg"), b"x" * 100),
        "pic_b": _write(cache_dir, _owned_name("https://example.com/b.png", ".png"), b"x" * 40),
        "sidecar": _write(cache_dir, _owned_name(feed, FEED_SIDECAR_SUFFIX), b"[]"),
        "temp": _write(cache_dir, ".dangling.part", b"t" * 7),
        "foreign": _write(cache_dir, "notes.txt", b"keep me"),
    }


def test_cache_clear_removes_only_owned_files(tmp_path):
    cache_dir, files = _seeded_cache(tmp_path)
    sub = cache_dir / "subdir"
    sub.mkdir()
    subfile = _write(sub, "inside.jpg")

    deleted = clear_web_source_cache(cache_dir)

    assert deleted.picture_count == 2
    assert deleted.picture_bytes == 140
    assert deleted.sidecar_count == 1
    assert deleted.temp_file_count == 1
    assert deleted.temp_file_bytes == 7
    assert deleted.total_bytes == 149
    for key in ("pic_a", "pic_b", "sidecar", "temp"):
        assert not files[key].exists()
    # Foreign files, subdirectories, and the cache directory itself survive.
    assert files["foreign"].is_file()
    assert subfile.is_file()
    assert cache_dir.is_dir()


def test_cache_clear_is_idempotent(tmp_path):
    cache_dir, _files = _seeded_cache(tmp_path)
    clear_web_source_cache(cache_dir)
    again = clear_web_source_cache(cache_dir)
    assert again.total_bytes == 0
    assert again.picture_count == 0 and again.sidecar_count == 0 and again.temp_file_count == 0


def test_cache_clear_missing_dir_is_a_noop(tmp_path):
    deleted = clear_web_source_cache(tmp_path / "missing" / "web_sources")
    assert deleted.total_bytes == 0


def test_cache_clear_ignores_symlinked_directories(tmp_path):
    cache_dir, files = _seeded_cache(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    target_file = (target / "precious.jpg")
    target_file.write_bytes(b"do not delete")
    os.symlink(target, cache_dir / "aliasdir")

    deleted = clear_web_source_cache(cache_dir)

    assert deleted.picture_count == 2  # only the real cache images
    assert target_file.is_file()


# --- CLI: cache info / cache clear --------------------------------------------


def _env_cache_dir(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    from mint_background_switcher.config import load_config, save_config
    from mint_background_switcher.working_storage import configured_working_directory

    save_config(load_config())  # create the config; working dir stays the env default
    return web_source_cache_dir(configured_working_directory(load_config()))


def test_cli_cache_info_reports_stats(monkeypatch, tmp_path, capsys):
    cache_dir = _env_cache_dir(monkeypatch, tmp_path)
    _write(cache_dir, _owned_name("https://example.com/a.jpg", ".jpg"), b"x" * 100)
    _write(cache_dir, _owned_name("https://example.com/gallery.rss", FEED_SIDECAR_SUFFIX), b"[]")
    _write(cache_dir, "notes.txt", b"ignored")

    from mint_background_switcher import cli

    assert cli.main(["cache", "info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cache_dir"] == str(cache_dir)
    assert payload["pictures"] == 1
    assert payload["picture_bytes"] == 100
    assert payload["feed_sidecars"] == 1
    assert payload["total_bytes"] == 102


def test_cli_cache_info_empty_cache_reports_zero(monkeypatch, tmp_path, capsys):
    _env_cache_dir(monkeypatch, tmp_path)

    from mint_background_switcher import cli

    assert cli.main(["cache", "info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pictures"] == 0
    assert payload["total_bytes"] == 0


def test_cli_cache_clear_dry_run_deletes_nothing(monkeypatch, tmp_path, capsys):
    _cache_dir, files = _seeded_cache(tmp_path)
    _env_cache_dir(monkeypatch, tmp_path)
    # Point the config's working dir at the seeded tree's parent so the
    # cache directory is the seeded <tmp>/web_sources.
    from mint_background_switcher.config import load_config, save_config

    config = load_config()
    config.working_directory = str(tmp_path)
    save_config(config)

    from mint_background_switcher import cli

    assert cli.main(["cache", "clear", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["would_delete_pictures"] == 2
    assert payload["would_delete_feed_sidecars"] == 1
    assert payload["would_delete_temp_files"] == 1
    assert payload["would_delete_bytes"] == 149
    assert payload["remaining_pictures"] == 2
    for key, path in files.items():
        assert path.is_file(), f"{key} must survive a dry run"


def test_cli_cache_clear_deletes_and_reports_remaining(monkeypatch, tmp_path, capsys):
    cache_dir, files = _seeded_cache(tmp_path)
    _env_cache_dir(monkeypatch, tmp_path)
    from mint_background_switcher.config import load_config, save_config

    config = load_config()
    config.working_directory = str(tmp_path)
    save_config(config)

    from mint_background_switcher import cli

    assert cli.main(["cache", "clear"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["deleted_pictures"] == 2
    assert payload["deleted_feed_sidecars"] == 1
    assert payload["deleted_temp_files"] == 1
    assert payload["deleted_bytes"] == 149
    assert payload["remaining_pictures"] == 0
    assert payload["remaining_bytes"] == 0
    for key in ("pic_a", "pic_b", "sidecar", "temp"):
        assert not files[key].exists()
    assert files["foreign"].is_file()


# --- Tk browser: header usage + Clear Cache... (needs a display or Xvfb) ------

import gc  # noqa: E402
import time  # noqa: E402

import tkinter as tk  # noqa: E402

from mint_background_switcher.cached_pictures import (  # noqa: E402
    BROWSER_MINSIZE,
    CachedPicturesWindow,
)


def _pump_until(root: tk.Misc, predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert predicate(), "timed out waiting for the window to settle"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_header_shows_total_cache_usage(tmp_path):
    cache_dir, files = _seeded_cache(tmp_path)
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        root.update()
        header = window._header_var.get()
        assert "0 cached web source pictures" in header
        # 100 + 40 + 2 + 7 = 149 bytes of owned cache content.
        assert "149 B used" in header
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_clear_cache_confirms_and_deletes(monkeypatch, tmp_path):
    cache_dir, files = _seeded_cache(tmp_path)
    confirmed: list[bool] = []

    def fake_askyesno(title: str, message: str, parent=None) -> bool:
        confirmed.append(True)
        assert title == "Clear Web Picture Cache"
        assert "2 cached picture(s)" in message
        assert "1 feed record(s)" in message
        assert "1 interrupted-download temp file(s)" in message
        assert str(cache_dir) in message
        return True

    monkeypatch.setattr("mint_background_switcher.cached_pictures.messagebox.askyesno", fake_askyesno)
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        root.update()
        window._clear_cache()
        _pump_until(root, lambda: "Cleared 2 picture(s) and 1 feed record(s)" in window._status_var.get())
        assert confirmed == [True]
        for key in ("pic_a", "pic_b", "sidecar", "temp"):
            assert not files[key].exists()
        assert files["foreign"].is_file()
        # The window is back to the empty state and usable.
        assert window._picture_list.size() == 0
        assert "0 cached web source pictures" in window._header_var.get()
        assert "0 B used" in window._header_var.get()
        assert "disabled" not in window._clear_button.state()
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_clear_cache_cancel_keeps_everything(monkeypatch, tmp_path):
    cache_dir, files = _seeded_cache(tmp_path)
    monkeypatch.setattr(
        "mint_background_switcher.cached_pictures.messagebox.askyesno",
        lambda title, message, parent=None: False,
    )
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        root.update()
        window._clear_cache()
        root.update()
        assert "cancelled" in window._status_var.get()
        for path in files.values():
            assert path.is_file()
        assert window._clearing is False
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_clear_cache_empty_skips_confirmation(monkeypatch, tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    cache_dir.mkdir(parents=True)

    def boom(title, message, parent=None) -> bool:
        raise AssertionError("an empty cache must not prompt for confirmation")

    monkeypatch.setattr("mint_background_switcher.cached_pictures.messagebox.askyesno", boom)
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        root.update()
        window._clear_cache()
        root.update()
        assert "already empty" in window._status_var.get()
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_clear_cache_failure_is_reported(monkeypatch, tmp_path):
    cache_dir, _files = _seeded_cache(tmp_path)
    monkeypatch.setattr(
        "mint_background_switcher.cached_pictures.messagebox.askyesno",
        lambda title, message, parent=None: True,
    )
    monkeypatch.setattr(
        "mint_background_switcher.cached_pictures.clear_web_source_cache",
        lambda directory: (_ for _ in ()).throw(OSError("disk full")),
    )
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        root.update()
        window._clear_cache()
        _pump_until(root, lambda: "could not be cleared" in window._status_var.get())
        assert window._clearing is False
        assert "disabled" not in window._clear_button.state()
    finally:
        window.destroy()
        root.destroy()
        # Free the destroyed root's Tcl interpreter on the main thread so a
        # still-running launch daemon thread cannot run the GC that frees it:
        # Tcl 8.6 (Python <= 3.13) aborts on cross-thread finalization.
        del window, root
        gc.collect()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_browser_clear_button_fits_at_minimum_size(tmp_path):
    """Every control must stay fully visible at the window's minimum geometry."""

    cache_dir, _files = _seeded_cache(tmp_path)
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: [], cache_dir)
    try:
        window.geometry(f"{BROWSER_MINSIZE[0]}x{BROWSER_MINSIZE[1]}")
        window.update_idletasks()
        window.update()
        root.update()
        width = window.winfo_width()
        assert width >= BROWSER_MINSIZE[0]
        for button in (window._open_button, window._open_folder_button, window._clear_button):
            assert button.winfo_ismapped()
            assert button.winfo_x() + button.winfo_width() <= width
    finally:
        window.destroy()
        root.destroy()
