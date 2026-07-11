"""Image scanning, fitting, and wallpaper composition."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

from .monitor import Monitor, normalized_position, virtual_canvas
from .paths import xdg_cache_dir

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def scan_images(folders: Iterable[str], recursive: bool = True) -> list[str]:
    images: list[str] = []
    for raw_folder in folders:
        if not raw_folder:
            continue
        path = Path(raw_folder).expanduser()
        try:
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                images.append(str(path.resolve()))
                continue
            is_dir = path.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        if recursive:
            for root, _dirs, files in os.walk(path, onerror=lambda _err: None):
                for filename in files:
                    item = Path(root) / filename
                    if item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        try:
                            images.append(str(item.resolve()))
                        except OSError:
                            continue
        else:
            try:
                iterator = list(path.iterdir())
            except OSError:
                continue
            for item in iterator:
                try:
                    if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        images.append(str(item.resolve()))
                except OSError:
                    continue
    return sorted(set(images))


def open_image(path: str | Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def fit_with_black_bars(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"Invalid target size: {size}")
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    working = image.copy()
    working.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    x = (target_w - working.width) // 2
    y = (target_h - working.height) // 2
    canvas.paste(working, (x, y))
    return canvas


def apply_effect(image_path: str | Path, effect: str) -> Path:
    """Apply a configured post-processing effect to a composed wallpaper."""
    path = Path(image_path)
    if effect == "none":
        return path
    if effect != "grayscale":
        raise ValueError(f"Unsupported wallpaper effect: {effect}")
    with Image.open(path) as source:
        processed = ImageOps.grayscale(source).convert("RGB")
        processed.save(path, format="PNG")
    return path


def compose_per_monitor(monitors: list[Monitor], image_by_monitor: dict[str, str], output_path: str | Path) -> Path:
    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    width, height, min_x, min_y = virtual_canvas(monitors)
    combined = Image.new("RGB", (width, height), (0, 0, 0))
    for monitor in monitors:
        image_path = image_by_monitor.get(monitor.name)
        if not image_path:
            continue
        panel = fit_with_black_bars(open_image(image_path), (monitor.width, monitor.height))
        combined.paste(panel, normalized_position(monitor, min_x, min_y))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output, format="PNG")
    return output


def compose_span(monitors: list[Monitor], image_path: str, output_path: str | Path) -> Path:
    width, height, _, _ = virtual_canvas(monitors)
    fitted = fit_with_black_bars(open_image(image_path), (width, height))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fitted.save(output, format="PNG")
    return output


def compose_black(monitors: list[Monitor], output_path: str | Path) -> Path:
    width, height, _, _ = virtual_canvas(monitors)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (0, 0, 0)).save(output, format="PNG")
    return output


def ensure_cache_dir() -> Path:
    path = xdg_cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
