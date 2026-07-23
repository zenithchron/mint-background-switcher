import json

from mint_background_switcher.config import Config, Profile, load_config, replace_working_directory, save_config


def test_config_roundtrip():
    cfg = Config(
        active_profile="P",
        profiles={
            "P": Profile(
                name="P",
                mode="per-monitor",
                shared_folders=["/pics"],
                monitor_folders={"HDMI-1": ["/a", "/b"]},
            )
        },
        working_directory="/working",
    )
    data = cfg.to_dict()
    loaded = Config.from_dict(json.loads(json.dumps(data)))
    profile = loaded.get_profile()
    assert loaded.active_profile == "P"
    assert loaded.working_directory == "/working"
    assert profile.mode == "per-monitor"
    assert profile.folders_for_monitor("HDMI-1") == ["/a", "/b"]
    assert profile.folders_for_monitor("missing") == ["/pics"]


def test_stale_profile_save_preserves_newer_working_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    initial = Config(active_profile="P", profiles={"P": Profile(name="P")})
    save_config(initial)
    stale_editor = load_config()
    replace_working_directory("/new/working", expected=None)
    stale_editor.profiles["P"].mode = "postcard"

    save_config(stale_editor)

    saved = load_config()
    assert saved.working_directory == "/new/working"
    assert saved.profiles["P"].mode == "postcard"


def test_missing_or_invalid_working_directory_uses_default():
    missing = Config.from_dict({"active_profile": "P", "profiles": {"P": {}}})
    invalid = Config.from_dict(
        {"active_profile": "P", "working_directory": ["not", "a", "path"], "profiles": {"P": {}}}
    )

    assert missing.working_directory is None
    assert invalid.working_directory is None


def test_same_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "same"}}})
    assert cfg.get_profile().mode == "same"


def test_montage_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "MONTAGE"}}})
    assert cfg.get_profile().mode == "montage"


def test_postcard_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "POSTCARD"}}})
    assert cfg.get_profile().mode == "postcard"


def test_effects_roundtrip_and_invalid_effect_falls_back():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "GRAYSCALE"}}})
    assert cfg.get_profile().effect == "grayscale"
    assert cfg.to_dict()["profiles"]["P"]["effect"] == "grayscale"

    sepia = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "SEPIA"}}})
    assert sepia.get_profile().effect == "sepia"
    assert sepia.to_dict()["profiles"]["P"]["effect"] == "sepia"

    blur = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "BLUR"}}})
    assert blur.get_profile().effect == "blur"
    assert blur.to_dict()["profiles"]["P"]["effect"] == "blur"

    vignette = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "VIGNETTE"}}})
    assert vignette.get_profile().effect == "vignette"
    assert vignette.to_dict()["profiles"]["P"]["effect"] == "vignette"

    calendar = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "CALENDAR"}}})
    assert calendar.get_profile().effect == "calendar"
    assert calendar.to_dict()["profiles"]["P"]["effect"] == "calendar"

    invert = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "INVERT"}}})
    assert invert.get_profile().effect == "invert"
    assert invert.to_dict()["profiles"]["P"]["effect"] == "invert"

    invalid = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "posterize"}}})
    assert invalid.get_profile().effect == "none"


def test_automatic_bar_color_roundtrips_and_invalid_value_falls_back():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"bar_color": "AUTO"}}})
    assert cfg.get_profile().bar_color == "auto"
    assert cfg.to_dict()["profiles"]["P"]["bar_color"] == "auto"

    invalid = Config.from_dict({"active_profile": "P", "profiles": {"P": {"bar_color": "rainbow"}}})
    assert invalid.get_profile().bar_color == "black"


def test_invalid_mode_falls_back_to_shared():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "crop"}}})
    assert cfg.get_profile().mode == "shared"


def test_bad_profile_types_fall_back_safely():
    cfg = Config.from_dict({
        "active_profile": "P",
        "profiles": {
            "P": {
                "interval_minutes": "not-a-number",
                "shared_folders": "/not/char/split",
                "monitor_folders": {"HDMI-1": "/also/not/char/split"},
            }
        },
    })
    profile = cfg.get_profile()
    assert profile.interval_minutes == 10.0
    assert profile.shared_folders == []
    assert profile.monitor_folders == {}
