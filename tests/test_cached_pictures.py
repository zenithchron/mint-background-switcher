"""Cached Picture Browser: cache enumeration, CLI JSON listing, and the Tk window."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from mint_background_switcher.config import Config, Profile
from mint_background_switcher.sources import (
    FEED_SIDECAR_SUFFIX,
    WEB_FEED_TYPE,
    all_web_source_entries,
    list_cached_pictures,
    web_source_cache_dir,
    web_source_stem,
)


def _write_picture(cache_dir: Path, name: str, data: bytes = b"img", mtime: float | None = None) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _sidecar_name(url: str) -> str:
    return web_source_stem(url) + FEED_SIDECAR_SUFFIX


def _url_entry(url: str) -> dict:
    return {"type": "url", "url": url}


def test_list_cached_pictures_missing_dir_returns_empty(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    assert list_cached_pictures(cache_dir, [_url_entry("https://example.com/a.jpg")]) == []


def test_list_cached_pictures_empty_dir_returns_empty(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    cache_dir.mkdir(parents=True)
    assert list_cached_pictures(cache_dir, [_url_entry("https://example.com/a.jpg")]) == []


def test_list_cached_pictures_labels_direct_url_entry(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.png")

    pictures = list_cached_pictures(cache_dir, [_url_entry(url)])

    assert len(pictures) == 1
    assert pictures[0].name == f"{web_source_stem(url)}.png"
    assert Path(pictures[0].path) == cache_dir / f"{web_source_stem(url)}.png"
    assert pictures[0].source_url == url
    assert pictures[0].source_type == "url"
    assert pictures[0].size == 3


def test_list_cached_pictures_labels_feed_pictures_from_sidecar(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    feed_url = "https://example.com/gallery.rss"
    img_a = "https://example.com/a.jpg"
    img_b = "https://example.com/b.jpg"
    _write_picture(cache_dir, _sidecar_name(feed_url), json.dumps([web_source_stem(img_a), web_source_stem(img_b)]).encode())
    _write_picture(cache_dir, f"{web_source_stem(img_a)}.jpg")
    _write_picture(cache_dir, f"{web_source_stem(img_b)}.png")
    entry = {"type": WEB_FEED_TYPE, "url": feed_url}

    pictures = list_cached_pictures(cache_dir, [entry])

    names = sorted(picture.name for picture in pictures)
    assert names == sorted([f"{web_source_stem(img_a)}.jpg", f"{web_source_stem(img_b)}.png"])
    assert all(picture.source_url == feed_url for picture in pictures)
    assert all(picture.source_type == WEB_FEED_TYPE for picture in pictures)


def test_list_cached_pictures_orphan_when_source_removed(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    orphan_stem = web_source_stem("https://example.com/gone.jpg")
    _write_picture(cache_dir, f"{orphan_stem}.jpg")

    pictures = list_cached_pictures(cache_dir, [])

    assert len(pictures) == 1
    assert pictures[0].source_url is None
    assert pictures[0].source_type == "orphan"


def test_list_cached_pictures_skips_sidecars_and_non_images(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")
    _write_picture(cache_dir, "notes.txt")
    _write_picture(cache_dir, _sidecar_name("https://example.com/gallery.rss"), b"[...]")
    _write_picture(cache_dir, "readme.md")

    pictures = list_cached_pictures(cache_dir, [_url_entry(url)])

    assert [picture.name for picture in pictures] == [f"{web_source_stem(url)}.jpg"]


def test_list_cached_pictures_sorts_newest_first_and_applies_limit(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url_a = "https://example.com/old.jpg"
    url_b = "https://example.com/new.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url_a)}.jpg", mtime=1_700_000_000)
    _write_picture(cache_dir, f"{web_source_stem(url_b)}.jpg", mtime=1_800_000_000)
    entries = [_url_entry(url_a), _url_entry(url_b)]

    pictures = list_cached_pictures(cache_dir, entries)
    assert [picture.name for picture in pictures] == [
        f"{web_source_stem(url_b)}.jpg",
        f"{web_source_stem(url_a)}.jpg",
    ]

    limited = list_cached_pictures(cache_dir, entries, limit=1)
    assert [picture.name for picture in limited] == [f"{web_source_stem(url_b)}.jpg"]


def test_list_cached_pictures_direct_entry_wins_over_feed_for_same_stem(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url = "https://example.com/pic.jpg"
    feed_url = "https://example.com/gallery.rss"
    _write_picture(cache_dir, _sidecar_name(feed_url), json.dumps([web_source_stem(url)]).encode())
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")

    pictures = list_cached_pictures(cache_dir, [_url_entry(url), {"type": WEB_FEED_TYPE, "url": feed_url}])

    assert len(pictures) == 1
    assert pictures[0].source_url == url
    assert pictures[0].source_type == "url"


def test_list_cached_pictures_malformed_sidecar_fails_open(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    feed_url = "https://example.com/gallery.rss"
    img = "https://example.com/a.jpg"
    _write_picture(cache_dir, _sidecar_name(feed_url), b"{not json")
    _write_picture(cache_dir, f"{web_source_stem(img)}.jpg")

    pictures = list_cached_pictures(cache_dir, [{"type": WEB_FEED_TYPE, "url": feed_url}])

    assert len(pictures) == 1
    assert pictures[0].source_url is None
    assert pictures[0].source_type == "orphan"


def test_list_cached_pictures_clamps_limit(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    for index in range(3):
        _write_picture(cache_dir, f"{web_source_stem(f'https://example.com/p{index}.jpg')}.jpg")

    # Limits below the floor list exactly the newest picture; huge limits list everything.
    assert len(list_cached_pictures(cache_dir, [], limit=0)) == 1
    assert len(list_cached_pictures(cache_dir, [], limit=-5)) == 1
    assert len(list_cached_pictures(cache_dir, [], limit=10**9)) == 3


def test_cached_picture_to_dict_is_serializable_and_iso_typed(tmp_path):
    cache_dir = web_source_cache_dir(tmp_path)
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")

    payload = list_cached_pictures(cache_dir, [_url_entry(url)])[0].to_dict()

    assert set(payload) == {"name", "path", "source_url", "source_type", "cached_at", "size"}
    assert isinstance(payload["size"], int)
    datetime.fromisoformat(payload["cached_at"])  # raises if not ISO 8601
    json.dumps(payload)  # must be JSON-safe


def test_all_web_source_entries_unions_and_dedupes_profiles():
    shared = "https://example.com/shared.jpg"
    config = Config(
        active_profile="A",
        profiles={
            "A": Profile(name="A", shared_folders=[], web_sources=[_url_entry(shared), _url_entry("https://example.com/a2.jpg")]),
            "B": Profile(name="B", shared_folders=[], web_sources=[_url_entry(shared), _url_entry("https://example.com/b.jpg")]),
        },
    )

    entries = all_web_source_entries(config)

    assert sorted(entry["url"] for entry in entries) == sorted(
        ["https://example.com/shared.jpg", "https://example.com/a2.jpg", "https://example.com/b.jpg"]
    )
    assert len(entries) == 3


def test_cli_cached_pictures_json_listing_is_headless(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))

    from mint_background_switcher.config import load_config, save_config
    from mint_background_switcher.working_storage import configured_working_directory

    url = "https://example.com/pic.jpg"
    config = load_config()
    config.get_profile("Default").web_sources = [_url_entry(url)]
    save_config(config)
    cache_dir = web_source_cache_dir(configured_working_directory(load_config()))
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg", b"x" * 1234)

    from mint_background_switcher import cli

    assert cli.main(["cached-pictures", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["cache_dir"] == str(cache_dir)
    assert payload["count"] == 1
    picture = payload["pictures"][0]
    assert picture["name"] == f"{web_source_stem(url)}.jpg"
    assert picture["source_url"] == url
    assert picture["source_type"] == "url"


def test_cli_cached_pictures_empty_cache_reports_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))

    from mint_background_switcher import cli

    assert cli.main(["cached-pictures", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["count"] == 0
    assert payload["pictures"] == []


# --- Tk browser window (needs a display or Xvfb) --------------------------------

import time  # noqa: E402

import tkinter as tk  # noqa: E402

from mint_background_switcher import settings_ui  # noqa: E402
from mint_background_switcher.cached_pictures import (  # noqa: E402
    BROWSER_MINSIZE,
    BROWSER_TITLE,
    EMPTY_HINT,
    CachedPicturesWindow,
)


def _pump_until(root: tk.Misc, predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert predicate(), "timed out waiting for the window to settle"


def _seed_web_source(monkeypatch, tmp_path: Path, url: str) -> Path:
    """Configure one direct web source and drop a matching file in the cache."""

    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    from mint_background_switcher.config import load_config, save_config
    from mint_background_switcher.working_storage import configured_working_directory

    config = load_config()
    config.get_profile("Default").web_sources = [_url_entry(url)]
    save_config(config)
    cache_dir = web_source_cache_dir(configured_working_directory(load_config()))
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg", b"x" * 1234)
    return cache_dir


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_lists_and_selects_first_picture(tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg", b"x" * 1234)
    root = tk.Tk()
    window = CachedPicturesWindow(
        root,
        lambda: list_cached_pictures(cache_dir, [_url_entry(url)]),
        cache_dir,
    )
    try:
        root.update()
        assert window.title() == BROWSER_TITLE
        assert window._picture_list.size() == 1
        assert window._picture_list.curselection() == (0,)
        row = window._picture_list.get(0)
        assert f"{web_source_stem(url)}.jpg" in row
        assert url in row
        assert "1 cached web source picture" in window._header_var.get()
        # First paint reports the selection, not a refresh.
        assert window._status_var.get().startswith("Selected ")
        assert window.winfo_width() >= BROWSER_MINSIZE[0]
        assert window.winfo_height() >= BROWSER_MINSIZE[1]
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_empty_cache_shows_hint(tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    cache_dir.mkdir(parents=True)
    root = tk.Tk()
    window = CachedPicturesWindow(root, lambda: list_cached_pictures(cache_dir, []), cache_dir)
    try:
        root.update()
        assert window._picture_list.size() == 0
        assert "0 cached web source pictures" in window._header_var.get()
        assert window._status_var.get() == EMPTY_HINT
        assert "disabled" in window._open_button.state()
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_refresh_picks_up_new_files(tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    url_a = "https://example.com/a.jpg"
    url_b = "https://example.com/b.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url_a)}.jpg")
    root = tk.Tk()
    window = CachedPicturesWindow(
        root,
        lambda: list_cached_pictures(cache_dir, [_url_entry(url_a), _url_entry(url_b)]),
        cache_dir,
    )
    try:
        root.update()
        assert window._picture_list.size() == 1
        _write_picture(cache_dir, f"{web_source_stem(url_b)}.jpg")
        assert window.refresh() is True
        root.update()
        assert window._picture_list.size() == 2
        assert "2 cached web source pictures" in window._header_var.get()
        assert "The cache list was refreshed." in window._status_var.get()
        # The selection follows the surviving picture (now second, newest first).
        assert f"{web_source_stem(url_a)}.jpg" in window._picture_list.get(1)
        assert window._picture_list.curselection() == (1,)
        # A no-op refresh reports no change and keeps the selection.
        assert window.refresh() is False
        assert window._picture_list.curselection() == (1,)
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_open_picture_calls_desktop_opener(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")
    opened: list[Path] = []

    def fake_open(target: Path, *, failure_subject: str, recovery: str) -> Path:
        opened.append(target)
        return target

    monkeypatch.setattr("mint_background_switcher.cached_pictures.open_desktop_target", fake_open)
    root = tk.Tk()
    window = CachedPicturesWindow(
        root,
        lambda: list_cached_pictures(cache_dir, [_url_entry(url)]),
        cache_dir,
    )
    try:
        root.update()
        window._open_selected()
        _pump_until(root, lambda: window._status_var.get().startswith("Selected "))
        assert opened == [cache_dir / f"{web_source_stem(url)}.jpg"]
        assert "could not be opened" not in window._status_var.get()
        # Re-entry while a launch is in flight is ignored, not stacked.
        window._opening = True
        window._open_selected()
        assert len(opened) == 1
        window._opening = False
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_loader_failure_is_actionable(tmp_path):
    def boom() -> list:
        raise ValueError("no config")

    root = tk.Tk()
    window = CachedPicturesWindow(root, boom, tmp_path / "cache" / "web_sources")
    try:
        root.update()
        assert "The cache could not be listed." in window._status_var.get()
        assert window._picture_list.size() == 0
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_open_missing_file_reports_error(tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    url = "https://example.com/pic.jpg"
    picture = _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")
    root = tk.Tk()
    window = CachedPicturesWindow(
        root,
        lambda: list_cached_pictures(cache_dir, [_url_entry(url)]),
        cache_dir,
    )
    try:
        root.update()
        picture.unlink()  # pruned by a refresh after the list was drawn
        window._open_selected()
        _pump_until(root, lambda: "could not be opened" in window._status_var.get())
        assert "missing" in window._status_var.get()
        # The window is still usable after the failed open.
        assert "disabled" not in window._open_button.state()
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_cached_pictures_window_open_folder_calls_opener_with_cache_dir(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache" / "web_sources"
    url = "https://example.com/pic.jpg"
    _write_picture(cache_dir, f"{web_source_stem(url)}.jpg")
    opened: list[Path] = []

    def fake_open(target: Path, *, failure_subject: str, recovery: str) -> Path:
        opened.append(target)
        return target

    monkeypatch.setattr("mint_background_switcher.cached_pictures.open_desktop_target", fake_open)
    root = tk.Tk()
    window = CachedPicturesWindow(
        root,
        lambda: list_cached_pictures(cache_dir, [_url_entry(url)]),
        cache_dir,
    )
    try:
        root.update()
        window._open_selected(containing_folder=True)
        _pump_until(root, lambda: window._status_var.get().startswith("Selected "))
        assert opened == [cache_dir]
    finally:
        window.destroy()
        root.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_standalone_cached_pictures_gui_exits_when_window_closed(monkeypatch, tmp_path):
    """The cached-pictures process must terminate once the window is closed."""

    from mint_background_switcher import cached_pictures as cp

    _seed_web_source(monkeypatch, tmp_path, "https://example.com/pic.jpg")
    original_init = cp.CachedPicturesWindow.__init__

    def auto_close(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.after(200, self.destroy)

    monkeypatch.setattr(cp.CachedPicturesWindow, "__init__", auto_close)

    # The CLI runs the GUI on the process's main thread, so test that
    # documented launch path: Tcl 8.6 (Python <= 3.13) cannot host a second
    # Tk interpreter on a worker thread, and a worker-thread root aborts the
    # test process on CI.
    started = time.monotonic()
    assert cp.run_cached_pictures_gui() == 0
    assert time.monotonic() - started < 10


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_cached_pictures_button_opens_browser_from_sources_tab(monkeypatch, tmp_path):
    url = "https://example.com/pic.jpg"
    cache_dir = _seed_web_source(monkeypatch, tmp_path, url)
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        app.notebook.select(app.sources_tab)
        app.update()
        assert app.web_cached_pictures_button.cget("text") == "Cached Pictures..."
        assert app.web_cached_pictures_button.winfo_ismapped()

        app.web_cached_pictures_button.invoke()
        _pump_until(app, lambda: getattr(app, "_cached_pictures_window", None) is not None)
        window = app._cached_pictures_window
        app.update()
        assert window is not None and window.winfo_exists()
        assert window.title() == BROWSER_TITLE
        assert window._picture_list.size() == 1
        assert f"{web_source_stem(url)}.jpg" in window._picture_list.get(0)
        assert cache_dir.name in window._header_var.get()

        # Re-invoking focuses the existing window instead of stacking another one.
        before = app.winfo_children()
        app.web_cached_pictures_button.invoke()
        app.update()
        assert app._cached_pictures_window is window
        assert before == app.winfo_children()
    finally:
        app.destroy()


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display or Xvfb")
def test_settings_cached_pictures_button_empty_cache_still_opens(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    from mint_background_switcher.config import load_config, save_config

    load_config()
    save_config(load_config())  # configured but with no web sources
    monkeypatch.setattr(settings_ui, "detect_monitors", lambda: [])
    app = settings_ui.SettingsApp()
    try:
        app.update_idletasks()
        app.update()
        app.notebook.select(app.sources_tab)
        app.update()
        app.web_cached_pictures_button.invoke()
        _pump_until(app, lambda: getattr(app, "_cached_pictures_window", None) is not None)
        window = app._cached_pictures_window
        app.update()
        assert window is not None and window.winfo_exists()
        assert window._picture_list.size() == 0
        assert window._status_var.get() == EMPTY_HINT
    finally:
        app.destroy()
