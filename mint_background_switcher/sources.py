"""Web picture sources: the extension point for non-folder picture sources.

This release ships the first provider: direct image URLs. Each profile can
list up to ``MAX_WEB_SOURCES`` ``http(s)`` URLs, each pointing at one image
file. On every switch the sources are resolved to cached copies under the
working directory's ``web_sources`` folder, and the cached files join the
rotation pool exactly like a local folder.

Design notes:

* Sources are fail-open: an unreachable, oversized, or non-image URL is
  reported for that source and never blocks rotation. If a URL was already
  downloaded, its cached copy keeps rotating while the URL is offline.
* Each URL is re-downloaded at most once per ``WEB_SOURCE_REFRESH_HOURS``;
  ``force_refresh`` re-downloads immediately.
* Dry runs never touch the network or the cache.
* Cache files are named ``<sha256(url) prefix>.<ext>``. Files for URLs that
  are no longer configured are pruned so removed sources stop rotating.
* Future providers (RSS feeds, image search) plug in through the same
  per-profile ``web_sources`` entry list and cache directory; the rotation
  pipeline only ever sees local folders, so adding a provider never touches
  it again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

from PIL import Image

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from .config import Profile

WEB_SOURCE_TYPE = "url"
WEB_SOURCE_DIRNAME = "web_sources"
MAX_WEB_SOURCES = 20
MAX_WEB_SOURCE_URL_LENGTH = 2048
WEB_SOURCE_REFRESH_HOURS = 24.0
WEB_SOURCE_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
WEB_SOURCE_TIMEOUT_SECONDS = 30
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
    status: str  # "cached" | "refreshed" | "stale-kept" | "failed" | "skipped"
    path: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "status": self.status, "path": self.path, "detail": self.detail}


def validate_web_url(raw: Any) -> str | None:
    """Normalize and validate a direct image URL.

    Returns the stripped URL when it is a plausible http(s) direct image URL,
    or None when it is unusable. Strict on purpose: sources must be direct
    file URLs, and garbage in the config must never reach the downloader.
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
        entries.append({"type": WEB_SOURCE_TYPE, "url": url})
    return entries


def web_source_cache_dir(working_directory: Path | str) -> Path:
    return Path(working_directory) / WEB_SOURCE_DIRNAME


def web_source_stem(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def _describe_error(exc: Exception, url: str) -> str:
    reason = str(exc) or exc.__class__.__name__
    return f"{reason} ({url})"


def _fetch_url(url: str) -> bytes:
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
            if total > WEB_SOURCE_MAX_DOWNLOAD_BYTES:
                raise WebSourceFetchError(
                    f"image exceeds {WEB_SOURCE_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MiB ({url})"
                )
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
        _prune_removed_source_files(cache_dir, {web_source_stem(entry["url"]) for entry in entries})
    return results
