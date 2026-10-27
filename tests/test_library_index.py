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
    normalized_ignore_patterns,
    normalized_scan_roots,
    orientation_matches,
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


def test_scan_signature_changes_with_ignore_hidden(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    roots = normalized_scan_roots([str(root)])

    assert scan_signature(roots, recursive=True) == scan_signature(roots, recursive=True, ignore_hidden=False)
    assert scan_signature(roots, recursive=True) != scan_signature(roots, recursive=True, ignore_hidden=True)


def test_refresh_ignores_hidden_files_and_folders(tmp_path):
    root = tmp_path / "photos"
    hidden = root / ".hidden"
    hidden.mkdir(parents=True)
    visible = root / "visible.jpg"
    visible.write_bytes(b"image")
    hidden_file = root / ".hidden-file.jpg"
    hidden_file.write_bytes(b"image")
    hidden_nested = hidden / "nested.jpg"
    hidden_nested.write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")

    default = index.refresh([str(root)], recursive=True)
    assert default.image_count == 3

    filtered = index.refresh([str(root)], recursive=True, ignore_hidden=True)
    assert filtered.image_count == 1
    assert index.paths(filtered.signature) == [str(visible.resolve())]


def test_ignore_hidden_still_scans_explicit_hidden_root(tmp_path):
    root = tmp_path / ".wallpapers"
    inner = root / "inner"
    inner.mkdir(parents=True)
    deep = root / ".deep"
    deep.mkdir()
    top = root / "top.jpg"
    top.write_bytes(b"image")
    inner_image = inner / "inner.jpg"
    inner_image.write_bytes(b"image")
    (deep / "deep.jpg").write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=True, ignore_hidden=True)

    # The explicitly configured root is scanned; hidden folders below it are not.
    assert sorted(index.paths(snapshot.signature)) == sorted(
        [str(top.resolve()), str(inner_image.resolve())]
    )


def test_nonrecursive_refresh_ignores_hidden_files(tmp_path):
    root = tmp_path / "photos"
    visible, hidden = _touch_images(root, ("a.jpg", ".hidden.jpg"))
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=False, ignore_hidden=True)

    assert index.paths(snapshot.signature) == [visible]


def test_ensure_reuses_index_for_same_hidden_setting_and_refreshes_on_toggle(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    deep = root / ".deep"
    deep.mkdir(parents=True)
    (root / "a.jpg").write_bytes(b"image")
    (deep / "b.jpg").write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")
    first = index.ensure([str(root)], recursive=True, ignore_hidden=True, now_ns=1_000_000_000)
    assert first.image_count == 1

    real_walk = os.walk
    walk_calls = []

    def spy_walk(*args, **kwargs):
        walk_calls.append(args)
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(os, "walk", spy_walk)
    reused = index.ensure([str(root)], recursive=True, ignore_hidden=True, now_ns=1_000_000_000 + 1)
    assert reused == first
    assert walk_calls == []

    toggled = index.ensure([str(root)], recursive=True, ignore_hidden=False, now_ns=1_000_000_000 + 2)
    assert toggled.image_count == 2
    assert len(walk_calls) == 1


def test_normalized_ignore_patterns_canonicalize_order_case_and_blanks():
    assert normalized_ignore_patterns([]) == ()
    assert normalized_ignore_patterns(["  ", ""]) == ()
    assert normalized_ignore_patterns(["b*", "A*", "b*"]) == ("a*", "b*")


def test_scan_signature_changes_with_ignore_patterns(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    roots = normalized_scan_roots([str(root)])

    assert scan_signature(roots, recursive=True) == scan_signature(
        roots, recursive=True, ignore_patterns=()
    )
    assert scan_signature(roots, recursive=True) != scan_signature(
        roots, recursive=True, ignore_patterns=["thumb*"]
    )
    # Equivalent inputs (case, order, duplicates, blanks) share one signature.
    assert scan_signature(roots, recursive=True, ignore_patterns=["a*", "b*"]) == scan_signature(
        roots, recursive=True, ignore_patterns=["B*", " A* ", "b*"]
    )
    assert scan_signature(roots, recursive=True, ignore_patterns=["a*"]) != scan_signature(
        roots, recursive=True, ignore_patterns=["b*"]
    )


def test_refresh_ignores_name_patterns(tmp_path):
    root = tmp_path / "photos"
    (root / "nested").mkdir(parents=True)
    visible = root / "photo.jpg"
    visible.write_bytes(b"image")
    thumb = root / "thumb-1.jpg"
    thumb.write_bytes(b"image")
    banner = root / "nested" / "Banner-2.png"
    banner.write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")

    default = index.refresh([str(root)], recursive=True)
    assert default.image_count == 3

    filtered = index.refresh([str(root)], recursive=True, ignore_patterns=["thumb*", "banner*"])
    assert filtered.image_count == 1
    assert index.paths(filtered.signature) == [str(visible.resolve())]


def test_nonrecursive_refresh_ignores_name_patterns(tmp_path):
    root = tmp_path / "photos"
    visible, thumb = _touch_images(root, ("photo.jpg", "thumb-1.jpg"))
    index = LibraryIndex(tmp_path / "working")

    snapshot = index.refresh([str(root)], recursive=False, ignore_patterns=["thumb*"])

    assert index.paths(snapshot.signature) == [visible]


def test_ignore_patterns_still_scan_explicit_matched_root(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    matched = root / "thumb-1.jpg"
    matched.write_bytes(b"image")
    other = root / "other.jpg"
    other.write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")

    # An explicitly configured individual picture matching a pattern stays in rotation.
    snapshot = index.refresh([str(matched)], recursive=True, ignore_patterns=["thumb*"])
    assert index.paths(snapshot.signature) == [str(matched.resolve())]

    # A matching folder name does not matter: its pictures are matched by name.
    snapshot = index.refresh([str(root)], recursive=True, ignore_patterns=["thumb*"])
    assert index.paths(snapshot.signature) == [str(other.resolve())]


def test_ensure_reuses_index_for_same_patterns_and_refreshes_on_change(monkeypatch, tmp_path):
    root = tmp_path / "photos"
    (root / "nested").mkdir(parents=True)
    (root / "a.jpg").write_bytes(b"image")
    (root / "nested" / "b.jpg").write_bytes(b"image")
    (root / "thumb-1.jpg").write_bytes(b"image")
    index = LibraryIndex(tmp_path / "working")
    first = index.ensure(
        [str(root)], recursive=True, ignore_patterns=["thumb*"], now_ns=1_000_000_000
    )
    assert first.image_count == 2

    real_walk = os.walk
    walk_calls = []

    def spy_walk(*args, **kwargs):
        walk_calls.append(args)
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(os, "walk", spy_walk)
    # Equivalent pattern inputs (case/whitespace/order) reuse the same index.
    reused = index.ensure(
        [str(root)], recursive=True, ignore_patterns=["THUMB* ", "thumb*"], now_ns=1_000_000_001
    )
    assert reused == first
    assert walk_calls == []

    changed = index.ensure(
        [str(root)], recursive=True, ignore_patterns=["thumb*", "b*"], now_ns=1_000_000_002
    )
    assert changed.image_count == 1
    assert len(walk_calls) == 1


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


def test_sequential_draw_cycles_in_folder_order_and_wraps(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("c.jpg", "a.jpg", "b.jpg"))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)
    ordered = index.paths(snapshot.signature)
    assert ordered == sorted(ordered)

    first = index.draw(snapshot.signature, "bucket", 2, sequential=True)
    second = index.draw(snapshot.signature, "bucket", 2, sequential=True)
    third = index.draw(snapshot.signature, "bucket", 2, sequential=True)

    assert first == ordered[:2]
    assert second == [ordered[2], ordered[0]]
    assert third == [ordered[1], ordered[2]]
    assert index.remaining_count(snapshot.signature, "bucket") == 0


def test_sequential_draw_through_selection_transaction_keeps_order(tmp_path):
    root = tmp_path / "photos"
    _touch_images(root, ("c.jpg", "a.jpg", "b.jpg"))
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)
    ordered = index.paths(snapshot.signature)

    with index.selection() as selection:
        first = selection.draw(snapshot.signature, "bucket", 2, sequential=True)
        second = selection.draw(snapshot.signature, "bucket", 1, sequential=True)

    assert first == ordered[:2]
    assert second == [ordered[2]]


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


def _save_sized_image(path: Path, width: int, height: int) -> None:
    Image.new("RGB", (width, height), (4, 5, 6)).save(path)


def test_orientation_matches_rules():
    # No requirement and square monitors accept every picture.
    assert orientation_matches(None, "portrait") is True
    assert orientation_matches("square", "landscape") is True
    # Unreadable or square pictures may serve any monitor.
    assert orientation_matches("landscape", "unknown") is True
    assert orientation_matches("landscape", "square") is True
    assert orientation_matches("portrait", "square") is True
    # Otherwise the orientations must be equal.
    assert orientation_matches("landscape", "landscape") is True
    assert orientation_matches("portrait", "portrait") is True
    assert orientation_matches("landscape", "portrait") is False
    assert orientation_matches("portrait", "landscape") is False


def test_cached_orientation_reads_header_and_invalidates_on_file_change(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    picture = root / "l.png"
    _save_sized_image(picture, 120, 80)
    index = LibraryIndex(tmp_path / "working")

    key = str(picture.absolute())
    assert index.cached_orientation(key) == "landscape"
    assert index.cached_orientation(key) == "landscape"

    _save_sized_image(picture, 80, 120)
    stamp = os.lstat(picture).st_mtime_ns + 10**9
    os.utime(picture, ns=(stamp, stamp))
    assert index.cached_orientation(key) == "portrait"


def test_oriented_draw_prefers_matching_pictures_and_square_serves_any(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    landscape = root / "l.png"
    _save_sized_image(landscape, 120, 80)
    portrait = root / "p.png"
    _save_sized_image(portrait, 80, 120)
    square = root / "s.png"
    _save_sized_image(square, 80, 80)
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)

    chosen = index.draw(snapshot.signature, "bucket", 2, sequential=True, orientations=("landscape", "portrait"))
    assert chosen == [str(landscape.absolute()), str(portrait.absolute())]

    # The remaining square picture may serve any monitor orientation.
    assert index.draw(snapshot.signature, "bucket", 1, sequential=True, orientations=("landscape",)) == [
        str(square.absolute())
    ]


def test_oriented_draw_falls_back_when_pool_has_no_matching_picture(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    first = root / "a.png"
    _save_sized_image(first, 80, 120)
    second = root / "b.png"
    _save_sized_image(second, 90, 150)
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)

    chosen = index.draw(
        snapshot.signature, "bucket", 2, sequential=True, orientations=("landscape", "landscape")
    )
    assert chosen == [str(first.absolute()), str(second.absolute())]


def test_oriented_draw_reuses_pictures_when_pool_is_smaller_than_slot_count(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    only = root / "a.png"
    _save_sized_image(only, 120, 80)
    index = LibraryIndex(tmp_path / "working")
    snapshot = index.refresh([str(root)], recursive=True)

    # One picture for two landscape slots: the pool wraps around and reuses
    # the picture instead of leaving a slot unfilled, matching draw_many.
    chosen = index.draw(
        snapshot.signature, "bucket", 2, sequential=True, orientations=("landscape", "landscape")
    )
    assert chosen == [str(only.absolute()), str(only.absolute())]