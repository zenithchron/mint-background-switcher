"""Web picture sources: the extension point for non-folder picture sources.

Two providers are shipped: direct image URLs and RSS/Atom picture feeds.
Each profile can list up to ``MAX_WEB_SOURCES`` ``http(s)`` entries, where
an entry either points at one image file (``type == "url"``) or at an
RSS/Atom feed whose items carry pictures (``type == "feed"``). On every
switch the sources are resolved to cached copies under the working
directory's ``web_sources`` folder, and the cached files join the rotation
pool exactly like a local folder.

Design notes:

* Sources are fail-open: an unreachable, oversized, or non-image URL is
  reported for that source and never blocks rotation. If a URL was already
  downloaded, its cached copy keeps rotating while the URL is offline.
* Each URL is re-downloaded at most once per ``WEB_SOURCE_REFRESH_HOURS``;
  ``force_refresh`` re-downloads immediately. A feed is re-fetched on the
  same window; pictures that are still listed are kept, new ones are
  downloaded, and pictures the feed no longer lists are pruned.
* Feed extraction is one picture per item, in feed order: an image
  ``enclosure``, then ``media:content``, then ``media:thumbnail``, then the
  first ``<img>`` in the item's content/description. Relative URLs resolve
  against the feed URL; non-http(s) URLs are dropped.
* Dry runs never touch the network or the cache.
* Cache files are named ``<sha256(url) prefix>.<ext>``. Files for URLs that
  are no longer configured are pruned so removed sources stop rotating.
  Feed ownership is tracked in a ``<stem>.images.json`` sidecar so only the
  feed that listed a picture can prune it.
* Future providers (image search) plug in through the same per-profile
  ``web_sources`` entry list and cache directory; the rotation pipeline
  only ever sees local folders, so adding a provider never touches it again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from PIL import Image

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from .config import Profile

WEB_SOURCE_TYPE = "url"
WEB_FEED_TYPE = "feed"
WEB_SOURCE_DIRNAME = "web_sources"
MAX_WEB_SOURCES = 20
MAX_WEB_SOURCE_URL_LENGTH = 2048
WEB_SOURCE_REFRESH_HOURS = 24.0
WEB_SOURCE_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
WEB_SOURCE_TIMEOUT_SECONDS = 30
RSS_MAX_IMAGES_PER_FEED = 10
FEED_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
FEED_SIDECAR_SUFFIX = ".images.json"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
USER_AGENT = "MintBackgroundSwitcher/0.2 (+https://github.com/zenithchron/mint-background-switcher)"

# Mirrors images.SUPPORTED_EXTENSIONS (importing images here would cycle
# through config).
_SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)
_FORMAT_EXTENSIONS = {
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "bmp": ".bmp",
    "gif": ".gif",
    "tiff": ".tiff",
}
_HOSTNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_CACHE_FILE_RE = re.compile(
    r"^[0-9a-f]{20}\.(?:jpg|jpeg|png|webp|bmp|gif|tif|tiff)$", re.IGNORECASE
)
_STEM_RE = re.compile(r"^[0-9a-f]{20}$")
_FEED_SIDECAR_RE = re.compile(r"^[0-9a-f]{20}\.images\.json$")
_IMG_TAG_RE = re.compile(r"<img[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


class WebSourceError(RuntimeError):
    """A web source could not be resolved."""


class WebSourceCancelled(WebSourceError):
    """The user cancelled a web source refresh."""


class WebSourceFetchError(WebSourceError):
    """A single URL could not be downloaded or is not a usable image."""


@dataclass(frozen=True, slots=True)
class WebSourceStatus:
    """Outcome of resolving one configured web source to a cached file."""

    url: str
    status: str  # "cached" | "refreshed" | "stale-kept" | "failed" | "skipped" | "empty"
    path: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "status": self.status, "path": self.path, "detail": self.detail}


def validate_web_url(raw: Any) -> str | None:
    """Normalize and validate a web source URL (direct image URL or RSS/Atom feed).

    Returns the stripped URL when it is a plausible http(s) web source URL,
    or None when it is unusable. Strict on purpose: sources must be http(s)
    URLs, and garbage in the config must never reach the downloader.
    """
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > MAX_WEB_SOURCE_URL_LENGTH:
        return None
    if any(ch.isspace() or ord(ch) < 0x20 for ch in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    netloc = parts.netloc
    if not netloc or len(netloc) > 255 or "@" in netloc or " " in netloc:
        return None
    if netloc.startswith("["):
        return None  # IPv6 literal URLs are not supported
    hostname, sep, port = netloc.rpartition(":")
    if sep:
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            return None
    else:
        hostname = netloc
    if not hostname or len(hostname) > 253 or not _HOSTNAME_RE.fullmatch(hostname):
        return None
    return url


def coerce_web_sources(value: Any) -> list[dict[str, str]]:
    """Normalize a config ``web_sources`` list: validate, de-dupe, bound count."""
    if not isinstance(value, list):
        return []
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if len(entries) >= MAX_WEB_SOURCES:
            break
        if not isinstance(item, dict):
            continue
        url = validate_web_url(item.get("url"))
        if url is None or url in seen:
            continue
        seen.add(url)
        kind = WEB_FEED_TYPE if item.get("type") == WEB_FEED_TYPE else WEB_SOURCE_TYPE
        entries.append({"type": kind, "url": url})
    return entries


def web_source_cache_dir(working_directory: Path | str) -> Path:
    return Path(working_directory) / WEB_SOURCE_DIRNAME


def web_source_stem(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def _describe_error(exc: Exception, url: str) -> str:
    reason = str(exc) or exc.__class__.__name__
    return f"{reason} ({url})"


def _fetch_url(url: str, max_bytes: int = WEB_SOURCE_MAX_DOWNLOAD_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=WEB_SOURCE_TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise WebSourceFetchError(_describe_error(exc, url)) from exc
    chunks: list[bytes] = []
    total = 0
    with response:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise WebSourceFetchError(f"content exceeds {max_bytes // (1024 * 1024)} MiB ({url})")
            chunks.append(chunk)
    return b"".join(chunks)


def _decode_check(data: bytes) -> str | None:
    """Return a supported cache extension for decodable image bytes, else None."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            format_name = (image.format or "").lower()
    except Exception:
        return None
    extension = _FORMAT_EXTENSIONS.get(format_name)
    return extension if extension in _SUPPORTED_IMAGE_EXTENSIONS else None


def _find_existing(cache_dir: Path, stem: str) -> Path | None:
    try:
        candidates = [
            path
            for path in cache_dir.glob(f"{stem}.*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _atomic_write(cache_dir: Path, name: str, data: bytes) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / name
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".part", dir=cache_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def _prune_removed_source_files(cache_dir: Path, current_stems: set[str]) -> None:
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and _CACHE_FILE_RE.match(entry.name) and entry.name[:20] not in current_stems:
                entry.unlink()
        except OSError:
            continue


def _download(url: str, fetcher: Callable[[str], bytes]) -> tuple[bytes | None, str | None, str | None]:
    """Fetch one URL and decode-check the bytes. Returns (data, extension, error).

    A URL failure must never break rotation, so every failure path is a plain
    error string instead of an exception.
    """
    try:
        data = fetcher(url)
    except WebSourceFetchError as exc:
        return None, None, str(exc)
    except Exception as exc:
        return None, None, _describe_error(exc, url)
    extension = _decode_check(data)
    if extension is None:
        return None, None, f"download is not a decodable image of a supported type ({url})"
    return data, extension, None


def _local_tag(tag: object) -> str:
    """Element tag with any XML namespace stripped, or '' for non-elements."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _is_image_url(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path
    return Path(path).suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS


def _first_img_in_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _IMG_TAG_RE.search(text)
    return match.group(1) if match else None


def _item_image_url(item: ET.Element, feed_url: str) -> str | None:
    """Return the first plausible picture URL of one feed item, or None.

    Priority per item: image enclosure, then media:content, then
    media:thumbnail, then the first <img> in the item content/description
    (parsed CDATA elements or raw HTML text). Relative URLs resolve against
    the feed URL; the result must be a valid http(s) URL.
    """
    tiers: list[list[str]] = [[], [], [], []]
    for element in item.iter():
        tag = _local_tag(element.tag)
        if not tag or tag == "#comment":
            continue
        if tag == "enclosure":
            candidate = element.get("url")
            if candidate and ((element.get("type") or "").lower().startswith("image/") or _is_image_url(candidate)):
                tiers[0].append(candidate)
        elif tag in ("content", "encoded"):
            # media:content carries a url attribute; content:encoded (local tag
            # "encoded") and Atom content carry HTML (or CDATA-parsed elements)
            # whose <img> is the picture.
            candidate = element.get("url")
            if candidate and ((element.get("type") or "").lower().startswith("image/") or _is_image_url(candidate)):
                tiers[1].append(candidate)
            img = _first_img_in_text(element.text)
            if img:
                tiers[3].append(img)
        elif tag == "thumbnail":
            candidate = element.get("url")
            if candidate and _is_image_url(candidate):
                tiers[2].append(candidate)
        elif tag == "img":
            candidate = element.get("src")
            if candidate:
                tiers[3].append(candidate)
        elif tag == "description":
            img = _first_img_in_text(element.text)
            if img:
                tiers[3].append(img)
    for tier in tiers:
        if tier:
            resolved = urllib.parse.urljoin(feed_url, tier[0].strip())
            if validate_web_url(resolved) is not None:
                return resolved
    return None


def extract_feed_image_urls(
    data: bytes,
    feed_url: str,
    limit: int = RSS_MAX_IMAGES_PER_FEED,
) -> list[str]:
    """Parse RSS 2.0 / Atom XML and return picture URLs in feed order.

    One picture per ``<item>`` (RSS) or ``<entry>`` (Atom), newest first as
    feeds order their items, de-duplicated and bounded by ``limit``. Malformed
    XML and feeds without pictures yield an empty list — extraction is
    fail-open and never raises.
    """
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for element in root.iter():
        if _local_tag(element.tag) not in ("item", "entry"):
            continue
        if len(urls) >= limit:
            break
        url = _item_image_url(element, feed_url)
        if url is not None and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _feed_sidecar_path(cache_dir: Path, feed_url: str) -> Path:
    return cache_dir / f"{web_source_stem(feed_url)}{FEED_SIDECAR_SUFFIX}"


def _read_feed_sidecar(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {stem for stem in data if isinstance(stem, str) and _STEM_RE.match(stem)}


def _write_feed_sidecar(cache_dir: Path, feed_url: str, stems: list[str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _feed_sidecar_path(cache_dir, feed_url)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=cache_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stems, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _delete_stem_files(cache_dir: Path, stem: str) -> None:
    try:
        candidates = [
            path
            for path in cache_dir.glob(f"{stem}.*")
            if path.is_file() and path.suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS
        ]
    except OSError:
        return
    for path in candidates:
        try:
            path.unlink()
        except OSError:
            continue


def _refresh_feed_entry(
    feed_url: str,
    cache_dir: Path,
    *,
    dry_run: bool,
    force_refresh: bool,
    current: float,
    refresh_window: float,
    cancelled: Callable[[], bool] | None,
    fetcher: Callable[[str], bytes],
) -> WebSourceStatus:
    """Resolve one RSS/Atom feed entry to cached images. Never raises."""
    sidecar = _feed_sidecar_path(cache_dir, feed_url)
    old_stems = _read_feed_sidecar(sidecar)
    cached_files = [path for path in (_find_existing(cache_dir, stem) for stem in old_stems) if path is not None]
    if dry_run:
        if cached_files:
            return WebSourceStatus(feed_url, "cached", detail=f"{len(cached_files)} image(s) cached")
        return WebSourceStatus(feed_url, "skipped", detail="no cached copy yet; dry runs never download")
    if old_stems and not force_refresh:
        sidecar_age = current - sidecar.stat().st_mtime if sidecar.is_file() else None
        if sidecar_age is not None and sidecar_age < refresh_window and cached_files:
            return WebSourceStatus(feed_url, "cached", detail=f"{len(cached_files)} image(s) cached")
    if cancelled is not None and cancelled():
        raise WebSourceCancelled(f"cancelled before refreshing {feed_url}")
    feed_fetcher: Callable[[str], bytes]
    if fetcher is _fetch_url:
        feed_fetcher = lambda url: _fetch_url(url, FEED_MAX_DOWNLOAD_BYTES)
    else:
        feed_fetcher = fetcher
    try:
        feed_bytes = feed_fetcher(feed_url)
    except Exception as exc:
        error = str(exc) or _describe_error(exc, feed_url)
        if cached_files:
            newest = max(cached_files, key=lambda path: path.stat().st_mtime)
            return WebSourceStatus(feed_url, "stale-kept", str(newest), detail=error)
        return WebSourceStatus(feed_url, "failed", detail=error)
    image_urls = extract_feed_image_urls(feed_bytes, feed_url)
    if not image_urls:
        if cached_files:
            newest = max(cached_files, key=lambda path: path.stat().st_mtime)
            return WebSourceStatus(
                feed_url, "empty", str(newest), detail="feed lists no image URLs; cached copies kept"
            )
        return WebSourceStatus(feed_url, "empty", detail="feed lists no image URLs")
    new_stems = [web_source_stem(url) for url in image_urls]
    downloaded = 0
    failures: list[str] = []
    for url, stem in zip(image_urls, new_stems):
        existing = _find_existing(cache_dir, stem)
        if existing is not None:
            continue
        if cancelled is not None and cancelled():
            raise WebSourceCancelled(f"cancelled before refreshing {url}")
        data, extension, error = _download(url, fetcher)
        if error is not None:
            failures.append(error)
            continue
        assert data is not None and extension is not None  # guaranteed by _download
        _atomic_write(cache_dir, f"{stem}{extension}", data)
        downloaded += 1
    for stem in old_stems - set(new_stems):
        _delete_stem_files(cache_dir, stem)
    _write_feed_sidecar(cache_dir, feed_url, new_stems)
    kept = len(new_stems) - downloaded - len(failures)
    detail = f"{len(new_stems)} image(s) listed, {downloaded} downloaded, {kept} kept"
    if failures:
        detail += f", {len(failures)} failed: {failures[0]}"
    return WebSourceStatus(feed_url, "refreshed", detail=detail)


def refresh_web_sources(
    profile: "Profile",
    working_directory: Path | str,
    *,
    dry_run: bool = False,
    force_refresh: bool = False,
    cancelled: Callable[[], bool] | None = None,
    fetch: Callable[[str], bytes] | None = None,
    now: float | None = None,
) -> list[WebSourceStatus]:
    """Resolve each configured web source to a cached local image.

    Returns one status per configured source, in profile order. Individual
    URL failures never raise: they are reported as ``stale-kept`` (a previous
    cached copy survives) or ``failed`` (nothing to show). The only exception
    is ``WebSourceCancelled`` when ``cancelled`` reports a cancel request.

    ``dry_run`` reports cache state without any network access or file
    changes. ``force_refresh`` ignores the 24-hour freshness window.
    """
    entries = profile.web_sources
    cache_dir = web_source_cache_dir(Path(working_directory))
    fetcher = fetch or _fetch_url
    current = time.time() if now is None else now
    refresh_window = WEB_SOURCE_REFRESH_HOURS * 3600.0
    results: list[WebSourceStatus] = []
    for entry in entries:
        url = entry["url"]
        if entry["type"] == WEB_FEED_TYPE:
            results.append(
                _refresh_feed_entry(
                    url,
                    cache_dir,
                    dry_run=dry_run,
                    force_refresh=force_refresh,
                    current=current,
                    refresh_window=refresh_window,
                    cancelled=cancelled,
                    fetcher=fetcher,
                )
            )
            continue
        stem = web_source_stem(url)
        existing = _find_existing(cache_dir, stem)
        age = None if existing is None else current - existing.stat().st_mtime
        fresh = existing is not None and age is not None and age < refresh_window
        if dry_run:
            if existing is not None:
                results.append(WebSourceStatus(url, "cached", str(existing)))
            else:
                results.append(
                    WebSourceStatus(url, "skipped", detail="no cached copy yet; dry runs never download")
                )
            continue
        if fresh and not force_refresh:
            results.append(WebSourceStatus(url, "cached", str(existing)))
            continue
        if cancelled is not None and cancelled():
            raise WebSourceCancelled(f"cancelled before refreshing {url}")
        data, extension, error = _download(url, fetcher)
        if error is not None:
            if existing is not None:
                results.append(WebSourceStatus(url, "stale-kept", str(existing), detail=error))
            else:
                results.append(WebSourceStatus(url, "failed", detail=error))
            continue
        assert data is not None and extension is not None  # guaranteed by _download
        written = _atomic_write(cache_dir, f"{stem}{extension}", data)
        results.append(WebSourceStatus(url, "refreshed", str(written)))
    if not dry_run:
        _prune_web_source_cache(cache_dir, entries)
    return results


def _prune_web_source_cache(cache_dir: Path, entries: list[dict[str, str]]) -> None:
    """Drop cache files whose sources are no longer configured.

    Feed image files are only pruned through their owning feed's sidecar: a
    removed feed loses its sidecar and every image it listed. Unrelated
    files (other extensions, temp artifacts) are never touched.
    """
    try:
        all_entries = list(cache_dir.iterdir())
    except OSError:
        return
    direct_stems = {web_source_stem(entry["url"]) for entry in entries}
    live_feed_stems = {
        web_source_stem(entry["url"]) for entry in entries if entry["type"] == WEB_FEED_TYPE
    }
    sidecar_paths = [
        path for path in all_entries if path.is_file() and _FEED_SIDECAR_RE.match(path.name)
    ]
    # pictures still owned by a live feed must survive a sibling feed's removal
    live_feed_images: set[str] = set()
    for path in sidecar_paths:
        if path.name[:20] in live_feed_stems:
            live_feed_images |= _read_feed_sidecar(path)
    for path in sidecar_paths:
        if path.name[:20] in live_feed_stems:
            continue
        # feed no longer configured: drop the sidecar and its images, but never
        # a picture that is also listed as a direct URL or by another live feed
        for stem in _read_feed_sidecar(path) - direct_stems - live_feed_images:
            _delete_stem_files(cache_dir, stem)
        try:
            path.unlink()
        except OSError:
            continue
    _prune_removed_source_files(cache_dir, direct_stems | live_feed_images)
