"""Web picture sources: URL validation, config coercion, and refresh behavior."""

import io
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher.config import Profile
from mint_background_switcher.sources import (
    MAX_WEB_SOURCES,
    WEB_FEED_TYPE,
    WebSourceCancelled,
    WebSourceFetchError,
    coerce_web_sources,
    extract_feed_image_urls,
    refresh_web_sources,
    validate_web_url,
    web_source_cache_dir,
    web_source_stem,
)


def _png_bytes(color=(10, 200, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _feed_xml(items: list[str]) -> bytes:
    """Build a minimal RSS 2.0 feed with one image enclosure per item."""
    body = "\n".join(
        f"<item><title>item {index}</title><enclosure url=\"{url}\" type=\"image/jpeg\" length=\"1\"/></item>"
        for index, url in enumerate(items)
    )
    return f"<rss version=\"2.0\"><channel>{body}</channel></rss>".encode()


def _profile_with(*entries: dict) -> Profile:
    return Profile(name="P", shared_folders=[], web_sources=list(entries))


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


def test_coerce_web_sources_keeps_feed_type():
    entries = coerce_web_sources(
        [
            {"type": WEB_FEED_TYPE, "url": "https://example.com/feed.rss"},
            {"type": WEB_FEED_TYPE, "url": "https://example.com/feed.rss"},  # de-duped
            {"type": "url", "url": "https://example.com/a.jpg"},
            {"type": "bogus", "url": "https://example.com/b.jpg"},  # unknown -> direct URL
        ]
    )
    assert entries == [
        {"type": WEB_FEED_TYPE, "url": "https://example.com/feed.rss"},
        {"type": "url", "url": "https://example.com/a.jpg"},
        {"type": "url", "url": "https://example.com/b.jpg"},
    ]


def test_extract_feed_image_urls_rss_enclosures_in_order():
    feed = _feed_xml(
        ["https://example.com/one.jpg", "https://example.com/two.jpg", "https://example.com/three.jpg"]
    )
    urls = extract_feed_image_urls(feed, "https://example.com/feed.rss")
    assert urls == [
        "https://example.com/one.jpg",
        "https://example.com/two.jpg",
        "https://example.com/three.jpg",
    ]


def test_extract_feed_image_urls_atom_media_content_and_thumbnail():
    atom = (
        b'<feed xmlns="http://www.w3.org/2005/Atom" '
        b'xmlns:media="http://search.yahoo.com/mrss/">'
        b"<entry>"
        b'<media:content url="https://example.com/a.png" type="image/png"/>'
        b"</entry>"
        b"<entry>"
        b'<media:thumbnail url="https://example.com/b.webp"/>'
        b"</entry>"
        b"<entry><title>no picture</title></entry>"
        b"</feed>"
    )
    urls = extract_feed_image_urls(atom, "https://example.com/feed")
    assert urls == ["https://example.com/a.png", "https://example.com/b.webp"]


def test_extract_feed_image_urls_falls_back_to_img_in_description():
    feed = (
        b"<rss version=\"2.0\"><channel><item>"
        b"<description>see &lt;img src=&quot;https://example.com/shot.jpg&quot; alt=&quot;x&quot;/&gt; there</description>"
        b"</item></channel></rss>"
    )
    assert extract_feed_image_urls(feed, "https://example.com/feed.rss") == [
        "https://example.com/shot.jpg"
    ]


def test_extract_feed_image_urls_enclosure_beats_description():
    feed = (
        b"<rss version=\"2.0\"><channel><item>"
        b'<enclosure url="https://example.com/main.jpg" type="image/jpeg"/>'
        b"<description>&lt;img src='https://example.com/inline.png'/&gt;</description>"
        b"</item></channel></rss>"
    )
    assert extract_feed_image_urls(feed, "https://example.com/feed.rss") == ["https://example.com/main.jpg"]


def test_extract_feed_image_urls_finds_img_in_content_encoded():
    feed = (
        b'<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        b"<channel><item>"
        b"<title>post</title>"
        b"<content:encoded><![CDATA[<p>text</p><img src=\"https://example.com/full.jpg\"/>]]></content:encoded>"
        b"</item></channel></rss>"
    )
    assert extract_feed_image_urls(feed, "https://example.com/feed.rss") == [
        "https://example.com/full.jpg"
    ]


def test_extract_feed_image_urls_resolves_relative_and_drops_unusable():
    feed = (
        b"<rss version=\"2.0\"><channel>"
        b'<item><enclosure url="pictures/rel.jpg" type="image/jpeg"/></item>'
        b'<item><enclosure url="file:///tmp/local.png" type="image/png"/></item>'
        b'<item><enclosure url="https://example.com/ok.webp" type="image/webp"/></item>'
        b"</channel></rss>"
    )
    urls = extract_feed_image_urls(feed, "https://example.com/feed.rss")
    assert urls == ["https://example.com/pictures/rel.jpg", "https://example.com/ok.webp"]


def test_extract_feed_image_urls_dedupes_and_bounds_limit():
    many = [f"https://example.com/p{i}.jpg" for i in range(15)]
    many.insert(0, many[-1])  # duplicate of a later item
    feed = _feed_xml(many)
    urls = extract_feed_image_urls(feed, "https://example.com/feed.rss")
    assert len(urls) == 10
    assert len(set(urls)) == 10
    assert urls[0] == many[0]


def test_extract_feed_image_urls_malformed_or_empty_feed():
    assert extract_feed_image_urls(b"<rss><channel>", "https://example.com/feed.rss") == []
    assert extract_feed_image_urls(b"", "https://example.com/feed.rss") == []
    plain = b"<rss version=\"2.0\"><channel><item><title>no image</title></item></channel></rss>"
    assert extract_feed_image_urls(plain, "https://example.com/feed.rss") == []


def test_refresh_feed_downloads_listed_images(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    img_b = "https://example.com/b.png"
    fetcher = _FakeFetcher(
        **{feed_url: _feed_xml([img_a, img_b]), img_a: _png_bytes(), img_b: _png_bytes(color=(0, 200, 0))}
    )
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["refreshed"]
    assert "2 image(s) listed, 2 downloaded" in statuses[0].detail
    cache_dir = web_source_cache_dir(tmp_path)
    names = sorted(p.name for p in cache_dir.iterdir())
    assert names == sorted(
        [web_source_stem(img_a) + ".png", web_source_stem(img_b) + ".png", feed_stem_sidecar_name(feed_url)]
    )
    assert fetcher.calls == [feed_url, img_a, img_b]


def feed_stem_sidecar_name(feed_url: str) -> str:
    from mint_background_switcher.sources import FEED_SIDECAR_SUFFIX

    return web_source_stem(feed_url) + FEED_SIDECAR_SUFFIX


def test_refresh_feed_within_window_is_cached_without_fetching(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert fetcher.calls == [feed_url, img_a]

    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}),
        tmp_path,
        fetch=fetcher,
        now=1000.0 + 3600.0,
    )
    assert [s.status for s in statuses] == ["cached"]
    assert "1 image(s) cached" in statuses[0].detail
    assert fetcher.calls == [feed_url, img_a]  # no re-fetch inside the window


def test_refresh_feed_force_refresh_keeps_still_listed_images(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    profile = _profile_with({"type": WEB_FEED_TYPE, "url": feed_url})
    refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0)

    statuses = refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0 + 90_000.0, force_refresh=True)
    assert [s.status for s in statuses] == ["refreshed"]
    assert "1 image(s) listed, 0 downloaded, 1 kept" in statuses[0].detail
    assert fetcher.calls == [feed_url, img_a, feed_url]  # feed refetched, image not


def test_refresh_feed_prunes_images_dropped_from_feed(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    img_b = "https://example.com/b.png"
    fetcher = _FakeFetcher(
        **{feed_url: _feed_xml([img_a, img_b]), img_a: _png_bytes(), img_b: _png_bytes(color=(0, 200, 0))}
    )
    profile = _profile_with({"type": WEB_FEED_TYPE, "url": feed_url})
    refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0)
    cache_dir = web_source_cache_dir(tmp_path)
    assert (cache_dir / (web_source_stem(img_b) + ".png")).is_file()

    # the feed now only lists img_a; img_b's cache file is pruned
    fetcher.by_url[feed_url] = _feed_xml([img_a])
    statuses = refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0 + 90_000.0, force_refresh=True)
    assert [s.status for s in statuses] == ["refreshed"]
    assert not (cache_dir / (web_source_stem(img_b) + ".png")).is_file()
    assert (cache_dir / (web_source_stem(img_a) + ".png")).is_file()


def test_refresh_feed_removed_from_profile_prunes_sidecar_and_images(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    cache_dir = web_source_cache_dir(tmp_path)
    assert (cache_dir / feed_stem_sidecar_name(feed_url)).is_file()

    # profile no longer lists the feed: a subsequent refresh prunes its files
    statuses = refresh_web_sources(_profile_with(), tmp_path, fetch=fetcher, now=1000.0)
    assert statuses == []
    assert not (cache_dir / feed_stem_sidecar_name(feed_url)).is_file()
    assert not (cache_dir / (web_source_stem(img_a) + ".png")).is_file()


def test_refresh_feed_removed_keeps_image_also_listed_directly(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    profile = _profile_with(
        {"type": WEB_FEED_TYPE, "url": feed_url},
        {"type": "url", "url": img_a},  # the same picture is also a direct source
    )
    refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0)
    cache_dir = web_source_cache_dir(tmp_path)
    image_file = cache_dir / (web_source_stem(img_a) + ".png")
    assert image_file.is_file()

    # the feed is removed but the direct URL stays: its picture must survive
    statuses = refresh_web_sources(
        _profile_with({"type": "url", "url": img_a}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["cached"]
    assert image_file.is_file()
    assert not (cache_dir / feed_stem_sidecar_name(feed_url)).is_file()


def test_refresh_feed_removed_keeps_image_still_listed_by_other_feed(tmp_path):
    feed_a = "https://example.com/feed-a.rss"
    feed_b = "https://example.com/feed-b.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(
        **{
            feed_a: _feed_xml([img_a]),
            feed_b: _feed_xml([img_a]),
            img_a: _png_bytes(),
        }
    )
    profile = _profile_with(
        {"type": WEB_FEED_TYPE, "url": feed_a},
        {"type": WEB_FEED_TYPE, "url": feed_b},
    )
    refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0)
    cache_dir = web_source_cache_dir(tmp_path)
    image_file = cache_dir / (web_source_stem(img_a) + ".png")
    assert image_file.is_file()

    # feed A is removed but feed B still lists the same picture: it must survive
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_b}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["cached"]
    assert image_file.is_file()
    assert not (cache_dir / feed_stem_sidecar_name(feed_a)).is_file()


def test_refresh_feed_offline_keeps_stale_images(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    profile = _profile_with({"type": WEB_FEED_TYPE, "url": feed_url})
    first = refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0)
    assert first[0].status == "refreshed"

    fetcher.by_url[feed_url] = WebSourceFetchError("connection timed out")
    statuses = refresh_web_sources(profile, tmp_path, fetch=fetcher, now=1000.0 + 90_000.0, force_refresh=True)
    assert [s.status for s in statuses] == ["stale-kept"]
    assert "connection timed out" in statuses[0].detail
    assert (web_source_cache_dir(tmp_path) / (web_source_stem(img_a) + ".png")).is_file()


def test_refresh_feed_empty_feed_reports_empty(tmp_path):
    feed_url = "https://example.com/feed.rss"
    fetcher = _FakeFetcher(
        **{feed_url: b"<rss version=\"2.0\"><channel><item><title>words only</title></item></channel></rss>"}
    )
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["empty"]
    assert "no image URLs" in statuses[0].detail


def test_refresh_feed_dry_run_never_fetches(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([img_a]), img_a: _png_bytes()})
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, dry_run=True, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["skipped"]
    assert fetcher.calls == []
    assert not web_source_cache_dir(tmp_path).exists()

    refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, dry_run=True, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["cached"]
    assert "1 image(s) cached" in statuses[0].detail


def test_refresh_feed_image_failure_reported_but_others_downloaded(tmp_path):
    feed_url = "https://example.com/feed.rss"
    img_a = "https://example.com/a.jpg"
    img_b = "https://example.com/b.png"
    fetcher = _FakeFetcher(
        **{
            feed_url: _feed_xml([img_a, img_b]),
            img_a: _png_bytes(),
            img_b: WebSourceFetchError("boom"),
        }
    )
    statuses = refresh_web_sources(
        _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}), tmp_path, fetch=fetcher, now=1000.0
    )
    assert [s.status for s in statuses] == ["refreshed"]
    assert "1 downloaded" in statuses[0].detail
    assert "1 failed: boom" in statuses[0].detail
    cache_dir = web_source_cache_dir(tmp_path)
    assert (cache_dir / (web_source_stem(img_a) + ".png")).is_file()
    assert not any(p.name.startswith(web_source_stem(img_b)) for p in cache_dir.iterdir())


def test_refresh_feed_raises_when_cancelled(tmp_path):
    feed_url = "https://example.com/feed.rss"
    fetcher = _FakeFetcher(**{feed_url: _feed_xml([])})
    with pytest.raises(WebSourceCancelled):
        refresh_web_sources(
            _profile_with({"type": WEB_FEED_TYPE, "url": feed_url}),
            tmp_path,
            fetch=fetcher,
            now=1000.0,
            cancelled=lambda: True,
        )
    assert fetcher.calls == []
