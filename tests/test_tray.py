from mint_background_switcher.tray import TRAY_ICON_CANDIDATES, choose_tray_icon


class _Theme:
    def __init__(self, available):
        self.available = set(available)

    def has_icon(self, icon_name):
        return icon_name in self.available


class _Gtk:
    class IconTheme:
        @staticmethod
        def get_default():
            return _Theme({"image-x-generic-symbolic"})


class _NoThemeGtk:
    class IconTheme:
        @staticmethod
        def get_default():
            return None


def test_choose_tray_icon_prefers_symbolic_monochrome_icon():
    assert choose_tray_icon(_Gtk) == "image-x-generic-symbolic"


def test_choose_tray_icon_falls_back_to_eye_symbolic():
    assert choose_tray_icon(_NoThemeGtk) == TRAY_ICON_CANDIDATES[0]
    assert TRAY_ICON_CANDIDATES[0] == "view-preview-symbolic"
