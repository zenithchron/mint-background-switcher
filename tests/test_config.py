import json

from mint_background_switcher.config import Config, Profile


def test_config_roundtrip():
    cfg = Config(active_profile="P", profiles={"P": Profile(name="P", mode="per-monitor", shared_folders=["/pics"], monitor_folders={"HDMI-1": ["/a", "/b"]})})
    data = cfg.to_dict()
    loaded = Config.from_dict(json.loads(json.dumps(data)))
    profile = loaded.get_profile()
    assert loaded.active_profile == "P"
    assert profile.mode == "per-monitor"
    assert profile.folders_for_monitor("HDMI-1") == ["/a", "/b"]
    assert profile.folders_for_monitor("missing") == ["/pics"]


def test_same_mode_is_valid():
    cfg = Config.from_dict({"active_profile": "P", "profiles": {"P": {"mode": "same"}}})
    assert cfg.get_profile().mode == "same"


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
