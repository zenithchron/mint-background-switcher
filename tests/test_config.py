import json

from mint_background_switcher.config import (
    MAX_IGNORE_PATTERN_LENGTH,
    MAX_IGNORE_PATTERNS,
    POSTCARD_BACKGROUND_CHOICES,
    Config,
    Profile,
    load_config,
    replace_working_directory,
    save_config,
)


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


def test_min_image_size_roundtrip_and_coercion():
    assert Profile(name="P").min_image_size == 0

    loaded = Profile.from_dict("P", {"min_image_size": 720})
    assert loaded.min_image_size == 720
    assert loaded.to_dict()["min_image_size"] == 720

    assert Profile.from_dict("P", {}).min_image_size == 0
    assert Profile.from_dict("P", {"min_image_size": "1080"}).min_image_size == 1080
    assert Profile.from_dict("P", {"min_image_size": -80}).min_image_size == 0
    assert Profile.from_dict("P", {"min_image_size": "not-a-number"}).min_image_size == 0
    assert Profile.from_dict("P", {"min_image_size": None}).min_image_size == 0
    assert Profile.from_dict("P", {"min_image_size": 10_000_000}).min_image_size == 100_000


def test_ignore_hidden_roundtrip_and_coercion():
    assert Profile(name="P").ignore_hidden is False

    loaded = Profile.from_dict("P", {"ignore_hidden": True})
    assert loaded.ignore_hidden is True
    assert loaded.to_dict()["ignore_hidden"] is True

    assert Profile.from_dict("P", {}).ignore_hidden is False
    assert Profile.from_dict("P", {"ignore_hidden": "true"}).ignore_hidden is True
    assert Profile.from_dict("P", {"ignore_hidden": "no"}).ignore_hidden is False
    assert Profile.from_dict("P", {"ignore_hidden": "garbage"}).ignore_hidden is False
    assert Profile.from_dict("P", {"ignore_hidden": None}).ignore_hidden is False


def test_match_orientation_roundtrip_and_coercion():
    assert Profile(name="P").match_orientation is False

    loaded = Profile.from_dict("P", {"match_orientation": True})
    assert loaded.match_orientation is True
    assert loaded.to_dict()["match_orientation"] is True

    assert Profile.from_dict("P", {}).match_orientation is False
    assert Profile.from_dict("P", {"match_orientation": "true"}).match_orientation is True
    assert Profile.from_dict("P", {"match_orientation": "no"}).match_orientation is False
    assert Profile.from_dict("P", {"match_orientation": "garbage"}).match_orientation is False
    assert Profile.from_dict("P", {"match_orientation": None}).match_orientation is False


def test_ignore_patterns_roundtrip_and_coercion():
    assert Profile(name="P").ignore_patterns == []

    loaded = Profile.from_dict("P", {"ignore_patterns": ["thumb*.jpg", "banner-*.png"]})
    assert loaded.ignore_patterns == ["thumb*.jpg", "banner-*.png"]
    assert loaded.to_dict()["ignore_patterns"] == ["thumb*.jpg", "banner-*.png"]

    assert Profile.from_dict("P", {}).ignore_patterns == []
    # Non-list values are dropped rather than raised on.
    assert Profile.from_dict("P", {"ignore_patterns": "thumb*"}).ignore_patterns == []
    assert Profile.from_dict("P", {"ignore_patterns": None}).ignore_patterns == []

    # Whitespace is trimmed and duplicates are removed (order-preserving).
    assert Profile.from_dict("P", {"ignore_patterns": [" a ", "a", "b", "b "]}).ignore_patterns == [
        "a",
        "b",
    ]
    # Blank-only entries are dropped.
    assert Profile.from_dict("P", {"ignore_patterns": ["", "   "]}).ignore_patterns == []
    # Oversized pattern lists are capped; over-long patterns are dropped.
    many = [f"p{i}*" for i in range(MAX_IGNORE_PATTERNS + 10)]
    assert len(Profile.from_dict("P", {"ignore_patterns": many}).ignore_patterns) == MAX_IGNORE_PATTERNS
    at_limit = "x" * MAX_IGNORE_PATTERN_LENGTH
    assert Profile.from_dict("P", {"ignore_patterns": [at_limit]}).ignore_patterns == [at_limit]
    assert Profile.from_dict("P", {"ignore_patterns": ["x" * (MAX_IGNORE_PATTERN_LENGTH + 1)]}).ignore_patterns == []


def test_sequential_roundtrip_and_coercion():
    assert Profile(name="P").sequential is False

    loaded = Profile.from_dict("P", {"sequential": True})
    assert loaded.sequential is True
    assert loaded.to_dict()["sequential"] is True

    assert Profile.from_dict("P", {}).sequential is False
    assert Profile.from_dict("P", {"sequential": "true"}).sequential is True
    assert Profile.from_dict("P", {"sequential": "no"}).sequential is False
    assert Profile.from_dict("P", {"sequential": "garbage"}).sequential is False
    assert Profile.from_dict("P", {"sequential": None}).sequential is False


def test_rotate_on_startup_roundtrip_and_coercion():
    assert Profile(name="P").rotate_on_startup is True

    loaded = Profile.from_dict("P", {"rotate_on_startup": False})
    assert loaded.rotate_on_startup is False
    assert loaded.to_dict()["rotate_on_startup"] is False

    assert Profile.from_dict("P", {}).rotate_on_startup is True
    assert Profile.from_dict("P", {"rotate_on_startup": "false"}).rotate_on_startup is False
    assert Profile.from_dict("P", {"rotate_on_startup": "off"}).rotate_on_startup is False
    assert Profile.from_dict("P", {"rotate_on_startup": "garbage"}).rotate_on_startup is True
    assert Profile.from_dict("P", {"rotate_on_startup": None}).rotate_on_startup is True


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
    assert defaults.get_profile().postcard_tilt is True
    assert defaults.get_profile().postcard_background == "dark"

    configured = Config.from_dict(
        {
            "active_profile": "P",
            "profiles": {
                "P": {
                    "mode": "postcard",
                    "postcard_count": "7",
                    "postcard_size": "0.8",
                    "postcard_span": True,
                    "postcard_tilt": False,
                    "postcard_background": "CORKBOARD",
                }
            },
        }
    )
    profile = configured.get_profile()
    assert (
        profile.postcard_count,
        profile.postcard_size,
        profile.postcard_span,
        profile.postcard_tilt,
        profile.postcard_background,
    ) == (
        7,
        0.8,
        True,
        False,
        "corkboard",
    )
    saved = configured.to_dict()["profiles"]["P"]
    assert (
        saved["postcard_count"],
        saved["postcard_size"],
        saved["postcard_span"],
        saved["postcard_tilt"],
        saved["postcard_background"],
    ) == (
        7,
        0.8,
        True,
        False,
        "corkboard",
    )

    malformed_tilt = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_tilt": ["not", "a", "boolean"]}}}
    )
    assert malformed_tilt.get_profile().postcard_tilt is True

    invalid_background = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_background": "not-a-style"}}}
    )
    assert invalid_background.get_profile().postcard_background == "dark"

    high = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_count": 999, "postcard_size": 2}}}
    )
    low = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"postcard_count": 0, "postcard_size": -1}}}
    )
    assert (high.get_profile().postcard_count, high.get_profile().postcard_size) == (100, 1.0)
    assert (low.get_profile().postcard_count, low.get_profile().postcard_size) == (1, 0.0)


def test_all_postcard_background_choices_roundtrip():
    for background in POSTCARD_BACKGROUND_CHOICES:
        configured = Config.from_dict(
            {"active_profile": "P", "profiles": {"P": {"postcard_background": background.upper()}}}
        )
        assert configured.get_profile().postcard_background == background
        assert configured.to_dict()["profiles"]["P"]["postcard_background"] == background


def test_all_postcard_background_choices_roundtrip_through_file(tmp_path):
    profiles = {
        f"Profile {index}": Profile(name=f"Profile {index}", postcard_background=background)
        for index, background in enumerate(POSTCARD_BACKGROUND_CHOICES)
    }
    path = tmp_path / "config.json"
    save_config(Config(active_profile="Profile 0", profiles=profiles), path)

    loaded = load_config(path, create=False)

    assert {
        name: profile.postcard_background
        for name, profile in loaded.profiles.items()
    } == {
        f"Profile {index}": background
        for index, background in enumerate(POSTCARD_BACKGROUND_CHOICES)
    }


def test_postcard_and_polaroid_captions_roundtrip():
    for enabled in (False, True):
        profile = Profile(name="P", postcard_captions=enabled, polaroid_captions=enabled)
        assert profile.to_dict()["postcard_captions"] is enabled
        assert profile.to_dict()["polaroid_captions"] is enabled
        loaded = Profile.from_dict("P", profile.to_dict())
        assert (loaded.postcard_captions, loaded.polaroid_captions) == (enabled, enabled)


def test_caption_flags_default_off_and_coerce_non_booleans():
    profile = Profile(name="P")
    assert profile.postcard_captions is False
    assert profile.polaroid_captions is False
    loaded = Profile.from_dict("P", {"postcard_captions": "yes", "polaroid_captions": 1})
    assert loaded.postcard_captions is True
    assert loaded.polaroid_captions is True
    empty = Profile.from_dict("P", {})
    assert empty.postcard_captions is False
    assert empty.polaroid_captions is False


def test_postcard_background_preserves_legacy_profile_positional_arguments():
    profile = Profile(
        "P",
        5.0,
        "postcard",
        False,
        ["/pictures"],
        {},
        "<Alt>b",
        "x11",
        "sepia",
        "auto",
        7,
        0.8,
        True,
        6,
        0.7,
        True,
        False,
        False,
    )

    assert profile.postcard_count == 7
    assert profile.postcard_size == 0.8
    assert profile.postcard_span is True
    assert profile.polaroid_count == 6
    assert profile.polaroid_size == 0.7
    assert profile.polaroid_span is True
    assert profile.polaroid_tilt is False
    assert profile.postcard_tilt is False
    assert profile.postcard_background == "dark"


def test_polaroid_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "POLAROID"}}})
    assert cfg.get_profile().mode == "polaroid"


def test_polaroid_options_roundtrip_with_backward_compatible_defaults_and_bounds():
    defaults = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "polaroid"}}})
    assert defaults.get_profile().polaroid_count == 4
    assert defaults.get_profile().polaroid_size == 0.5
    assert defaults.get_profile().polaroid_span is False
    assert defaults.get_profile().polaroid_tilt is True

    configured = Config.from_dict(
        {
            "active_profile": "P",
            "profiles": {
                "P": {
                    "mode": "polaroid",
                    "polaroid_count": "7",
                    "polaroid_size": "0.8",
                    "polaroid_span": True,
                    "polaroid_tilt": False,
                }
            },
        }
    )
    assert configured.get_profile().polaroid_count == 7
    assert configured.get_profile().polaroid_size == 0.8
    assert configured.get_profile().polaroid_span is True
    assert configured.get_profile().polaroid_tilt is False
    assert configured.to_dict()["profiles"]["P"]["polaroid_count"] == 7
    assert configured.to_dict()["profiles"]["P"]["polaroid_size"] == 0.8
    assert configured.to_dict()["profiles"]["P"]["polaroid_span"] is True
    assert configured.to_dict()["profiles"]["P"]["polaroid_tilt"] is False

    malformed_tilt = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"polaroid_tilt": ["not", "a", "boolean"]}}}
    )
    assert malformed_tilt.get_profile().polaroid_tilt is True

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

    contrast = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "CONTRAST"}}}
    )
    assert contrast.get_profile().effect == "contrast"
    assert contrast.to_dict()["profiles"]["P"]["effect"] == "contrast"

    brighten = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "BRIGHTEN"}}}
    )
    assert brighten.get_profile().effect == "brighten"
    assert brighten.to_dict()["profiles"]["P"]["effect"] == "brighten"

    darken = Config.from_dict(
        {"active_profile": "P", "profiles": {"P": {"effect": "DARKEN"}}}
    )
    assert darken.get_profile().effect == "darken"
    assert darken.to_dict()["profiles"]["P"]["effect"] == "darken"

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


def test_letterbox_bar_styles_roundtrip_and_invalid_value_falls_back():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"bar_color": "AUTO"}}})
    assert cfg.get_profile().bar_color == "auto"
    assert cfg.to_dict()["profiles"]["P"]["bar_color"] == "auto"

    blurred = Config.from_dict({"active_profile": "P", "profiles": {"P": {"bar_color": "BLURRED"}}})
    assert blurred.get_profile().bar_color == "blurred"
    assert blurred.to_dict()["profiles"]["P"]["bar_color"] == "blurred"

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
