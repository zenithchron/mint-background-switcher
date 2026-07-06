from mint_background_switcher import settings_ui


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Text:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def insert(self, _index, text):
        self.value += text

    def delete(self, *_args):
        self.value = ""


class _Combo:
    def configure(self, **_kwargs):
        pass


def test_save_current_returns_false_on_validation_failure(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda *_args: None)
    monkeypatch.setattr(settings_ui, "save_config", lambda _cfg: (_ for _ in ()).throw(AssertionError("should not save")))

    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "profile_var", _Var("P"))
    setattr(dummy, "interval_var", _Var("not-a-number"))
    setattr(dummy, "mode_var", _Var("shared"))
    setattr(dummy, "recursive_var", _Var(True))
    setattr(dummy, "hotkey_var", _Var("<Primary><Alt>b"))
    setattr(dummy, "desktop_var", _Var("auto"))
    setattr(dummy, "shared_text", _Text("/tmp/images"))
    setattr(dummy, "monitor_text", _Text(""))
    setattr(dummy, "config_data", settings_ui.Config(active_profile="P", profiles={}))
    setattr(dummy, "profile_combo", _Combo())

    assert settings_ui.SettingsApp._save_current(dummy, show_success=False) is False
    assert errors and errors[0][0] == "Save failed"


def test_apply_next_aborts_when_save_fails(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "profile_var", _Var("P"))
    setattr(dummy, "_save_current", lambda **_kwargs: False)
    monkeypatch.setattr(settings_ui, "switch_once", fail_if_called)

    settings_ui.SettingsApp._apply_next(dummy)

    assert called is False


def test_shared_hard_drive_browse_adds_unique_folder():
    calls = []

    def fake_ask_folder(**kwargs):
        calls.append(kwargs)
        return "/media/example/Photos"

    dummy = object.__new__(settings_ui.SettingsApp)
    shared_text = _Text("/tmp/example/Pictures")
    setattr(dummy, "shared_text", shared_text)
    setattr(dummy, "_ask_folder", fake_ask_folder)

    settings_ui.SettingsApp._add_shared_folder_from_root(dummy)
    settings_ui.SettingsApp._add_shared_folder_from_root(dummy)

    assert calls[0]["initialdir"] == "/"
    assert calls[0]["title"]
    assert shared_text.value.splitlines() == ["/tmp/example/Pictures", "/media/example/Photos"]


def test_monitor_folder_flow_browses_then_asks_for_screen():
    events = []
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("DP-1=/old/dp\nHDMI-1=/old/hdmi")
    setattr(dummy, "monitor_folder_var", _Var("DP-1"))
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "_ask_folder", lambda **_kwargs: events.append("folder") or "/mnt/wallpapers")
    setattr(dummy, "_choose_monitor_for_folder", lambda folder: events.append(("screen", folder)) or "HDMI-1")

    settings_ui.SettingsApp._add_monitor_folder_from_root(dummy)

    lines = monitor_text.value.splitlines()
    assert events == ["folder", ("screen", "/mnt/wallpapers")]
    assert "DP-1=/old/dp" in lines
    assert "HDMI-1=/old/hdmi;/mnt/wallpapers" in lines
    assert dummy.monitor_folder_var.get() == "HDMI-1"


def test_monitor_hard_drive_browse_shows_error_for_malformed_text(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("not-a-valid-monitor-line")
    setattr(dummy, "monitor_folder_var", _Var("HDMI-1"))
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "_ask_folder", lambda **_kwargs: "/mnt/wallpapers")
    setattr(dummy, "_choose_monitor_for_folder", lambda folder: "HDMI-1")

    settings_ui.SettingsApp._add_monitor_folder_from_root(dummy)

    assert errors and errors[0][0] == "Could not add folder"
    assert monitor_text.value == "not-a-valid-monitor-line"


def test_remove_monitor_folder_removes_only_selected_assignment():
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {"DP-1": ["/a", "/b"], "HDMI-1": ["/c"]})

    settings_ui.SettingsApp._remove_monitor_folder(dummy, "DP-1", "/a")

    assert dummy.monitor_folders_data == {"DP-1": ["/b"], "HDMI-1": ["/c"]}
    assert monitor_text.value.splitlines() == ["DP-1=/b", "HDMI-1=/c"]


def test_remove_monitor_folder_dialog_can_delete_last_assignment():
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {"DP-1": ["/a"], "HDMI-1": ["/c"]})
    setattr(dummy, "_choose_monitor_folder_to_remove", lambda: ("DP-1", "/a"))

    settings_ui.SettingsApp._remove_monitor_folder_from_dialog(dummy)

    assert dummy.monitor_folders_data == {"HDMI-1": ["/c"]}
    assert monitor_text.value.splitlines() == ["HDMI-1=/c"]


def test_remove_monitor_folder_dialog_shows_message_when_empty(monkeypatch):
    messages = []
    monkeypatch.setattr(settings_ui.messagebox, "showinfo", lambda title, message: messages.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    monitor_text = _Text("")
    setattr(dummy, "monitor_text", monitor_text)
    setattr(dummy, "monitor_folders_data", {})

    assert settings_ui.SettingsApp._choose_monitor_folder_to_remove(dummy) is None
    assert messages and messages[0][0] == "No per-monitor folders"


def test_new_profile_prompts_for_name_and_saves(monkeypatch):
    saved = []
    loaded = []
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Default", profiles={"Default": settings_ui.Profile(name="Default")}))
    setattr(dummy, "profile_var", _Var("Default"))
    setattr(dummy, "profile_combo", _Combo())
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: "Travel")
    setattr(dummy, "_load_profile", lambda name: loaded.append(name))

    settings_ui.SettingsApp._new_profile(dummy)

    assert "Travel" in dummy.config_data.profiles
    assert dummy.config_data.active_profile == "Travel"
    assert dummy.profile_var.get() == "Travel"
    assert saved == ["Travel"]
    assert loaded == ["Travel"]


def test_rename_profile_preserves_current_form_settings_and_saves(monkeypatch):
    saved = []
    loaded = []
    errors = []
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    old_profile = settings_ui.Profile(
        name="Old",
        mode="shared",
        shared_folders=["/old-shared"],
        monitor_folders={"DP-1": ["/old"]},
        desktop="cinnamon",
    )
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Old", profiles={"Old": old_profile}))
    setattr(dummy, "profile_var", _Var("Old"))
    setattr(dummy, "profile_combo", _Combo())
    setattr(dummy, "interval_var", _Var("15"))
    setattr(dummy, "mode_var", _Var("per-monitor"))
    setattr(dummy, "recursive_var", _Var(False))
    setattr(dummy, "hotkey_var", _Var("<Primary><Alt>x"))
    setattr(dummy, "desktop_var", _Var("mate"))
    setattr(dummy, "shared_text", _Text("/new-shared\n"))
    setattr(dummy, "monitor_text", _Text(""))
    setattr(dummy, "monitor_folders_data", {"HDMI-1": ["/new-monitor"]})
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: "Travel")
    setattr(dummy, "_load_profile", lambda name: loaded.append(name))

    settings_ui.SettingsApp._rename_profile(dummy)

    assert errors == []
    assert "Old" not in dummy.config_data.profiles
    renamed = dummy.config_data.profiles["Travel"]
    assert renamed.name == "Travel"
    assert renamed.interval_minutes == 15.0
    assert renamed.mode == "per-monitor"
    assert renamed.recursive is False
    assert renamed.shared_folders == ["/new-shared"]
    assert renamed.monitor_folders == {"HDMI-1": ["/new-monitor"]}
    assert renamed.black_hotkey == "<Primary><Alt>x"
    assert renamed.desktop == "mate"
    assert dummy.profile_var.get() == "Travel"
    assert saved == ["Travel"]
    assert loaded == ["Travel"]


def test_rename_profile_cancel_has_no_save_side_effect(monkeypatch):
    saved = []
    dummy = object.__new__(settings_ui.SettingsApp)
    old_profile = settings_ui.Profile(name="Old", shared_folders=["/old"])
    setattr(dummy, "config_data", settings_ui.Config(active_profile="Old", profiles={"Old": old_profile}))
    setattr(dummy, "profile_var", _Var("Old"))
    setattr(dummy, "_ask_profile_name", lambda *_args, **_kwargs: None)
    setattr(dummy, "_save_current", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cancel should not save")))
    monkeypatch.setattr(settings_ui, "save_config", lambda cfg: saved.append(cfg.active_profile))

    settings_ui.SettingsApp._rename_profile(dummy)

    assert saved == []
    assert dummy.config_data.active_profile == "Old"
    assert dummy.config_data.profiles == {"Old": old_profile}


def test_blank_or_duplicate_profile_name_is_rejected(monkeypatch):
    errors = []
    monkeypatch.setattr(settings_ui.messagebox, "showerror", lambda title, message: errors.append((title, message)))
    dummy = object.__new__(settings_ui.SettingsApp)
    setattr(dummy, "config_data", settings_ui.Config(active_profile="A", profiles={"A": settings_ui.Profile(name="A")}))

    assert settings_ui.SettingsApp._validated_profile_name(dummy, "  ") is None
    assert settings_ui.SettingsApp._validated_profile_name(dummy, "A") is None
    assert [title for title, _message in errors] == ["Invalid profile name", "Profile exists"]
