"""Desktop wallpaper application helpers."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path


def file_uri(path: str | Path) -> str:
    return Path(path).expanduser().resolve().as_uri()


def _parse_gsettings_output(value: str) -> object:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _gsettings_arg(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _get_gsettings(schema: str, key: str) -> object | None:
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings is not available")
    try:
        output = subprocess.check_output(
            ["gsettings", "get", schema, key],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    return _parse_gsettings_output(output)


def _set_gsettings(schema: str, key: str, value: str | bool, dry_run: bool, *, skip_if_current: bool = True) -> None:
    if dry_run:
        return
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings is not available")
    if skip_if_current:
        current = _get_gsettings(schema, key)
        if current == value:
            return
    subprocess.run(["gsettings", "set", schema, key, _gsettings_arg(value)], check=True)


def _try_set_gsettings(schema: str, key: str, value: str | bool, dry_run: bool, *, skip_if_current: bool = True) -> None:
    try:
        _set_gsettings(schema, key, value, dry_run, skip_if_current=skip_if_current)
    except subprocess.CalledProcessError:
        pass


def detect_desktop() -> str:
    values = [
        os.environ.get("XDG_CURRENT_DESKTOP", ""),
        os.environ.get("DESKTOP_SESSION", ""),
        os.environ.get("GDMSESSION", ""),
    ]
    joined = " ".join(values).lower()
    if "cinnamon" in joined:
        return "cinnamon"
    if "mate" in joined:
        return "mate"
    if "gnome" in joined or "ubuntu" in joined or "pop" in joined:
        return "gnome"
    if "xfce" in joined or "xubuntu" in joined:
        return "xfce"
    if "kde" in joined or "plasma" in joined:
        return "kde"
    return "unknown"


class DesktopSetter:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def _resolve_desktop(self, desktop: str) -> str:
        return detect_desktop() if desktop == "auto" else desktop.lower()

    def supports_solid_black(self, desktop: str = "auto") -> bool:
        return self._resolve_desktop(desktop) in {"cinnamon", "gnome"}

    def apply(self, image_path: str | Path, desktop: str = "auto") -> list[str]:
        image_path = Path(image_path).expanduser().resolve()
        if self.dry_run:
            if not image_path.exists():
                raise FileNotFoundError(image_path)
            return [f"dry-run:{desktop}"]
        desktop = self._resolve_desktop(desktop)
        if desktop == "cinnamon":
            self._apply_cinnamon(image_path)
            return ["cinnamon"]
        if desktop == "gnome":
            self._apply_gnome(image_path)
            return ["gnome"]
        if desktop == "mate":
            self._apply_mate(image_path)
            return ["mate"]
        if desktop == "xfce":
            self._apply_feh(image_path)
            return ["xfce-feh-fallback"]
        if shutil.which("feh"):
            self._apply_feh(image_path)
            return ["feh"]
        if shutil.which("gsettings"):
            try:
                self._apply_cinnamon(image_path)
                return ["cinnamon-fallback"]
            except subprocess.CalledProcessError:
                self._apply_gnome(image_path)
                return ["gnome-fallback"]
        raise RuntimeError("Could not determine how to set wallpaper on this desktop")

    def apply_black(self, image_path: str | Path | None = None, desktop: str = "auto") -> list[str]:
        """Apply an all-black desktop as directly as the backend allows.

        Cinnamon and GNOME can show a solid black background without loading a new
        image, which avoids their slow image crossfade path. Other desktops fall
        back to applying the prebuilt black composite.
        """
        resolved_desktop = self._resolve_desktop(desktop)
        image = Path(image_path).expanduser().resolve() if image_path is not None else None
        if self.dry_run:
            if image is not None and not image.exists():
                raise FileNotFoundError(image)
            return [f"dry-run-black:{desktop}"]
        if resolved_desktop == "cinnamon":
            self._apply_cinnamon_black()
            return ["cinnamon-black"]
        if resolved_desktop == "gnome":
            self._apply_gnome_black()
            return ["gnome-black"]
        if image is None:
            raise ValueError(f"Black screen image is required for desktop {resolved_desktop!r}")
        if resolved_desktop == "mate":
            self._apply_mate_black(image)
            return ["mate-black"]
        return self.apply(image, resolved_desktop)

    def _apply_cinnamon(self, image_path: Path) -> None:
        schema = "org.cinnamon.desktop.background"
        _set_gsettings(schema, "picture-uri", file_uri(image_path), self.dry_run)
        _set_gsettings(schema, "picture-options", "spanned", self.dry_run)

    def _disable_cinnamon_background_transitions(self) -> None:
        _try_set_gsettings("org.cinnamon.muffin", "background-transition", "none", self.dry_run)
        _try_set_gsettings("org.nemo.desktop", "background-fade", False, self.dry_run)

    def _apply_cinnamon_black(self) -> None:
        schema = "org.cinnamon.desktop.background"
        _set_gsettings(schema, "primary-color", "#000000", self.dry_run)
        _set_gsettings(schema, "secondary-color", "#000000", self.dry_run)
        _set_gsettings(schema, "color-shading-type", "solid", self.dry_run)
        _set_gsettings(schema, "picture-options", "none", self.dry_run)

    def _apply_gnome(self, image_path: Path) -> None:
        schema = "org.gnome.desktop.background"
        uri = file_uri(image_path)
        _set_gsettings(schema, "picture-uri", uri, self.dry_run)
        try:
            _set_gsettings(schema, "picture-uri-dark", uri, self.dry_run)
        except subprocess.CalledProcessError:
            pass
        _set_gsettings(schema, "picture-options", "spanned", self.dry_run)

    def _apply_gnome_black(self) -> None:
        schema = "org.gnome.desktop.background"
        _set_gsettings(schema, "primary-color", "#000000", self.dry_run)
        _set_gsettings(schema, "secondary-color", "#000000", self.dry_run)
        _set_gsettings(schema, "color-shading-type", "solid", self.dry_run)
        _set_gsettings(schema, "picture-options", "none", self.dry_run)

    def _apply_mate(self, image_path: Path) -> None:
        _set_gsettings("org.mate.background", "background-fade", False, self.dry_run)
        _set_gsettings("org.mate.background", "picture-options", "spanned", self.dry_run)
        _set_gsettings("org.mate.background", "picture-filename", str(image_path), self.dry_run)

    def _apply_mate_black(self, image_path: Path) -> None:
        _set_gsettings("org.mate.background", "background-fade", False, self.dry_run)
        _set_gsettings("org.mate.background", "picture-options", "spanned", self.dry_run)
        _set_gsettings("org.mate.background", "picture-filename", str(image_path), self.dry_run)

    def _apply_feh(self, image_path: Path) -> None:
        if self.dry_run:
            return
        subprocess.run(["feh", "--bg-scale", "--no-xinerama", str(image_path)], check=True)
