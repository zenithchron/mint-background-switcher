import json
from pathlib import Path
import threading
import time

from PIL import Image
import pytest

from mint_background_switcher import service, state as state_module, working_storage as working_storage_module
from mint_background_switcher.config import Config, Profile, load_config, save_config
from mint_background_switcher.monitor import Monitor
from mint_background_switcher.state import RuntimeState, load_state, save_state
from mint_background_switcher.working_storage import (
    FOREIGN_DIRECTORY_MESSAGE,
    MARKER_FILENAME,
    WorkingDirectoryError,
    WorkingDirectoryMigrationCancelled,
    WorkingDirectoryOverlapError,
    configured_working_directory,
    create_working_directory,
    migrate_working_directory,
    prepare_working_directory,
    validate_working_directory,
)


def _config(*folders: Path, working_directory: Path | None = None) -> Config:
    return Config(
        active_profile="P",
        profiles={"P": Profile(name="P", shared_folders=[str(folder) for folder in folders])},
        working_directory=str(working_directory) if working_directory is not None else None,
    )


def test_default_working_directory_preserves_xdg_cache_override(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("MBS_CACHE_DIR", str(cache))

    assert configured_working_directory(_config()) == cache.absolute()


def test_custom_working_directory_overrides_default_cache(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    custom = tmp_path / "custom"
    monkeypatch.setenv("MBS_CACHE_DIR", str(cache))

    assert configured_working_directory(_config(working_directory=custom)) == custom.absolute()


def test_prepare_empty_working_directory_writes_owner_marker(tmp_path):
    candidate = tmp_path / "working"
    candidate.mkdir()

    prepared = prepare_working_directory(candidate, _config())

    assert prepared == candidate.resolve()
    marker = json.loads((candidate / MARKER_FILENAME).read_text(encoding="utf-8"))
    assert marker == {"application": "mint-background-switcher", "schema": 1}
    assert validate_working_directory(candidate, _config(), require_marker=True) == candidate.resolve()


def test_foreign_nonempty_directory_is_rejected_without_changes(tmp_path):
    candidate = tmp_path / "working"
    candidate.mkdir()
    foreign = candidate / "family-photo.jpg"
    foreign.write_bytes(b"do not touch")

    with pytest.raises(WorkingDirectoryError, match=FOREIGN_DIRECTORY_MESSAGE):
        prepare_working_directory(candidate, _config())

    assert foreign.read_bytes() == b"do not touch"
    assert not (candidate / MARKER_FILENAME).exists()


@pytest.mark.parametrize("placement", ["same", "inside", "contains"])
def test_working_directory_must_not_overlap_source_folders(tmp_path, placement):
    source = tmp_path / "photos"
    source.mkdir()
    if placement == "same":
        candidate = source
    elif placement == "inside":
        candidate = source / "generated"
        candidate.mkdir()
    else:
        candidate = tmp_path

    with pytest.raises(WorkingDirectoryError, match="overlaps a wallpaper source folder"):
        prepare_working_directory(candidate, _config(source))


def test_create_working_directory_creates_one_explicit_child_and_marker(tmp_path):
    parent = tmp_path / "external-drive"
    parent.mkdir()

    created = create_working_directory(parent, "MBS Working Files", _config())

    assert created == (parent / "MBS Working Files").resolve()
    assert (created / MARKER_FILENAME).is_file()


@pytest.mark.parametrize("name", ["", ".", "..", "nested/folder", "nested\\folder", "bad\nname"])
def test_create_working_directory_rejects_unsafe_child_name(tmp_path, name):
    parent = tmp_path / "parent"
    parent.mkdir()

    with pytest.raises(WorkingDirectoryError, match="folder name"):
        create_working_directory(parent, name, _config())

    assert list(parent.iterdir()) == []


def _setup_migration(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    source = tmp_path / "default-cache"
    source.mkdir()
    monkeypatch.setenv("MBS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MBS_CACHE_DIR", str(source))
    config = _config()
    save_config(config)
    return config, source


def test_migration_copies_only_managed_files_updates_state_and_retains_source(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    active = source / "P-active-1.png"
    active.write_bytes(b"active wallpaper")
    preview = source / "P-dry-run.png"
    preview.write_bytes(b"preview")
    database = source / "library-index.sqlite3"
    database.write_bytes(b"sqlite placeholder")
    log = source / "tray.log"
    log.write_text("local diagnostic\n", encoding="utf-8")
    save_state(RuntimeState(last_wallpaper=str(active), last_images=["/photos/original.jpg"]))
    target = tmp_path / "external" / "MBS"
    target.parent.mkdir()
    target.mkdir()
    progress = []

    result = migrate_working_directory(
        config,
        target,
        progress=lambda completed, total, name: progress.append((completed, total, name)),
    )

    assert result.source == source.resolve()
    assert result.destination == target.resolve()
    assert set(result.copied_names) == {"P-active-1.png", "P-dry-run.png", "library-index.sqlite3"}
    assert (target / "P-active-1.png").read_bytes() == b"active wallpaper"
    assert (target / "P-dry-run.png").read_bytes() == b"preview"
    assert (target / "library-index.sqlite3").read_bytes() == b"sqlite placeholder"
    assert not (target / "tray.log").exists()
    assert active.read_bytes() == b"active wallpaper"
    assert preview.read_bytes() == b"preview"
    assert database.read_bytes() == b"sqlite placeholder"
    assert log.read_text(encoding="utf-8") == "local diagnostic\n"
    assert load_config().working_directory == str(target.resolve())
    assert load_state().last_wallpaper == str(target.resolve() / active.name)
    assert load_state().last_images == ["/photos/original.jpg"]
    assert progress[-1][:2] == (3, 3)


def test_migration_rejects_destination_collision_without_switching(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    (source / "P-active-0.png").write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)
    collision = target / "P-active-0.png"
    collision.write_bytes(b"unrelated target")

    with pytest.raises(WorkingDirectoryError, match="already contains"):
        migrate_working_directory(config, target)

    assert load_config().working_directory is None
    assert collision.read_bytes() == b"unrelated target"
    assert (source / "P-active-0.png").read_bytes() == b"source"


def test_migration_rejects_reserved_symlink_even_when_source_name_is_absent(monkeypatch, tmp_path):
    config, _source = _setup_migration(monkeypatch, tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"must remain untouched")
    reserved = target / "P-active-1.png"
    reserved.symlink_to(unrelated)

    with pytest.raises(WorkingDirectoryError, match="already contains"):
        migrate_working_directory(config, target)

    assert reserved.is_symlink()
    assert unrelated.read_bytes() == b"must remain untouched"
    assert load_config().working_directory is None


def test_migration_preserves_profile_saved_while_copy_is_paused(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    (source / "P-active-0.png").write_bytes(b"generated")
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)
    copy_started = threading.Event()
    release_copy = threading.Event()
    original_copy = working_storage_module._copy_verified

    def blocked_copy(copy_source, staged_file, cancelled):
        copy_started.set()
        assert release_copy.wait(3)
        original_copy(copy_source, staged_file, cancelled)

    monkeypatch.setattr(working_storage_module, "_copy_verified", blocked_copy)
    errors = []

    def migrate():
        try:
            migrate_working_directory(config, target)
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            errors.append(exc)

    worker = threading.Thread(target=migrate)
    worker.start()
    assert copy_started.wait(3)
    concurrent = load_config()
    concurrent.profiles["Concurrent"] = Profile(name="Concurrent", shared_folders=["/new/profile"])
    save_config(concurrent)
    release_copy.set()
    worker.join(3)

    assert not worker.is_alive()
    assert errors == []
    saved = load_config()
    assert "Concurrent" in saved.profiles
    assert saved.working_directory == str(target.resolve())


def test_migration_revalidates_concurrent_profile_overlap_before_activation(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"generated")
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)
    copy_started = threading.Event()
    release_copy = threading.Event()
    original_copy = working_storage_module._copy_verified

    def blocked_copy(copy_source, staged_file, cancelled):
        copy_started.set()
        assert release_copy.wait(3)
        original_copy(copy_source, staged_file, cancelled)

    monkeypatch.setattr(working_storage_module, "_copy_verified", blocked_copy)
    errors = []

    def migrate():
        try:
            migrate_working_directory(config, target)
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            errors.append(exc)

    worker = threading.Thread(target=migrate)
    worker.start()
    assert copy_started.wait(3)
    concurrent = load_config()
    concurrent.profiles["Unsafe"] = Profile(name="Unsafe", shared_folders=[str(target)])
    save_config(concurrent)
    release_copy.set()
    worker.join(3)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], WorkingDirectoryOverlapError)
    saved = load_config()
    assert "Unsafe" in saved.profiles
    assert saved.working_directory is None
    assert source_file.read_bytes() == b"generated"
    assert not (target / source_file.name).exists()


def test_rotation_waits_for_migration_inventory_and_uses_new_folder(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (24, 16), (30, 90, 180)).save(photos / "photo.png")
    config.profiles["P"].shared_folders = [str(photos)]
    save_config(config)
    active = source / "P-active-0.png"
    active.write_bytes(b"previous generated wallpaper")
    save_state(RuntimeState(last_wallpaper=str(active), wallpaper_slot=0))
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)

    inventory_ready = threading.Event()
    release_inventory = threading.Event()
    original_source_files = working_storage_module._source_files

    def paused_inventory(live_config, live_source):
        files = original_source_files(live_config, live_source)
        inventory_ready.set()
        assert release_inventory.wait(3)
        return files

    class Setter:
        def __init__(self, *, dry_run=False):
            self.dry_run = dry_run

        def apply(self, _wallpaper, _desktop):
            return None

    monkeypatch.setattr(working_storage_module, "_source_files", paused_inventory)
    monkeypatch.setattr(service, "detect_monitors", lambda: [Monitor("A", 80, 60, 0, 0)])
    monkeypatch.setattr(service, "DesktopSetter", Setter)
    migration_errors = []
    rotation_errors = []
    rotation_results = []

    def migrate():
        try:
            migrate_working_directory(config, target)
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            migration_errors.append(exc)

    def rotate():
        try:
            rotation_results.append(service.switch_once("P"))
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            rotation_errors.append(exc)

    migration_worker = threading.Thread(target=migrate)
    migration_worker.start()
    assert inventory_ready.wait(3)
    rotation_worker = threading.Thread(target=rotate)
    rotation_worker.start()
    time.sleep(0.1)
    assert rotation_worker.is_alive()
    release_inventory.set()
    migration_worker.join(5)
    rotation_worker.join(5)

    assert not migration_worker.is_alive()
    assert not rotation_worker.is_alive()
    assert migration_errors == []
    assert rotation_errors == []
    assert rotation_results[0].wallpaper.parent == target.resolve()
    last_wallpaper = load_state().last_wallpaper
    assert last_wallpaper is not None
    assert Path(last_wallpaper).parent == target.resolve()


def test_migration_never_overwrites_collision_created_after_preflight(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()
    original_copy = __import__(
        "mint_background_switcher.working_storage",
        fromlist=["_copy_verified"],
    )._copy_verified

    def copy_then_race(copy_source, staged_file, cancelled):
        original_copy(copy_source, staged_file, cancelled)
        (target / copy_source.name).write_bytes(b"racer")

    monkeypatch.setattr("mint_background_switcher.working_storage._copy_verified", copy_then_race)

    with pytest.raises(WorkingDirectoryError, match="already contains"):
        migrate_working_directory(config, target)

    assert (target / source_file.name).read_bytes() == b"racer"
    assert source_file.read_bytes() == b"source"
    assert load_config().working_directory is None


def test_migration_rejects_destination_inside_current_working_folder(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    target = source / "nested"
    target.mkdir()

    with pytest.raises(WorkingDirectoryOverlapError, match="must not contain"):
        migrate_working_directory(config, target)

    assert load_config().working_directory is None
    assert not (target / MARKER_FILENAME).exists()


def test_migration_rejects_destination_containing_current_working_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    outer = tmp_path / "outer"
    outer.mkdir()
    base_config = _config()
    prepare_working_directory(outer, base_config)
    source = outer / "current"
    source.mkdir()
    prepare_working_directory(source, base_config)
    config = _config(working_directory=source)
    save_config(config)

    with pytest.raises(WorkingDirectoryOverlapError, match="must not contain"):
        migrate_working_directory(config, outer)

    assert load_config().working_directory == str(source)


def test_migration_cancellation_keeps_old_location_active(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    (source / "P-active-0.png").write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(WorkingDirectoryMigrationCancelled, match="cancelled"):
        migrate_working_directory(config, target, cancelled=lambda: True)

    assert load_config().working_directory is None
    assert not (target / "P-active-0.png").exists()
    assert (source / "P-active-0.png").read_bytes() == b"source"


@pytest.mark.parametrize("cancel_on_call", [4, 8])
def test_migration_cancellation_cleans_partial_copy_and_install(monkeypatch, tmp_path, cancel_on_call):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    payload = b"migration-source" + b"x" * (3 * 1024 * 1024)
    source_file.write_bytes(payload)
    target = tmp_path / "target"
    target.mkdir()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= cancel_on_call

    with pytest.raises(WorkingDirectoryMigrationCancelled, match="cancelled"):
        migrate_working_directory(config, target, cancelled=cancelled)

    assert calls >= cancel_on_call
    assert source_file.read_bytes() == payload
    assert load_config().working_directory is None
    assert not (target / source_file.name).exists()
    assert list(target.glob(".mbs-migration-*")) == []


def test_unexpected_staging_child_fails_before_activation(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()
    original_install = working_storage_module._install_exclusive

    def install_then_leave_residue(staged_file, target_file, cancelled):
        identity = original_install(staged_file, target_file, cancelled)
        (staged_file.parent / "unexpected-child").mkdir()
        return identity

    monkeypatch.setattr(working_storage_module, "_install_exclusive", install_then_leave_residue)

    with pytest.raises(WorkingDirectoryError, match="staging directory contained unexpected entries"):
        migrate_working_directory(config, target)

    assert load_config().working_directory is None
    assert source_file.read_bytes() == b"source"
    assert not (target / source_file.name).exists()
    assert list(target.glob(".mbs-migration-*")) == []


def test_remove_staging_unlinks_symlink_without_touching_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    staging_link = tmp_path / ".mbs-migration-test-link"
    staging_link.symlink_to(outside, target_is_directory=True)

    working_storage_module._remove_staging(staging_link)

    assert not staging_link.exists()
    assert not staging_link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_migration_config_save_failure_keeps_old_disk_config(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    (source / "P-active-0.png").write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()

    def fail_save(_working_directory, **_kwargs):
        raise OSError("simulated config save failure")

    monkeypatch.setattr(working_storage_module, "replace_working_directory", fail_save)

    with pytest.raises(OSError, match="simulated config save failure"):
        migrate_working_directory(config, target)

    assert config.working_directory is None
    assert load_config().working_directory is None
    assert not (target / "P-active-0.png").exists()
    assert (source / "P-active-0.png").read_bytes() == b"source"


def test_migration_state_commit_failure_rolls_back_before_waiting_rotation(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (24, 16), (40, 100, 180)).save(photos / "photo.png")
    config.profiles["P"].shared_folders = [str(photos)]
    save_config(config)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"source")
    save_state(RuntimeState(last_wallpaper=str(source_file), wallpaper_slot=0))
    target = tmp_path / "target"
    target.mkdir()
    prepare_working_directory(target, config)

    commit_started = threading.Event()
    release_commit = threading.Event()
    original_atomic_write = state_module.atomic_write_json_unlocked
    failed_once = False

    def fail_first_state_commit(path, data):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            commit_started.set()
            assert release_commit.wait(3)
            raise OSError("simulated state save failure")
        original_atomic_write(path, data)

    class Setter:
        def __init__(self, *, dry_run=False):
            self.dry_run = dry_run

        def apply(self, _wallpaper, _desktop):
            return None

    monkeypatch.setattr(state_module, "atomic_write_json_unlocked", fail_first_state_commit)
    monkeypatch.setattr(service, "detect_monitors", lambda: [Monitor("A", 80, 60, 0, 0)])
    monkeypatch.setattr(service, "DesktopSetter", Setter)
    migration_errors = []
    rotation_errors = []
    rotation_results = []

    def migrate():
        try:
            migrate_working_directory(config, target)
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            migration_errors.append(exc)

    def rotate():
        try:
            rotation_results.append(service.switch_once("P"))
        except BaseException as exc:  # pragma: no cover - reported by assertions below
            rotation_errors.append(exc)

    migration_worker = threading.Thread(target=migrate)
    migration_worker.start()
    assert commit_started.wait(3)
    assert load_config().working_directory == str(target.resolve())
    rotation_worker = threading.Thread(target=rotate)
    rotation_worker.start()
    time.sleep(0.1)
    assert rotation_worker.is_alive()
    release_commit.set()
    migration_worker.join(5)
    rotation_worker.join(5)

    assert not migration_worker.is_alive()
    assert not rotation_worker.is_alive()
    assert len(migration_errors) == 1
    assert isinstance(migration_errors[0], OSError)
    assert rotation_errors == []
    assert rotation_results[0].wallpaper.parent == source.resolve()
    assert load_config().working_directory is None
    last_wallpaper = load_state().last_wallpaper
    assert last_wallpaper is not None
    assert Path(last_wallpaper).parent == source.resolve()
    assert not (target / source_file.name).exists()
    assert source_file.read_bytes() == b"source"


def test_missing_custom_working_directory_fails_without_default_fallback(monkeypatch, tmp_path):
    default_cache = tmp_path / "default-cache"
    default_cache.mkdir()
    monkeypatch.setenv("MBS_CACHE_DIR", str(default_cache))
    missing = tmp_path / "unmounted-drive" / "MBS"
    config = _config(working_directory=missing)

    with pytest.raises(WorkingDirectoryError, match="does not exist"):
        validate_working_directory(configured_working_directory(config), config, require_marker=True)

    assert configured_working_directory(config) == missing.absolute()


def test_read_only_working_directory_is_rejected(tmp_path):
    target = tmp_path / "read-only"
    target.mkdir(mode=0o500)
    try:
        with pytest.raises(WorkingDirectoryError, match="not writable"):
            prepare_working_directory(target, _config())
    finally:
        target.chmod(0o700)


def test_symlinked_owner_marker_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    real_marker = tmp_path / "marker.json"
    real_marker.write_text(json.dumps({"application": "mint-background-switcher", "schema": 1}))
    (target / MARKER_FILENAME).symlink_to(real_marker)

    with pytest.raises(WorkingDirectoryError, match="not a regular file"):
        prepare_working_directory(target, _config())


def test_migration_same_directory_symlink_alias_is_a_noop(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    alias = tmp_path / "cache-alias"
    alias.symlink_to(source, target_is_directory=True)

    result = migrate_working_directory(config, alias)

    assert result.source == source.resolve()
    assert result.destination == source.resolve()
    assert result.copied_names == ()
    assert load_config().working_directory is None


def test_migration_copy_failure_keeps_old_location_active(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr(
        "mint_background_switcher.working_storage._copy_verified",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("simulated copy failure")),
    )

    with pytest.raises(OSError, match="simulated copy failure"):
        migrate_working_directory(config, target)

    assert load_config().working_directory is None
    assert not (target / source_file.name).exists()
    assert list(target.glob(".mbs-migration-*")) == []
    assert source_file.read_bytes() == b"source"


def test_migration_verification_failure_keeps_old_location_active(monkeypatch, tmp_path):
    config, source = _setup_migration(monkeypatch, tmp_path)
    source_file = source / "P-active-0.png"
    source_file.write_bytes(b"source")
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr("mint_background_switcher.working_storage._sha256", lambda *_args, **_kwargs: "wrong")

    with pytest.raises(WorkingDirectoryError, match="verification failed"):
        migrate_working_directory(config, target)

    assert load_config().working_directory is None
    assert not (target / source_file.name).exists()
    assert list(target.glob(".mbs-migration-*")) == []
    assert source_file.read_bytes() == b"source"