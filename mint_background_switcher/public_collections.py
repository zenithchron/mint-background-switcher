"""Rights-filtered downloads from public image collections.

Downloads are always explicit, user-triggered, and installed into a selected local
folder.  The module never modifies an existing source image and records provenance
for every installed file in a sidecar manifest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import uuid4

from PIL import Image


NETWORK_TIMEOUT_SECONDS = 30
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MANIFEST_FILENAME = ".mbs-public-collection.json"
_USER_AGENT = "MintBackgroundSwitcher/0.1 (+https://github.com/zenithchron/mint-background-switcher)"
_ALLOWED_IMAGE_HOSTS = frozenset({"images-assets.nasa.gov", "upload.wikimedia.org"})
_ALLOWED_METADATA_HOSTS = frozenset(
    {"images-api.nasa.gov", "images-assets.nasa.gov", "commons.wikimedia.org"}
)
_ALLOWED_COMMONS_LICENSES = frozenset({"cc0", "public domain"})
_IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class CollectionDownloadError(RuntimeError):
    """Raised when a collection cannot be downloaded safely."""


class CollectionDownloadCancelled(CollectionDownloadError):
    """Raised when the user cancels a collection download."""


@dataclass(frozen=True)
class PublicCollection:
    slug: str
    name: str
    provider: str
    description: str
    source_url: str
    query: tuple[str, ...]
    category: str = ""


@dataclass(frozen=True)
class RecommendedSource:
    name: str
    description: str
    url: str


@dataclass(frozen=True)
class CollectionAsset:
    provider_id: str
    title: str
    creator: str
    source_url: str
    download_url: str
    license_name: str
    license_url: str
    extension: str


@dataclass(frozen=True)
class CollectionDownloadResult:
    collection: PublicCollection
    destination: Path
    manifest_path: Path
    image_paths: tuple[Path, ...]
    downloaded: int
    existing: int
    failed: int


PUBLIC_COLLECTIONS = (
    PublicCollection(
        "nasa-space",
        "NASA Space",
        "NASA",
        "Nebulae, galaxies, stars, and deep-space missions from NASA.",
        "https://images.nasa.gov/",
        ("nebula galaxy stars", "deep space telescope"),
    ),
    PublicCollection(
        "nasa-earth",
        "NASA Earth from Space",
        "NASA",
        "Earth, weather, oceans, and land photographed from orbit.",
        "https://images.nasa.gov/",
        ("earth from space", "earth orbit satellite"),
    ),
    PublicCollection(
        "commons-sunsets",
        "Public-Domain Sunsets",
        "Wikimedia Commons",
        "Sunset photographs restricted to files marked CC0 or public domain.",
        "https://commons.wikimedia.org/wiki/Category:Sunsets",
        (),
        "Sunsets",
    ),
    PublicCollection(
        "commons-insects",
        "Public-Domain Insects",
        "Wikimedia Commons",
        "Insect photographs restricted to files marked CC0 or public domain.",
        "https://commons.wikimedia.org/wiki/Category:Insects",
        (),
        "Insects",
    ),
    PublicCollection(
        "commons-us-national-parks",
        "Public-Domain National Parks — Alaska",
        "Wikimedia Commons",
        "Scenery and wildlife from the official NPS Alaska Region import, restricted to public-domain files.",
        "https://commons.wikimedia.org/wiki/Category:Files_from_the_National_Park_Service_Alaska_Region_Flickr_stream",
        (),
        "Files from the National Park Service Alaska Region Flickr stream",
    ),
)

RECOMMENDED_SOURCES = (
    RecommendedSource(
        "USDA ARS Insects",
        "Public-domain insect and agricultural photographs; no stable public image API.",
        "https://www.ars.usda.gov/oc/images/image-gallery/",
    ),
    RecommendedSource(
        "Smithsonian Open Access",
        "CC0 natural-history media; automatic access requires a personal API key.",
        "https://www.si.edu/openaccess",
    ),
    RecommendedSource(
        "National Park Service",
        "Generally public-domain NPS-created galleries; automatic access requires an API key.",
        "https://www.nps.gov/subjects/developer/api-documentation.htm",
    ),
)


def collection_by_slug(slug: str) -> PublicCollection:
    for collection in PUBLIC_COLLECTIONS:
        if collection.slug == slug:
            return collection
    raise CollectionDownloadError(f"Unknown public collection: {slug}")


def _require_https_host(url: str, allowed_hosts: frozenset[str], *, subject: str) -> None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CollectionDownloadError(f"{subject} uses an invalid network port: {url}") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or port not in {None, 443}
        or parsed.username
        or parsed.password
    ):
        raise CollectionDownloadError(f"{subject} uses an untrusted download host: {url}")


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        _require_https_host(destination, self._allowed_hosts, subject="Collection redirect")
        return super().redirect_request(req, fp, code, msg, headers, destination)


_METADATA_URL_OPENER = build_opener(_AllowlistedRedirectHandler(_ALLOWED_METADATA_HOSTS)).open
_IMAGE_URL_OPENER = build_opener(_AllowlistedRedirectHandler(_ALLOWED_IMAGE_HOSTS)).open


def _open_request(
    opener: Callable[..., Any],
    request: Request,
    *,
    allowed_hosts: frozenset[str],
) -> Any:
    if opener is urlopen:
        safe_opener = _METADATA_URL_OPENER if allowed_hosts == _ALLOWED_METADATA_HOSTS else _IMAGE_URL_OPENER
        return safe_opener(request, timeout=NETWORK_TIMEOUT_SECONDS)
    return opener(request, timeout=NETWORK_TIMEOUT_SECONDS)


def _response_bytes(response: Any, *, maximum: int, subject: str) -> bytes:
    raw_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if raw_length:
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise CollectionDownloadError(f"{subject} returned an invalid response size") from exc
        if length < 0 or length > maximum:
            raise CollectionDownloadError(f"{subject} exceeds the {maximum // (1024 * 1024)} MB safety limit")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise CollectionDownloadError(f"{subject} exceeds the {maximum // (1024 * 1024)} MB safety limit")
    if raw_length and total != int(raw_length):
        raise CollectionDownloadError(f"{subject} ended before the advertised response size")
    return b"".join(chunks)


def _stream_image_response(
    response: Any,
    temporary: Path,
    *,
    cancelled: Callable[[], bool] | None,
) -> None:
    raw_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    expected_length: int | None = None
    if raw_length:
        try:
            expected_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise CollectionDownloadError("Collection image returned an invalid response size") from exc
        if expected_length < 0 or expected_length > MAX_IMAGE_BYTES:
            raise CollectionDownloadError(
                f"Collection image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB safety limit"
            )
    total = 0
    with temporary.open("xb") as stream:
        while True:
            _check_cancelled(cancelled)
            chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, MAX_IMAGE_BYTES + 1 - total))
            if not chunk:
                break
            stream.write(chunk)
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise CollectionDownloadError(
                    f"Collection image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB safety limit"
                )
        if expected_length is not None and total != expected_length:
            raise CollectionDownloadError("Collection image ended before the advertised response size")
        stream.flush()
        os.fsync(stream.fileno())


def _get_json(
    url: str,
    *,
    opener: Callable[..., Any],
    require_object: bool = True,
    cancelled: Callable[[], bool] | None = None,
) -> Any:
    _require_https_host(url, _ALLOWED_METADATA_HOSTS, subject="Collection metadata")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT})
    try:
        _check_cancelled(cancelled)
        with _open_request(opener, request, allowed_hosts=_ALLOWED_METADATA_HOSTS) as response:
            final_url = response.geturl()
            _require_https_host(final_url, _ALLOWED_METADATA_HOSTS, subject="Collection metadata redirect")
            payload = _response_bytes(response, maximum=MAX_METADATA_BYTES, subject="Collection metadata")
    except CollectionDownloadError:
        raise
    except Exception as exc:
        raise CollectionDownloadError(f"Could not retrieve collection metadata: {exc}") from exc
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionDownloadError("Collection provider returned malformed metadata") from exc
    if require_object and not isinstance(decoded, dict):
        raise CollectionDownloadError("Collection provider returned unexpected metadata")
    return decoded


def _plain_text(value: Any) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _extension_for_url(url: str, mime: str = "") -> str:
    if mime in _IMAGE_MIME_EXTENSIONS:
        return _IMAGE_MIME_EXTENSIONS[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ""


def _discover_wikimedia(
    collection: PublicCollection,
    count: int,
    *,
    opener: Callable[..., Any] = urlopen,
    cancelled: Callable[[], bool] | None = None,
) -> list[CollectionAsset]:
    base_url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": f'incategory:"{collection.category}" filetype:bitmap',
        "gsrnamespace": "6",
        "gsrlimit": "100",
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "3840",
    }
    assets: list[CollectionAsset] = []
    seen: set[str] = set()
    continuation: dict[str, str] = {}
    for _page in range(10):
        data = _get_json(
            f"{base_url}?{urlencode({**params, **continuation})}",
            opener=opener,
            cancelled=cancelled,
        )
        pages = data.get("query", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        if not isinstance(pages, list):
            pages = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            info_list = page.get("imageinfo")
            if not isinstance(info_list, list) or not info_list or not isinstance(info_list[0], dict):
                continue
            info = info_list[0]
            raw_metadata = info.get("extmetadata")
            metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

            def metadata_value(key: str) -> str:
                field = metadata.get(key)
                return str(field.get("value", "")) if isinstance(field, dict) else ""

            license_name = _plain_text(metadata_value("LicenseShortName"))
            if license_name.casefold() not in _ALLOWED_COMMONS_LICENSES:
                continue
            download_url = str(info.get("thumburl") or info.get("url") or "")
            source_url = str(info.get("descriptionurl") or "")
            extension = _extension_for_url(download_url, str(info.get("mime") or ""))
            try:
                _require_https_host(download_url, frozenset({"upload.wikimedia.org"}), subject="Wikimedia image")
                _require_https_host(source_url, frozenset({"commons.wikimedia.org"}), subject="Wikimedia source page")
            except CollectionDownloadError:
                continue
            if not extension:
                continue
            provider_id = str(page.get("pageid") or hashlib.sha256(source_url.encode()).hexdigest()[:20])
            if provider_id in seen:
                continue
            seen.add(provider_id)
            title = str(page.get("title") or provider_id).removeprefix("File:")
            assets.append(
                CollectionAsset(
                    provider_id=provider_id,
                    title=_plain_text(title),
                    creator=_plain_text(metadata_value("Artist")) or "Unknown creator",
                    source_url=source_url,
                    download_url=download_url,
                    license_name=license_name,
                    license_url=_plain_text(metadata_value("LicenseUrl")),
                    extension=extension,
                )
            )
            if len(assets) >= count:
                return assets
        next_values = data.get("continue")
        if not isinstance(next_values, dict):
            break
        continuation = {str(key): str(value) for key, value in next_values.items()}
    return assets


def _choose_nasa_download(items: Any) -> str:
    hrefs = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                href = item
            elif isinstance(item, dict):
                href = str(item.get("href") or "")
            else:
                continue
            parsed = urlparse(href)
            if parsed.scheme == "http" and parsed.hostname == "images-assets.nasa.gov":
                href = parsed._replace(scheme="https").geturl()
            hrefs.append(href)
    image_hrefs = [href for href in hrefs if _extension_for_url(href)]
    preferences = (
        lambda href: "~large." in href.lower(),
        lambda href: "~orig." in href.lower() and _extension_for_url(href) in {".jpg", ".jpeg", ".png", ".webp"},
        lambda href: "~medium." in href.lower(),
    )
    for predicate in preferences:
        for href in image_hrefs:
            if predicate(href):
                return href
    return image_hrefs[0] if image_hrefs else ""


def _discover_nasa(
    collection: PublicCollection,
    count: int,
    *,
    opener: Callable[..., Any] = urlopen,
    cancelled: Callable[[], bool] | None = None,
) -> list[CollectionAsset]:
    assets: list[CollectionAsset] = []
    seen: set[str] = set()
    for query in collection.query:
        search_url = "https://images-api.nasa.gov/search?" + urlencode(
            {"q": query, "media_type": "image", "page_size": 100}
        )
        data = _get_json(search_url, opener=opener, cancelled=cancelled)
        items = data.get("collection", {}).get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            records = item.get("data")
            if not isinstance(records, list) or not records or not isinstance(records[0], dict):
                continue
            record = records[0]
            provider_id = str(record.get("nasa_id") or "").strip()
            if not provider_id or provider_id in seen or str(record.get("media_type") or "") != "image":
                continue
            if str(record.get("copyright") or "").strip():
                continue
            asset_manifest_url = str(item.get("href") or "")
            try:
                _require_https_host(
                    asset_manifest_url,
                    frozenset({"images-api.nasa.gov", "images-assets.nasa.gov"}),
                    subject="NASA asset metadata",
                )
            except CollectionDownloadError:
                continue
            manifest = _get_json(
                asset_manifest_url,
                opener=opener,
                require_object=False,
                cancelled=cancelled,
            )
            if isinstance(manifest, dict):
                manifest_items = manifest.get("collection", {}).get("items", [])
            else:
                manifest_items = manifest
            download_url = _choose_nasa_download(manifest_items)
            extension = _extension_for_url(download_url)
            try:
                _require_https_host(download_url, frozenset({"images-assets.nasa.gov"}), subject="NASA image")
            except CollectionDownloadError:
                continue
            if not extension:
                continue
            seen.add(provider_id)
            creator = _plain_text(record.get("secondary_creator") or record.get("center") or "NASA")
            assets.append(
                CollectionAsset(
                    provider_id=provider_id,
                    title=_plain_text(record.get("title") or provider_id),
                    creator=creator,
                    source_url=f"https://images.nasa.gov/details/{quote(provider_id, safe='')}",
                    download_url=download_url,
                    license_name="NASA media usage guidelines",
                    license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                    extension=extension,
                )
            )
            if len(assets) >= count:
                return assets
    return assets


def _discover_assets(
    collection: PublicCollection,
    count: int,
    *,
    opener: Callable[..., Any],
    cancelled: Callable[[], bool] | None = None,
) -> list[CollectionAsset]:
    if collection.provider == "NASA":
        return _discover_nasa(collection, count, opener=opener, cancelled=cancelled)
    if collection.provider == "Wikimedia Commons":
        return _discover_wikimedia(collection, count, opener=opener, cancelled=cancelled)
    raise CollectionDownloadError(f"Collection provider is not supported: {collection.provider}")


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise CollectionDownloadCancelled("Public collection download cancelled")


def _safe_filename(asset: CollectionAsset) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", asset.provider_id).strip(".-_")[:80]
    if not safe_id:
        safe_id = hashlib.sha256(asset.source_url.encode()).hexdigest()[:20]
    return f"{safe_id}{asset.extension}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise CollectionDownloadError("Provider returned a file that is not a safe supported image") from exc


def _download_asset(
    asset: CollectionAsset,
    destination: Path,
    *,
    opener: Callable[..., Any],
    cancelled: Callable[[], bool] | None,
) -> tuple[Path, str, tuple[int, int]]:
    _require_https_host(asset.download_url, _ALLOWED_IMAGE_HOSTS, subject="Collection image")
    target = destination / _safe_filename(asset)
    if target.exists() or target.is_symlink():
        raise CollectionDownloadError(f"Refusing to replace an existing unowned file: {target.name}")
    temporary = destination / f".{target.name}.{uuid4().hex}.part"
    request = Request(asset.download_url, headers={"Accept": "image/*", "User-Agent": _USER_AGENT})
    try:
        with _open_request(opener, request, allowed_hosts=_ALLOWED_IMAGE_HOSTS) as response:
            _require_https_host(response.geturl(), _ALLOWED_IMAGE_HOSTS, subject="Collection image redirect")
            _stream_image_response(response, temporary, cancelled=cancelled)
        _check_cancelled(cancelled)
        _verify_image(temporary)
        digest = _sha256_file(temporary)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise CollectionDownloadError(f"A file appeared while downloading: {target.name}") from exc
        identity = target.stat().st_dev, target.stat().st_ino
        return target, digest, identity
    except CollectionDownloadError:
        raise
    except Exception as exc:
        raise CollectionDownloadError(f"Could not download {asset.title}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _load_manifest(path: Path) -> tuple[bytes | None, dict[str, dict[str, Any]], str | None]:
    if not path.exists():
        return None, {}, None
    if path.is_symlink() or not path.is_file():
        raise CollectionDownloadError(f"Collection manifest is not a regular file: {path}")
    previous = path.read_bytes()
    try:
        parsed = json.loads(previous)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionDownloadError(f"Collection manifest is malformed: {path}") from exc
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        raise CollectionDownloadError(f"Collection manifest has an unsupported schema: {path}")
    collection_data = parsed.get("collection")
    images = parsed.get("images")
    if not isinstance(collection_data, dict) or not isinstance(collection_data.get("slug"), str):
        raise CollectionDownloadError(f"Collection manifest does not identify its collection: {path}")
    if not isinstance(images, list):
        raise CollectionDownloadError(f"Collection manifest has an invalid image list: {path}")
    valid = {}
    for item in images:
        if isinstance(item, dict) and isinstance(item.get("provider_id"), str):
            valid[item["provider_id"]] = item
    return previous, valid, collection_data["slug"]


def _existing_manifest_image(destination: Path, item: dict[str, Any]) -> Path | None:
    filename = item.get("filename")
    expected_hash = item.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(expected_hash, str):
        return None
    path = destination / filename
    if path.is_symlink() or not path.is_file():
        return None
    try:
        _verify_image(path)
        if _sha256_file(path) != expected_hash:
            return None
    except (OSError, CollectionDownloadError):
        return None
    return path


def _remove_installed(installed: list[tuple[Path, tuple[int, int]]]) -> None:
    for path, identity in reversed(installed):
        try:
            stat_result = path.stat()
            if (stat_result.st_dev, stat_result.st_ino) == identity:
                path.unlink()
        except FileNotFoundError:
            pass


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_manifest(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.restore")
    try:
        with temporary.open("xb") as stream:
            stream.write(previous)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def download_public_collection(
    slug: str,
    destination: str | Path,
    count: int,
    *,
    opener: Callable[..., Any] = urlopen,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> CollectionDownloadResult:
    """Download up to ``count`` licensed images and atomically update provenance."""

    collection = collection_by_slug(slug)
    try:
        requested = int(count)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CollectionDownloadError("Image count must be a whole number from 1 to 100") from exc
    if requested < 1 or requested > 100:
        raise CollectionDownloadError("Image count must be from 1 to 100")
    destination_path = Path(destination).expanduser().absolute()
    if destination_path.is_symlink():
        raise CollectionDownloadError("Collection destination must not be a symbolic link")
    if destination_path.exists() and not destination_path.is_dir():
        raise CollectionDownloadError("Collection destination must be a folder")
    destination_path.mkdir(parents=True, exist_ok=True)
    if destination_path.is_symlink():
        raise CollectionDownloadError("Collection destination must not be a symbolic link")

    manifest_path = destination_path / MANIFEST_FILENAME
    previous_manifest, existing_records, manifest_slug = _load_manifest(manifest_path)
    if manifest_slug is not None and manifest_slug != collection.slug:
        raise CollectionDownloadError(
            f"The destination already contains a manifest for a different collection ({manifest_slug})."
        )
    _check_cancelled(cancelled)
    if progress is not None:
        progress(0, requested, "Checking existing collection files...")

    installed: list[tuple[Path, tuple[int, int]]] = []
    selected_paths: list[Path] = []
    selected_records: list[dict[str, Any]] = []
    downloaded = 0
    existing = 0
    failures: list[CollectionDownloadError] = []
    manifest_records = dict(existing_records)
    manifest_written = False
    try:
        for provider_id, prior in existing_records.items():
            _check_cancelled(cancelled)
            if len(selected_paths) >= requested:
                break
            existing_path = _existing_manifest_image(destination_path, prior)
            if existing_path is None:
                continue
            selected_paths.append(existing_path)
            selected_records.append(prior)
            existing += 1
            if progress is not None:
                progress(len(selected_paths), requested, str(prior.get("title") or provider_id))

        if len(selected_paths) >= requested:
            _check_cancelled(cancelled)
            return CollectionDownloadResult(
                collection=collection,
                destination=destination_path,
                manifest_path=manifest_path,
                image_paths=tuple(selected_paths),
                downloaded=0,
                existing=existing,
                failed=0,
            )

        _check_cancelled(cancelled)
        if progress is not None:
            progress(len(selected_paths), requested, "Searching collection...")
        needed = requested - len(selected_paths)
        provider_limit = 300 if collection.provider == "Wikimedia Commons" else 200
        discovery_count = min(provider_limit, requested + max(25, needed * 2))
        assets = _discover_assets(
            collection,
            discovery_count,
            opener=opener,
            cancelled=cancelled,
        )
        if not assets and not selected_paths:
            raise CollectionDownloadError("No eligible CC0, public-domain, or NASA images were returned")
        selected_ids = {str(record.get("provider_id")) for record in selected_records}
        for asset in assets:
            if len(selected_paths) >= requested:
                break
            _check_cancelled(cancelled)
            if asset.provider_id in selected_ids:
                continue
            try:
                path, digest, identity = _download_asset(
                    asset,
                    destination_path,
                    opener=opener,
                    cancelled=cancelled,
                )
            except CollectionDownloadCancelled:
                raise
            except CollectionDownloadError as exc:
                failures.append(exc)
                continue
            installed.append((path, identity))
            downloaded += 1
            selected_paths.append(path)
            record = {
                "provider_id": asset.provider_id,
                "title": asset.title,
                "creator": asset.creator,
                "source_url": asset.source_url,
                "download_url": asset.download_url,
                "license": asset.license_name,
                "license_url": asset.license_url,
                "filename": path.name,
                "sha256": digest,
            }
            selected_records.append(record)
            selected_ids.add(asset.provider_id)
            manifest_records[asset.provider_id] = record
            if progress is not None:
                progress(len(selected_paths), requested, asset.title)

        _check_cancelled(cancelled)
        if not selected_paths:
            if failures:
                raise failures[0]
            raise CollectionDownloadError("No eligible images could be downloaded")
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection": asdict(collection),
            "rights_notice": (
                "Files were accepted only when identified as NASA content without a copyright field, "
                "or as Wikimedia Commons CC0/public-domain media. Review each source record before redistribution."
            ),
            "images": list(manifest_records.values()),
        }
        _write_manifest(manifest_path, payload)
        manifest_written = True
        _check_cancelled(cancelled)
    except Exception:
        _remove_installed(installed)
        if manifest_written:
            _restore_manifest(manifest_path, previous_manifest)
        raise

    return CollectionDownloadResult(
        collection=collection,
        destination=destination_path,
        manifest_path=manifest_path,
        image_paths=tuple(selected_paths),
        downloaded=downloaded,
        existing=existing,
        failed=max(0, requested - len(selected_paths)),
    )
