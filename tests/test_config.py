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


def test_collage_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "COLLAGE"}}})
    assert cfg.get_profile().mode == "collage"


def test_postcard_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "POSTCARD"}}})
    assert cfg.get_profile().mode == "postcard"


def test_postcard_options_roundtrip_with_backward_compatible_defaults_and_bounds():
    defaults = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "postcard"}}})
    assert defaults.get_profile().postcard_count == 4
    assert defaults.get_profile().postcard_size == 0.5
    assert defaults.get_profile().postcard_span is False

    configured = Config.from_dict(
        {
            "active_profile": "P",
            "profiles": {
                "P": {
                    "mode": "postcard",
                    "postcard_count": "7",
                    "postcard_size": "0.8",
                    "postcard_span": True,
                }
            },
        }
    )
    profile = configured.get_profile()
    assert (profile.postcard_count, profile.postcard_size, profile.postcard_span) == (7, 0.8, True)
    saved = configured.to_dict()["profiles"]["P"]
    assert (saved["postcard_count"], saved["postcard_size"], saved["postcard_span"]) == (7, 0.8, True)

    high = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_count": 999, "postcard_size": 2}}}
    )
    low = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_count": 0, "postcard_size": -1}}}
    )
    assert (high.get_profile().postcard_count, high.get_profile().postcard_size) == (100, 1.0)
    assert (low.get_profile().postcard_count, low.get_profile().postcard_size) == (1, 0.0)


def test_polaroid_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "POLAROID"}}})
    assert cfg.get_profile().mode == "polaroid"


def test_polaroid_options_roundtrip_with_backward_compatible_defaults_and_bounds():
    defaults = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "polaroid"}}})
    assert defaults.get_profile().polaroid_count == 4
    assert defaults.get_profile().polaroid_size == 0.5
    assert defaults.get_profile().polaroid_span is False

    configured = Config.from_dict(
        {
            "active_profile": "P",
            "profiles": {
                "P": {
                    "mode": "polaroid",
                    "polaroid_count": "7",
                    "polaroid_size": "0.8",
                    "polaroid_span": True,
                }
            },
        }
    )
    assert configured.get_profile().polaroid_count == 7
    assert configured.get_profile().polaroid_size == 0.8
    assert configured.get_profile().polaroid_span is True
    assert configured.to_dict()["profiles"]["P"]["polaroid_count"] == 7
    assert configured.to_dict()["profiles"]["P"]["polaroid_size"] == 0.8
    assert configured.to_dict()["profiles"]["P"]["polaroid_span"] is True

    high = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"polaroid_count": 999, "polaroid_size": 2}}}
    )
    low = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"polaroid_count": 0, "polaroid_size": -1}}}
    )
    assert (high.get_profile().polaroid_count, high.get_profile().polaroid_size) == (100, 1.0)
    assert (low.get_profile().polaroid_count, low.get_profile().polaroid_size) == (1, 0.0)


def test_effects_roundtrip_and_invalid_effect_falls_back():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "GRAYSCALE"}}})
    assert cfg.get_profile().effect == "grayscale"
    assert cfg.to_dict()["profiles"]["P"]["effect"] == "grayscale"

    sepia = Config.from_dict({"active_profile": "P", "profiles": {"P": {"effect": "SEPIA"}}})
    assert sepia.get_profile().effect == "sepia"
    assert sepia.to_dict()["profiles"]["P"]["effect"] == "sepia"

    desaturate = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "DESATURATE"}}}
    )
    assert desaturate.get_profile().effect == "desaturate"
    assert desaturate.to_dict()["profiles"]["P"]["effect"] == "desaturate"

    saturate = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "SATURATE"}}}
    )
    assert saturate.get_profile().effect == "saturate"
    assert saturate.to_dict()["profiles"]["P"]["effect"] == "saturate"

    random_effect = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "RANDOM"}}}
    )
    assert random_effect.get_profile().effect == "random"
    assert random_effect.to_dict()["profiles"]["P"]["effect"] == "random"

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
