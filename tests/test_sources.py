"""Web picture sources: URL validation, config coercion, and refresh behavior."""

import io
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher.config import Profile
from mint_background_switcher.sources import (
    MAX_WEB_SOURCES,
    WebSourceCancelled,
    WebSourceFetchError,
    coerce_web_sources,
    refresh_web_sources,
    validate_web_url,
    web_source_cache_dir,
    web_source_stem,
)


def _png_bytes(color=(10, 200, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeFetcher:
    """Callable fetcher with scripted per-URL responses; records call order."""

    def __init__(self, **by_url):
        self.by_url = by_url
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.by_url:
            raise WebSourceFetchError(f"no scripted response ({url})")
        value = self.by_url[url]
        if isinstance(value, Exception):
            raise value
        return value


def _profile(*urls: str) -> Profile:
    return Profile(
        name="P",
        shared_folders=[],
        web_sources=[{"type": "url", "url": url} for url in urls],
    )


def test_validate_web_url_accepts_direct_image_urls():
    assert validate_web_url("https://example.com/pic.jpg") == "https://example.com/pic.jpg"
    assert validate_web_url("http://localhost:8080/x.png") == "http://localhost:8080/x.png"
    assert validate_web_url("  https://Example.com/a/b.webp  ") == "https://Example.com/a/b.webp"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url",
        "ftp://example.com/x.jpg",
        "https://",
        "https:///x.jpg",
        "https://example.com/x .jpg",
        "https://user:pass@example.com/x.jpg",
        "https://[::1]/x.jpg",
        "https://example.com:0/x.jpg",
        "https://example.com:99999/x.jpg",
        "https://example.com:port/x.jpg",
        "https://-bad-.com/x.jpg",
        "https://example.com/x.jpg" + "a" * 2048,
        None,
        1234,
    ],
)
def test_validate_web_url_rejects_unusable_urls(raw):
    assert validate_web_url(raw) is None


def test_coerce_web_sources_drops_invalid_and_dedupes():
    entries = coerce_web_sources(
        [
            "nope",
            {"url": "ftp://example.com/x.jpg"},
            {"url": "https://example.com/ok.png"},
            {"url": "https://example.com/ok.png"},
            {"no_url_key": True},
        ]
    )
    assert entries == [{"type": "url", "url": "https://example.com/ok.png"}]


def test_coerce_web_sources_handles_non_lists_and_caps_count():
    assert coerce_web_sources(None) == []
    assert coerce_web_sources("https://example.com/x.jpg") == []
    urls = [f"https://example.com/p{i}.jpg" for i in range(MAX_WEB_SOURCES + 5)]
    entries = coerce_web_sources([{"url": url} for url in urls] * 2)
    assert len(entries) == MAX_WEB_SOURCES
    assert [entry["url"] for entry in entries] == urls[:MAX_WEB_SOURCES]


def test_profile_web_sources_round_trip_and_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    from mint_background_switcher.config import Config, load_config, save_config

    save_config(
        Config(
            active_profile="P",
            profiles={"P": _profile("https://example.com/a.jpg")},
        )
    )
    loaded = load_config()
    assert loaded.get_profile("P").web_sources == [{"type": "url", "url": "https://example.com/a.jpg"}]

    fresh = Profile(name="Q")
    assert fresh.web_sources == []
    assert fresh.to_dict()["web_sources"] == []
    assert Profile.from_dict("Q", fresh.to_dict()).web_sources == []


def test_refresh_downloads_caches_and_respects_freshness_window(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: _png_bytes()})
    statuses = refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["refreshed"]
    assert fetcher.calls == [url]
    assert statuses[0].path is not None
    cached = Path(statuses[0].path)
    assert cached.is_file()
    assert cached.parent == web_source_cache_dir(tmp_path)
    assert cached.name == web_source_stem(url) + ".png"

    # within the 24-hour window the cached copy is reused without fetching
    statuses = refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0 + 3600.0)
    assert [s.status for s in statuses] == ["cached"]
    assert fetcher.calls == [url]

    # force_refresh re-downloads immediately
    statuses = refresh_web_sources(
        _profile(url), tmp_path, fetch=fetcher, now=1000.0 + 3600.0, force_refresh=True
    )
    assert [s.status for s in statuses] == ["refreshed"]
    assert fetcher.calls == [url, url]


def test_refresh_dry_run_never_fetches_or_writes(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: _png_bytes()})
    statuses = refresh_web_sources(_profile(url), tmp_path, dry_run=True, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["skipped"]
    assert fetcher.calls == []
    assert not web_source_cache_dir(tmp_path).exists()

    # after a real download the dry run reports the cache without touching it
    refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0)
    before = sorted(p.name for p in web_source_cache_dir(tmp_path).iterdir())
    statuses = refresh_web_sources(_profile(url), tmp_path, dry_run=True, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["cached"]
    assert fetcher.calls == [url]
    after = sorted(p.name for p in web_source_cache_dir(tmp_path).iterdir())
    assert before == after == [web_source_stem(url) + ".png"]


def test_refresh_failure_keeps_stale_cache(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: _png_bytes()})
    first = refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0)
    assert first[0].path is not None
    stale_path = Path(first[0].path)
    assert stale_path.is_file()

    # the URL goes offline after the freshness window; the cached copy survives
    fetcher.by_url[url] = WebSourceFetchError("connection timed out")
    statuses = refresh_web_sources(
        _profile(url), tmp_path, fetch=fetcher, now=1000.0 + 90_000.0, force_refresh=True
    )
    assert [s.status for s in statuses] == ["stale-kept"]
    assert statuses[0].path == str(stale_path)
    assert "connection timed out" in statuses[0].detail
    assert stale_path.is_file()


def test_refresh_failure_without_cache_reports_failed(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: WebSourceFetchError("DNS failure")})
    statuses = refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["failed"]
    assert "DNS failure" in statuses[0].detail
    assert statuses[0].path is None
    assert not web_source_cache_dir(tmp_path).exists()


def test_refresh_rejects_non_image_download(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: b"this is not an image"})
    statuses = refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["failed"]
    assert "not a decodable image" in statuses[0].detail
    assert not web_source_cache_dir(tmp_path).exists()


def test_refresh_prunes_removed_sources_and_keeps_unrelated_files(tmp_path):
    url_a = "https://example.com/a.jpg"
    url_b = "https://example.com/b.png"
    fetcher = _FakeFetcher(**{url_a: _png_bytes(), url_b: _png_bytes(color=(0, 0, 250))})
    refresh_web_sources(_profile(url_a, url_b), tmp_path, fetch=fetcher, now=1000.0)
    cache_dir = web_source_cache_dir(tmp_path)
    unrelated = cache_dir / "notes.txt"
    unrelated.write_text("keep me")
    assert len(list(cache_dir.iterdir())) == 3

    # removing url_b from the profile prunes its cache file on the next refresh
    statuses = refresh_web_sources(_profile(url_a), tmp_path, fetch=fetcher, now=1000.0)
    assert [s.status for s in statuses] == ["cached"]
    remaining = sorted(p.name for p in cache_dir.iterdir())
    assert remaining == sorted([web_source_stem(url_a) + ".png", "notes.txt"])


def test_refresh_raises_when_cancelled_before_downloading(tmp_path):
    url = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{url: _png_bytes()})
    with pytest.raises(WebSourceCancelled):
        refresh_web_sources(_profile(url), tmp_path, fetch=fetcher, now=1000.0, cancelled=lambda: True)
    assert fetcher.calls == []
    assert not web_source_cache_dir(tmp_path).exists()
