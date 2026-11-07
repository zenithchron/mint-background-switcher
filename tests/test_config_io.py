import json

import pytest

from mint_background_switcher import cli
from mint_background_switcher.config import CONFIG_VERSION, Config, Profile, load_config
from mint_background_switcher.config_io import (
    EXPORT_FORMAT,
    EXPORT_FORMAT_VERSION,
    ConfigImportError,
    export_config,
    export_document,
    import_settings,
    load_export,
)


def _rich_config() -> Config:
    """A config exercising every profile field plus the application-level values."""
    office = Profile(
        name="Office",
        interval_minutes=45.0,
        mode="montage",
        recursive=False,
        min_image_size=720,
        ignore_hidden=True,
        ignore_patterns=["thumb*.jpg"],
        image_types=["jpg", "png"],
        sequential=True,
        match_orientation=True,
        postcard_captions=True,
        polaroid_captions=True,
        rotate_on_startup=False,
        night_black_screen=True,
        night_start="21:30",
        night_end="05:15",
        mirror_lockscreen=True,
        suppress_process="firefox",
        suppress_on_battery=True,
        suppress_remote_session=True,
        idle_only=True,
        idle_seconds=120,
        suppress_when_locked=True,
        excluded_images=["/pics/old/one.jpg", "/pics/old/two.png"],
        shared_folders=["/pics/office", "/pics/shared"],
        monitor_folders={"DP-1": ["/pics/primary"], "HDMI-1": ["/pics/secondary"]},
        black_hotkey="<Ctrl>b",
        next_hotkey="<Ctrl>n",
        pause_hotkey="<Ctrl>p",
        desktop="cinnamon",
        effect="sepia",
        bar_color="blurred",
        fit_mode="scale_and_blur",
        postcard_background="corkboard",
        postcard_count=6,
        postcard_size=0.7,
        postcard_span=True,
        postcard_tilt=False,
        polaroid_count=5,
        polaroid_size=0.4,
        polaroid_span=False,
        polaroid_tilt=True,
    )
    home = Profile(name="Home", shared_folders=["/pics/home"], mode="same", interval_minutes=20.0)
    return Config(active_profile="Office", profiles={"Home": home, "Office": office}, working_directory="/working")


def test_export_document_shape_and_determinism():
    document = export_document(_rich_config())

    assert set(document) == {"format", "format_version", "config"}
    assert document["format"] == EXPORT_FORMAT
    assert document["format_version"] == EXPORT_FORMAT_VERSION
    assert document["config"]["version"] == CONFIG_VERSION
    assert export_document(_rich_config()) == document


def test_export_import_roundtrip_preserves_everything(tmp_path):
    source_config = _rich_config()
    export_path = tmp_path / "backup.json"
    config_path = tmp_path / "config" / "config.json"
    destination_config = Config.default(folder="/elsewhere")

    assert export_config(source_config, export_path) == export_path
    # Import into a fresh installation's config path.
    import_settings(export_path, config_path)

    loaded = load_config(config_path)
    assert loaded.to_dict() == source_config.to_dict()
    assert loaded.active_profile == "Office"
    assert loaded.working_directory == "/working"
    office = loaded.get_profile("Office")
    assert office.mode == "montage"
    assert office.night_start == "21:30"
    assert office.excluded_images == ["/pics/old/one.jpg", "/pics/old/two.png"]
    assert office.folders_for_monitor("DP-1") == ["/pics/primary"]
    assert office.folders_for_monitor("missing") == ["/pics/office", "/pics/shared"]
    # The pre-existing (different) config was fully replaced.
    assert destination_config.working_directory is None
    assert set(loaded.profiles) == {"Home", "Office"}


def test_import_replaces_working_directory_not_preserved(tmp_path):
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True)
    current = Config.default(folder="/pics")
    current.working_directory = "/old/working"
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")

    donor = Config.default(folder="/pics")
    donor.working_directory = "/new/working"
    export_path = tmp_path / "donor.json"
    export_config(donor, export_path)

    imported = import_settings(export_path, config_path)

    assert imported.working_directory == "/new/working"
    assert load_config(config_path).working_directory == "/new/working"


def test_import_accepts_raw_config_file(tmp_path):
    config_path = tmp_path / "config" / "config.json"
    current = Config.default(folder="/pics")
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")

    donor = Config(active_profile="D", profiles={"D": Profile(name="D", shared_folders=["/pics/d"])}).to_dict()
    donor_path = tmp_path / "raw-config.json"
    donor_path.write_text(json.dumps(donor), encoding="utf-8")

    imported = import_settings(donor_path, config_path)

    assert imported.active_profile == "D"
    assert set(imported.profiles) == {"D"}
    assert load_config(config_path).to_dict() == Config.from_dict(donor).to_dict()


def test_import_invalid_files_raise_and_leave_destination_unchanged(tmp_path):
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True)
    current = Config.default(folder="/pics")
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
    before = config_path.read_bytes()

    bad_files = {
        "not-json.json": "this is not json {",
        "array.json": json.dumps(["a", "b"]),
        "scalar.json": json.dumps(42),
        "empty-object.json": json.dumps({}),
        "no-profiles.json": json.dumps({"version": CONFIG_VERSION, "active_profile": "P"}),
        "empty-profiles.json": json.dumps({"version": CONFIG_VERSION, "profiles": {}}),
        "string-profiles.json": json.dumps({"profiles": "P"}),
        "malformed-profile.json": json.dumps({"profiles": {"P": 5}}),
        "blank-profile-name.json": json.dumps({"profiles": {"  ": {}}}),
        "non-dict-wrapper-config.json": json.dumps({"format": EXPORT_FORMAT, "config": "nope"}),
    }
    for name, content in bad_files.items():
        bad_path = tmp_path / name
        bad_path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigImportError):
            import_settings(bad_path, config_path)
        with pytest.raises(ConfigImportError):
            load_export(bad_path)

    missing = tmp_path / "missing.json"
    with pytest.raises(ConfigImportError):
        load_export(missing)

    assert config_path.read_bytes() == before
    assert load_config(config_path).to_dict() == current.to_dict()


def test_import_rejects_directory_destination(tmp_path):
    donor = Config.default(folder="/pics")
    export_path = tmp_path / "donor.json"
    export_config(donor, export_path)

    with pytest.raises(ConfigImportError):
        import_settings(export_path, tmp_path)


def test_export_creates_parent_directories(tmp_path):
    destination = tmp_path / "deep" / "nested" / "backup.json"
    export_config(_rich_config(), destination)
    assert destination.exists()


def test_cli_export_to_file_and_stdout(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    rich = _rich_config()
    rich.working_directory = None
    from mint_background_switcher.config import save_config

    save_config(rich)

    destination = tmp_path / "out" / "backup.json"
    assert cli.main(["export", str(destination)]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == str(destination)
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["config"] == load_config().to_dict()

    # Without a destination the export document goes to stdout.
    assert cli.main(["export"]) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == export_document(load_config())


def test_cli_import_dry_run_validates_without_mutating(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True)
    current = Config.default(folder="/pics")
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
    before = config_path.read_bytes()

    donor = _rich_config()
    export_path = tmp_path / "donor.json"
    export_config(donor, export_path)

    assert cli.main(["import", str(export_path), "--dry-run"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["profile_count"] == 2
    assert summary["profiles"] == ["Home", "Office"]
    assert summary["active_profile"] == "Office"
    assert summary["working_directory"] == "/working"
    assert config_path.read_bytes() == before


def test_cli_import_replaces_settings(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    current = Config.default(folder="/pics")
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.json").write_text(json.dumps(current.to_dict()), encoding="utf-8")

    donor = _rich_config()
    export_path = tmp_path / "donor.json"
    export_config(donor, export_path)

    assert cli.main(["import", str(export_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is False
    assert summary["active_profile"] == "Office"
    assert load_config().to_dict() == donor.to_dict()


def test_cli_import_invalid_file_fails_and_keeps_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True)
    current = Config.default(folder="/pics")
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
    before = config_path.read_bytes()

    bad = tmp_path / "bad.json"
    bad.write_text("nope", encoding="utf-8")

    assert cli.main(["import", str(bad)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("import failed:")
    assert config_path.read_bytes() == before


def test_export_refuses_live_config_destination(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    from mint_background_switcher.paths import config_file

    # No config.json exists yet: exporting onto its path must be refused
    # before anything is written.
    with pytest.raises(ValueError, match="refusing to export onto the live settings file"):
        export_config(_rich_config(), config_file())
    assert not config_file().exists()

    from mint_background_switcher.config import save_config

    current = Config.default(folder="/pics")
    save_config(current)
    before = config_file().read_bytes()
    with pytest.raises(ValueError, match="refusing to export onto the live settings file"):
        export_config(_rich_config(), config_file())
    assert config_file().read_bytes() == before


def test_load_config_recovers_wrapped_document_written_over_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    from mint_background_switcher.paths import config_file

    current = Config.default(folder="/pics")
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(current.to_dict()), encoding="utf-8")

    # Simulate the historical accident: a wrapped export overwrote config.json.
    rich = _rich_config()
    config_file().write_text(json.dumps(export_document(rich)), encoding="utf-8")

    recovered = load_config()
    assert recovered.to_dict() == rich.to_dict()
    assert "Office" in recovered.profiles


def test_load_export_non_utf8_file_raises(tmp_path):
    bad = tmp_path / "legacy.json"
    bad.write_bytes(b"\xff\xfe\x00broken")
    with pytest.raises(ConfigImportError, match="not valid UTF-8"):
        load_export(bad)


def test_cli_import_non_utf8_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True)
    current = Config.default(folder="/pics")
    config_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
    before = config_path.read_bytes()

    bad = tmp_path / "legacy.json"
    bad.write_bytes(b"\xff\xfe\x00broken")

    assert cli.main(["import", str(bad)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("import failed:")
    assert "Traceback" not in err
    assert config_path.read_bytes() == before


def test_cli_export_failure_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    # A directory component that is actually a file guarantees an OSError
    # no matter which user the tests run as.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    assert cli.main(["export", str(blocker / "backup.json")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("export failed:")
    assert "Traceback" not in err


def test_export_import_unicode_round_trip(tmp_path):
    unicode_profile = Profile(
        name="Été ☀️",
        shared_folders=["/bilder/sonnig", "/photos/naïve"],
        excluded_images=["/bilder/übersicht.png"],
        monitor_folders={"DP-1": ["/moniteur/secondaire"]},
    )
    config = Config(
        active_profile="Été ☀️",
        profiles={"Été ☀️": unicode_profile},
        working_directory="/travail/été",
    )
    destination = tmp_path / "unicode.json"
    export_config(config, destination)
    imported = load_export(destination)
    assert imported.to_dict() == config.to_dict()
