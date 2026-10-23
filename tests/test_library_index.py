import os
import random
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from mint_background_switcher.library_index import (
    INDEX_FILENAME,
    LibraryIndex,
    LibraryIndexError,
    LibraryScanCancelled,
    normalized_scan_roots,
    scan_signature,
)


def _touch_images(folder: Path, names: tuple[str, ...]) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        paths.append(str(path.absolute()))
    return paths


def test_normalized_roots_and_signature_are_stable_across_order_and_duplicates(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    roots_a = normalized_scan_roots([str(second), str(first), str(first)])
    roots_b = normalized_scan_roots([str(first), str(second)])

    assert roots_a == roots_b == (str(first.resolve()), str(second.resolve()))
    assert scan_signature(roots_a, recursive=True) == scan_signature(roots_b, recursive=True)
    assert scan_signature(roots_a, recursive=True) != scan_signature(roots_a, recursive=False)


def test_refresh_indexes_supported_images_recursively_without_per_file_resolve(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    expected = _touch_images(root, ("a.jpg", "nested/b.PNG", "nested/skip.txt"))[:2]
    working = tmp_path / "working"
    working.mkdir()
    real_resolve = Path.resolve
    resolve_calls = []

    def counted_resolve(path, *args, **kwargs):
        resolve_calls.append(path)
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted_resolve)
    index = LibraryIndex(working)

    snapshot = index.refresh([str(root)], recursive=True)

    assert snapshot.image_count == 2
    assert index.paths(snapshot.signature) == sorted(expected)
    assert len(resolve_calls) <= 3


def test_nonrecursive_refresh_skips_nested_images(tmp_path):
    root = tmp_path / "photos"
    expected = _touch_images(root, ("a.jpg", "nested/b.png"))
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=False)

    assert index.paths(snapshot.signature) == [expected[0]]


def test_refresh_indexes_an_individual_picture_source(tmp_path):
    picture = tmp_path / "individual.png"
    picture.write_bytes(b"extension is sufficient for indexing")
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(picture)], recursive=True)

    assert snapshot.image_count == 1
    assert index.paths(snapshot.signature) == [str(picture.resolve())]


def _write_sized_images(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    sized = {
        "small": Image.new("RGB", (60, 40), (1, 2, 3)),
        "medium": Image.new("RGB", (100, 80), (2, 3, 1)),
        "large": Image.new("RGB", (200, 150), (3, 1, 2)),
    }
    paths = {}
    for name, image in sized.items():
        path = root / f"{name}.png"
        image.save(path)
        paths[name] = path
    return paths


def test_scan_signature_changes_with_min_image_size(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    roots = normalized_scan_roots([str(root)])

    assert scan_signature(roots, recursive=True) == scan_signature(roots, recursive=True, min_image_size=0)
    assert scan_signature(roots, recursive=True) != scan_signature(roots, recursive=True, min_image_size=720)
    assert scan_signature(roots, recursive=True, min_image_size=720) != scan_signature(
        roots, recursive=True, min_image_size=1080
    )


def test_refresh_excludes_images_below_min_size(tmp_path):
    root = tmp_path / "photos"
    paths = _write_sized_images(root)
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=True, min_image_size=100)

    assert snapshot.image_count == 1
    assert index.paths(snapshot.signature) == [str(paths["large"].resolve())]


def test_refresh_keeps_image_whose_smallest_side_equals_min_size(tmp_path):
    root = tmp_path / "photos"
    paths = _write_sized_images(root)
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=True, min_image_size=80)

    assert sorted(index.paths(snapshot.signature)) == sorted(
        [str(paths["medium"].resolve()), str(paths["large"].resolve())]
    )


def test_filter_emptied_root_still_counts_as_complete_without_rescanning(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    _write_sized_images(root)
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=True, min_image_size=10_000, now_ns=1_000_000_000)
    assert snapshot.image_count == 0
    assert snapshot.refreshed_ns == 1_000_000_000

    monkeypatch.setattr(os, "walk", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rescanned")))
    reused = index.ensure([str(root)], recursive=True, min_image_size=10_000, now_ns=1_000_000_000 + 1)
    assert reused == snapshot


def test_filter_excludes_undecodable_files(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    real = root / "real.png"
    Image.new("RGB", (100, 80), (1, 1, 1)).save(real)
    garbage = root / "garbage.jpg"
    garbage.write_bytes(b"extension is sufficient but bytes are not")
    index = LibraryIndex(tmp_path / "working")

    unfiltered = index.refresh([str(root)], recursive=True)
    filtered = index.refresh([str(root)], recursive=True, min_image_size=1)

    assert unfiltered.image_count == 2
    assert filtered.image_count == 1
    assert index.paths(filtered.signature) == [str(real.resolve())]


def test_individual_picture_root_respects_min_size(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGB", (60, 40), (1, 2, 3)).save(small)
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(small)], recursive=True, min_image_size=100, now_ns=1_000_000_000)

    assert snapshot.image_count == 0
    assert snapshot.refreshed_ns == 1_000_000_000
    assert index.paths(snapshot.signature) == []


def test_fresh_index_is_reused_without_rescanning(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("a.jpg", "b.jpg"))
    index = LibraryIndex(tmp_path / "working")
    first = index.ensure([str(root)], recursive=True, now_ns=1_000_000_000)

    monkeypatch.setattr(os, "walk", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rescanned")))
    second = index.ensure(
        [str(root)],
        recursive=True,
        max_age_seconds=300,
        now_ns=2_000_000_000,
    )

    assert second == first


def test_refresh_throttles_progress_events_for_large_folders(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, tuple(f"{index}.jpg" for index in range(1201)))
    events = []
    index = LibraryIndex(tmp_path / "working")

    index.refresh(
        [str(root)],
        recursive=True,
        progress=lambda count, path: events.append((count, path)),
    )

    assert [count for count, _path in events] == [1, 500, 1000, 1201]


def test_cancelled_refresh_preserves_previous_committed_index(tmp_path):
    root = tmp_path / "photos"
    first_paths = _touch_images(root, ("a.jpg", "b.jpg"))
    index = LibraryIndex(tmp_path / "working")
    first = index.refresh([str(root)], recursive=True)
    _touch_images(root, ("c.jpg",))

    with pytest.raises(LibraryScanCancelled, match="cancelled"):
        index.refresh([str(root)], recursive=True, cancelled=lambda: True)

    assert index.paths(first.signature) == sorted(first_paths)


def test_batch_draw_does_not_repeat_until_pool_exhaustion(tmp_path):
    root = tmp_path / "photos"
    expected = _touch_images(root, tuple(f"{index}.jpg" for index in range(10)))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)
    rng = random.Random(7)

    first = index.draw(snapshot.signature, "profile:P:postcard", 4, rng=rng)
    second = index.draw(snapshot.signature, "profile:P:postcard", 6, rng=rng)
    third = index.draw(snapshot.signature, "profile:P:postcard", 4, rng=rng)

    assert len(set(first + second)) == 10
    assert sorted(first + second) == sorted(expected)
    assert len(third) == 4
    assert len(set(third)) == 4


def test_selection_transaction_rolls_back_unapplied_draw(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, tuple(f"{index}.jpg" for index in range(4)))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)

    with pytest.raises(RuntimeError, match="composition failed"):
        with index.selection() as selection:
            assert len(selection.draw(snapshot.signature, "span", 1, rng=random.Random(7))) == 1
            raise RuntimeError("composition failed")

    assert index.remaining_count(snapshot.signature, "span") == 0
    with index.selection() as selection:
        assert len(selection.draw(snapshot.signature, "span", 1, rng=random.Random(7))) == 1
    assert index.remaining_count(snapshot.signature, "span") == 3


def test_batch_draw_uses_independent_buckets(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, tuple(f"{index}.jpg" for index in range(5)))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)

    index.draw(snapshot.signature, "bucket-a", 3, rng=random.Random(1))
    index.draw(snapshot.signature, "bucket-b", 1, rng=random.Random(1))

    assert index.remaining_count(snapshot.signature, "bucket-a") == 2
    assert index.remaining_count(snapshot.signature, "bucket-b") == 4


def test_refresh_removes_deleted_paths_from_remaining_pool(tmp_path):
    root = tmp_path / "photos"
    paths = _touch_images(root, ("a.jpg", "b.jpg", "c.jpg"))
    index = LibraryIndex(tmp_path / "working")
    first = index.refresh([str(root)], recursive=True)
    index.draw(first.signature, "bucket", 1, rng=random.Random(1))
    Path(paths[1]).unlink()

    second = index.refresh([str(root)], recursive=True)
    drawn = index.draw(second.signature, "bucket", 3, rng=random.Random(2))

    assert paths[1] not in drawn


def test_malformed_database_is_quarantined_and_rebuilt(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    database = working / INDEX_FILENAME
    database.write_bytes(b"not sqlite")
    root = tmp_path / "photos"
    expected = _touch_images(root, ("a.jpg",))

    index = LibraryIndex(working)
    snapshot = index.refresh([str(root)], recursive=True)

    assert index.paths(snapshot.signature) == expected
    quarantined = list(working.glob("library-index.corrupt-*.sqlite3"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"not sqlite"


def test_incompatible_database_version_is_quarantined_and_rebuilt(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    database = working / INDEX_FILENAME
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    root = tmp_path / "photos"
    expected = _touch_images(root, ("a.jpg",))

    index = LibraryIndex(working)
    snapshot = index.refresh([str(root)], recursive=True)

    assert index.paths(snapshot.signature) == expected
    assert len(list(working.glob("library-index.corrupt-*.sqlite3"))) == 1


def test_operational_database_failure_does_not_quarantine_valid_index(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("a.jpg",))
    working = tmp_path / "working"
    index = LibraryIndex(working)
    index.refresh([str(root)], recursive=True)

    def fail_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("mint_background_switcher.library_index.sqlite3.connect", fail_connect)

    with pytest.raises(LibraryIndexError, match="database is locked"):
        index.snapshot("unused")

    assert index.database_path.is_file()
    assert list(working.glob("library-index.corrupt-*.sqlite3")) == []


def test_malformed_scan_metadata_is_quarantined_and_rebuilt(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("a.jpg",))
    working = tmp_path / "working"
    index = LibraryIndex(working)
    snapshot = index.refresh([str(root)], recursive=True)
    with sqlite3.connect(index.database_path) as connection:
        connection.execute("UPDATE scans SET roots_json = ? WHERE signature = ?", ("{", snapshot.signature))

    assert index.snapshot(snapshot.signature) is None
    assert len(list(working.glob("library-index.corrupt-*.sqlite3"))) == 1
    rebuilt = index.ensure([str(root)], recursive=True)
    assert rebuilt.image_count == 1


def test_stale_index_refreshes_and_discovers_new_images(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("a.jpg",))
    index = LibraryIndex(tmp_path / "working")
    first = index.ensure([str(root)], recursive=True, now_ns=1_000_000_000)
    _touch_images(root, ("b.jpg",))

    refreshed = index.ensure(
        [str(root)],
        recursive=True,
        max_age_seconds=1,
        now_ns=3_000_000_000,
    )

    assert first.image_count == 1
    assert refreshed.image_count == 2
    assert refreshed.refreshed_ns == 3_000_000_000


def test_empty_or_partially_unavailable_roots_are_retried_on_next_ensure(tmp_path):
    available = tmp_path / "available"
    returned = tmp_path / "removable-volume"
    _touch_images(available, ("always.jpg",))
    returned.mkdir()
    index = LibraryIndex(tmp_path / "working")
    incomplete = index.ensure(
        [str(available), str(returned)],
        recursive=True,
        now_ns=1_000_000_000,
    )
    returned_path = _touch_images(returned, ("returned.jpg",))[0]

    retried = index.ensure(
        [str(available), str(returned)],
        recursive=True,
        now_ns=2_000_000_000,
    )

    assert incomplete.image_count == 1
    assert incomplete.refreshed_ns == 0
    assert retried.image_count == 2
    assert returned_path in index.paths(retried.signature)


def test_changed_roots_keep_independent_index_snapshots(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_paths = _touch_images(first_root, ("a.jpg",))
    second_paths = _touch_images(second_root, ("b.jpg",))
    index = LibraryIndex(tmp_path / "working")

    first = index.refresh([str(first_root)], recursive=True)
    second = index.refresh([str(second_root)], recursive=True)

    assert first.signature != second.signature
    assert index.paths(first.signature) == first_paths
    assert index.paths(second.signature) == second_paths


def test_refresh_adds_paths_without_resetting_current_no_repeat_cycle(tmp_path):
    root = tmp_path / "photos"
    original = _touch_images(root, ("a.jpg", "b.jpg", "c.jpg"))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)
    first = index.draw(snapshot.signature, "bucket", 1, rng=random.Random(2))
    _touch_images(root, ("d.jpg",))

    refreshed = index.refresh([str(root)], recursive=True)
    rest_of_cycle = index.draw(refreshed.signature, "bucket", 2, rng=random.Random(3))

    assert len(set(first + rest_of_cycle)) == 3
    assert set(first + rest_of_cycle) == set(original)
    assert refreshed.image_count == 4


def test_database_path_directory_is_rejected_without_fallback(tmp_path):
    working = tmp_path / "working"
    (working / INDEX_FILENAME).mkdir(parents=True)
    index = LibraryIndex(working)

    with pytest.raises(LibraryIndexError, match="not a regular file"):
        index.snapshot("unused")