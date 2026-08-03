import io
import json
from http.client import HTTPMessage
from urllib.request import Request

import pytest
from PIL import Image

from mint_background_switcher import public_collections


class _Response:
    def __init__(self, payload: bytes, *, url: str, content_type: str = "application/json"):
        self._stream = io.BytesIO(payload)
        self._url = url
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": content_type,
        }

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _json_response(payload, url: str) -> _Response:
    return _Response(json.dumps(payload).encode("utf-8"), url=url)


def _png_bytes(color=(30, 80, 150)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(stream, format="PNG")
    return stream.getvalue()


def test_catalogue_has_no_key_automatic_collections_and_keyed_sources_are_links_only():
    slugs = {item.slug for item in public_collections.PUBLIC_COLLECTIONS}
    assert slugs == {
        "nasa-space",
        "nasa-earth",
        "commons-sunsets",
        "commons-insects",
        "commons-us-national-parks",
    }
    assert all(item.provider in {"NASA", "Wikimedia Commons"} for item in public_collections.PUBLIC_COLLECTIONS)
    assert {source.name for source in public_collections.RECOMMENDED_SOURCES} == {
        "USDA ARS Insects",
        "Smithsonian Open Access",
        "National Park Service",
    }
    assert all(source.url.startswith("https://") for source in public_collections.RECOMMENDED_SOURCES)


def test_wikimedia_discovery_accepts_only_cc0_and_public_domain_bitmap_assets():
    spec = public_collections.collection_by_slug("commons-sunsets")
    api_url = "https://commons.wikimedia.org/w/api.php"
    payload = {
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "title": "File:CC0 sunset.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/cc0.jpg",
                            "thumburl": "https://upload.wikimedia.org/cc0-thumb.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:CC0_sunset.jpg",
                            "mime": "image/jpeg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"},
                                "Artist": {"value": "<b>Alice</b>"},
                            },
                        }
                    ],
                },
                "2": {
                    "pageid": 2,
                    "title": "File:Government sunset.png",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/public.png",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Government_sunset.png",
                            "mime": "image/png",
                            "extmetadata": {
                                "LicenseShortName": {"value": "Public domain"},
                                "Artist": {"value": "US Government"},
                            },
                        }
                    ],
                },
                "3": {
                    "pageid": 3,
                    "title": "File:Attribution required.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/by.jpg",
                            "mime": "image/jpeg",
                            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
                        }
                    ],
                },
                "4": {
                    "pageid": 4,
                    "title": "File:Untrusted redirect.jpg",
                    "imageinfo": [
                        {
                            "url": "https://evil.example/image.jpg",
                            "mime": "image/jpeg",
                            "extmetadata": {"LicenseShortName": {"value": "CC0"}},
                        }
                    ],
                },
            }
        }
    }

    def opener(request, timeout):
        assert request.full_url.startswith(api_url)
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return _json_response(payload, api_url)

    assets = public_collections._discover_wikimedia(spec, 10, opener=opener)

    assert [(asset.title, asset.license_name, asset.creator) for asset in assets] == [
        ("CC0 sunset.jpg", "CC0", "Alice"),
        ("Government sunset.png", "Public domain", "US Government"),
    ]
    assert assets[0].download_url.endswith("cc0-thumb.jpg")
    assert assets[1].download_url.endswith("public.png")


def test_nasa_discovery_rejects_items_with_copyright_metadata_and_uses_large_asset():
    spec = public_collections.collection_by_slug("nasa-space")
    search_url = "https://images-api.nasa.gov/search"
    asset_url = "https://images-assets.nasa.gov/image/NASA-1/collection.json"
    search = {
        "collection": {
            "items": [
                {
                    "data": [
                        {
                            "nasa_id": "NASA-1",
                            "media_type": "image",
                            "title": "Public nebula",
                            "secondary_creator": "NASA/JPL-Caltech",
                        }
                    ],
                    "href": asset_url,
                },
                {
                    "data": [
                        {
                            "nasa_id": "THIRD-PARTY",
                            "media_type": "image",
                            "title": "Licensed nebula",
                            "copyright": "Commercial Observatory",
                        }
                    ],
                    "href": "https://images-api.nasa.gov/asset/THIRD-PARTY",
                },
            ]
        }
    }
    manifest = [
        "http://images-assets.nasa.gov/image/NASA-1/NASA-1~small.jpg",
        "http://images-assets.nasa.gov/image/NASA-1/NASA-1~large.jpg",
        "http://images-assets.nasa.gov/image/NASA-1/NASA-1~orig.tif",
    ]

    def opener(request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        if request.full_url.startswith(search_url):
            return _json_response(search, request.full_url)
        if request.full_url == asset_url:
            return _json_response(manifest, asset_url)
        raise AssertionError(request.full_url)

    assets = public_collections._discover_nasa(spec, 10, opener=opener)

    assert len(assets) == 1
    assert assets[0].provider_id == "NASA-1"
    assert assets[0].download_url == "https://images-assets.nasa.gov/image/NASA-1/NASA-1~large.jpg"
    assert assets[0].license_name == "NASA media usage guidelines"


def test_cancellation_stops_nasa_discovery_before_asset_requests(tmp_path):
    cancel = False
    calls = []
    search = {
        "collection": {
            "items": [
                {
                    "data": [{"nasa_id": "NASA-CANCEL", "media_type": "image", "title": "Cancelled"}],
                    "href": "https://images-assets.nasa.gov/image/NASA-CANCEL/collection.json",
                }
            ]
        }
    }

    class CancellingMetadataResponse(_Response):
        def read(self, size=-1):
            nonlocal cancel
            data = super().read(size)
            if data:
                cancel = True
            return data

    def opener(request, timeout):
        calls.append(request.full_url)
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return CancellingMetadataResponse(
            json.dumps(search).encode("utf-8"),
            url=request.full_url,
        )

    destination = tmp_path / "NASA"
    with pytest.raises(public_collections.CollectionDownloadCancelled):
        public_collections.download_public_collection(
            "nasa-space",
            destination,
            1,
            opener=opener,
            cancelled=lambda: cancel,
        )

    assert len(calls) == 1
    assert not list(destination.iterdir())


def test_download_collection_installs_verified_images_and_manifest_idempotently(monkeypatch, tmp_path):
    spec = public_collections.collection_by_slug("commons-insects")
    assets = [
        public_collections.CollectionAsset(
            provider_id="bee-1",
            title="Bee one",
            creator="A. Person",
            source_url="https://commons.wikimedia.org/wiki/File:Bee_one.png",
            download_url="https://upload.wikimedia.org/bee-one.png",
            license_name="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            extension=".png",
        ),
        public_collections.CollectionAsset(
            provider_id="bee-2",
            title="Bee two",
            creator="US Government",
            source_url="https://commons.wikimedia.org/wiki/File:Bee_two.png",
            download_url="https://upload.wikimedia.org/bee-two.png",
            license_name="Public domain",
            license_url="",
            extension=".png",
        ),
    ]
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: list(assets))
    image_payloads = {
        assets[0].download_url: _png_bytes((10, 20, 30)),
        assets[1].download_url: _png_bytes((40, 50, 60)),
    }
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return _Response(image_payloads[request.full_url], url=request.full_url, content_type="image/png")

    destination = tmp_path / "Insects"
    progress = []
    result = public_collections.download_public_collection(
        spec.slug,
        destination,
        2,
        opener=opener,
        progress=lambda completed, total, name: progress.append((completed, total, name)),
    )

    assert result.downloaded == 2
    assert result.existing == 0
    assert len(result.image_paths) == 2
    assert all(path.is_file() for path in result.image_paths)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["collection"]["slug"] == spec.slug
    assert [(item["title"], item["license"]) for item in manifest["images"]] == [
        ("Bee one", "CC0"),
        ("Bee two", "Public domain"),
    ]
    assert all(len(item["sha256"]) == 64 for item in manifest["images"])
    assert progress[-1][:2] == (2, 2)

    calls.clear()
    repeated = public_collections.download_public_collection(spec.slug, destination, 2, opener=opener)
    assert repeated.downloaded == 0
    assert repeated.existing == 2
    assert calls == []
    assert repeated.image_paths == result.image_paths

    smaller = public_collections.download_public_collection(spec.slug, destination, 1, opener=opener)
    assert smaller.downloaded == 0
    assert smaller.existing == 1
    assert calls == []
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["images"]) == 2


def test_existing_collection_can_expand_past_already_discovered_provider_ids(monkeypatch, tmp_path):
    assets = [
        public_collections.CollectionAsset(
            provider_id=f"asset-{index:02d}",
            title=f"Asset {index:02d}",
            creator="Public Creator",
            source_url=f"https://commons.wikimedia.org/wiki/File:Asset-{index:02d}.jpg",
            download_url=f"https://upload.wikimedia.org/asset-{index:02d}.jpg",
            license_name="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            extension=".jpg",
        )
        for index in range(40)
    ]
    discovered_counts = []

    def discover(_collection, count, *, opener, cancelled):
        assert cancelled is None
        discovered_counts.append(count)
        return assets[:count]

    monkeypatch.setattr(public_collections, "_discover_assets", discover)

    def opener(request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return _Response(_png_bytes(), url=request.full_url, content_type="image/png")

    destination = tmp_path / "Expandable"
    initial = public_collections.download_public_collection(
        "commons-sunsets",
        destination,
        25,
        opener=opener,
    )
    expanded = public_collections.download_public_collection(
        "commons-sunsets",
        destination,
        30,
        opener=opener,
    )

    assert initial.downloaded == 25
    assert expanded.downloaded == 5
    assert expanded.existing == 25
    assert expanded.failed == 0
    assert len(expanded.image_paths) == 30
    assert discovered_counts == [75, 55]
    manifest = json.loads(expanded.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["images"]) == 30


def test_download_rejects_redirect_to_unapproved_host(monkeypatch, tmp_path):
    asset = public_collections.CollectionAsset(
        "space-1",
        "Space",
        "NASA",
        "https://images.nasa.gov/details/space-1",
        "https://images-assets.nasa.gov/image/space-1/space-1~large.jpg",
        "NASA media usage guidelines",
        "https://www.nasa.gov/nasa-brand-center/images-and-media/",
        ".jpg",
    )
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: [asset])

    def opener(_request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return _Response(_png_bytes(), url="https://evil.example/stolen.jpg", content_type="image/jpeg")

    destination = tmp_path / "Space"
    with pytest.raises(public_collections.CollectionDownloadError, match="untrusted download host"):
        public_collections.download_public_collection("nasa-space", destination, 1, opener=opener)

    assert not list(destination.glob("*.part"))
    assert not list(destination.glob("*.jpg"))
    assert not (destination / public_collections.MANIFEST_FILENAME).exists()


def test_redirect_handler_rejects_untrusted_host_before_following():
    handler = public_collections._AllowlistedRedirectHandler(public_collections._ALLOWED_IMAGE_HOSTS)
    request = Request("https://upload.wikimedia.org/approved.jpg")

    with pytest.raises(public_collections.CollectionDownloadError, match="untrusted download host"):
        handler.redirect_request(
            request,
            io.BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://evil.example/stolen.jpg",
        )


def test_cancellation_after_final_existing_validation_does_not_return_success(monkeypatch, tmp_path):
    assets = [
        public_collections.CollectionAsset(
            f"existing-{index}",
            f"Existing {index}",
            "Creator",
            f"https://commons.wikimedia.org/wiki/File:Existing-{index}.jpg",
            f"https://upload.wikimedia.org/existing-{index}.jpg",
            "CC0",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            ".jpg",
        )
        for index in range(10)
    ]
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: assets)

    def opener(request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return _Response(_png_bytes(), url=request.full_url, content_type="image/png")

    destination = tmp_path / "Existing"
    public_collections.download_public_collection(
        "commons-sunsets",
        destination,
        10,
        opener=opener,
    )
    manifest_before = (destination / public_collections.MANIFEST_FILENAME).read_bytes()
    cancelled = False
    validations = 0
    original = public_collections._existing_manifest_image

    def validate(*args, **kwargs):
        nonlocal cancelled, validations
        result = original(*args, **kwargs)
        validations += 1
        if validations == 10:
            cancelled = True
        return result

    monkeypatch.setattr(public_collections, "_existing_manifest_image", validate)
    with pytest.raises(public_collections.CollectionDownloadCancelled):
        public_collections.download_public_collection(
            "commons-sunsets",
            destination,
            10,
            opener=opener,
            cancelled=lambda: cancelled,
        )

    assert validations == 10
    assert (destination / public_collections.MANIFEST_FILENAME).read_bytes() == manifest_before


def test_cancellation_after_manifest_commit_restores_prior_state(monkeypatch, tmp_path):
    asset = public_collections.CollectionAsset(
        "commit-cancel",
        "Commit Cancel",
        "Creator",
        "https://commons.wikimedia.org/wiki/File:Commit-Cancel.jpg",
        "https://upload.wikimedia.org/commit-cancel.jpg",
        "CC0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
        ".jpg",
    )
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: [asset])

    def opener(request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return _Response(_png_bytes(), url=request.full_url, content_type="image/png")

    cancelled = False
    original_write = public_collections._write_manifest

    def write_then_cancel(path, payload):
        nonlocal cancelled
        original_write(path, payload)
        cancelled = True

    monkeypatch.setattr(public_collections, "_write_manifest", write_then_cancel)
    destination = tmp_path / "Commit Cancel"
    with pytest.raises(public_collections.CollectionDownloadCancelled):
        public_collections.download_public_collection(
            "commons-sunsets",
            destination,
            1,
            opener=opener,
            cancelled=lambda: cancelled,
        )

    assert not (destination / public_collections.MANIFEST_FILENAME).exists()
    assert not list(destination.glob("*.jpg"))
    assert not list(destination.glob("*.part"))


def test_cancellation_interrupts_stream_and_removes_temporary_file(monkeypatch, tmp_path):
    asset = public_collections.CollectionAsset(
        "stream-1",
        "Streaming image",
        "Creator",
        "https://commons.wikimedia.org/wiki/File:Streaming_image.png",
        "https://upload.wikimedia.org/streaming-image.png",
        "CC0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
        ".png",
    )
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: [asset])
    cancel = False

    class CancellingResponse(_Response):
        def read(self, size=-1):
            nonlocal cancel
            data = super().read(min(size, 10))
            if data:
                cancel = True
            return data

    def opener(request, timeout):
        assert timeout == public_collections.NETWORK_TIMEOUT_SECONDS
        return CancellingResponse(_png_bytes(), url=request.full_url, content_type="image/png")

    destination = tmp_path / "Streaming"
    with pytest.raises(public_collections.CollectionDownloadCancelled):
        public_collections.download_public_collection(
            "commons-sunsets",
            destination,
            1,
            opener=opener,
            cancelled=lambda: cancel,
        )

    assert not list(destination.iterdir())


def test_cancellation_rolls_back_new_images_and_preserves_previous_manifest(monkeypatch, tmp_path):
    assets = [
        public_collections.CollectionAsset(
            f"asset-{index}",
            f"Asset {index}",
            "Creator",
            f"https://commons.wikimedia.org/wiki/File:Asset_{index}.png",
            f"https://upload.wikimedia.org/asset-{index}.png",
            "CC0",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            ".png",
        )
        for index in range(2)
    ]
    monkeypatch.setattr(public_collections, "_discover_assets", lambda *_args, **_kwargs: list(assets))
    destination = tmp_path / "Sunsets"
    destination.mkdir()
    manifest = destination / public_collections.MANIFEST_FILENAME
    previous_manifest = (
        '{"schema_version": 1, "collection": {"slug": "commons-sunsets"}, "images": []}\n'
    )
    manifest.write_text(previous_manifest, encoding="utf-8")
    cancel = False

    def opener(request, timeout):
        return _Response(_png_bytes(), url=request.full_url, content_type="image/png")

    def progress(completed, _total, _name):
        nonlocal cancel
        if completed == 1:
            cancel = True

    with pytest.raises(public_collections.CollectionDownloadCancelled):
        public_collections.download_public_collection(
            "commons-sunsets",
            destination,
            2,
            opener=opener,
            cancelled=lambda: cancel,
            progress=progress,
        )

    assert manifest.read_text(encoding="utf-8") == previous_manifest
    assert not list(destination.glob("*.png"))
    assert not list(destination.glob("*.part"))


def test_download_rejects_symlink_destination(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(
        public_collections,
        "_discover_assets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reject before network discovery")),
    )

    with pytest.raises(public_collections.CollectionDownloadError, match="symbolic link"):
        public_collections.download_public_collection("nasa-earth", linked, 10)
