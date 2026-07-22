"""Image scanning, fitting, and wallpaper composition."""

from __future__ import annotations

import calendar
from datetime import date
import os
from pathlib import Path
import tempfile
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .monitor import Monitor, normalized_position, virtual_canvas
from .paths import xdg_cache_dir

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")
CALENDAR_HIGHLIGHT_COLOR = (64, 120, 216, 255)
POSTCARD_BACKGROUND_COLOR = (112, 78, 46)
POSTCARD_PIN_COLOR = (188, 42, 42, 255)
_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAY_LABELS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def _save_png_atomic(image: Image.Image, output_path: str | Path) -> Path:
    """Save a PNG beside its destination, then replace without following symlinks."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=str(output.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file_handle:
            image.save(file_handle, format="PNG")
            file_handle.flush()
            os.fsync(file_handle.fileno())
        # Replacing a symlink replaces the link itself, never the linked target.
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return output


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


def is_usable_image(path: str | Path) -> bool:
    """Return whether Pillow recognizes an image without decoding all pixel data."""

    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return False
    return True


def automatic_bar_color(image: Image.Image) -> tuple[int, int, int]:
    """Return a representative RGB color for an image's letterbox bars."""
    sample = image.convert("RGB")
    sample.thumbnail((64, 64), Image.Resampling.LANCZOS)
    mean = ImageStat.Stat(sample).mean
    return (int(round(mean[0])), int(round(mean[1])), int(round(mean[2])))


def fit_with_black_bars(image: Image.Image, size: tuple[int, int], bar_color: str = "black") -> Image.Image:
    target_w, target_h = size
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"Invalid target size: {size}")
    if bar_color == "auto":
        fill = automatic_bar_color(image)
    elif bar_color == "black":
        fill = (0, 0, 0)
    else:
        raise ValueError(f"Unsupported letterbox bar color: {bar_color}")
    canvas = Image.new("RGB", (target_w, target_h), fill)
    working = image.copy()
    working.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    x = (target_w - working.width) // 2
    y = (target_h - working.height) // 2
    canvas.paste(working, (x, y))
    return canvas


def _calendar_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size=max(8, size))
    except OSError:
        return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width = right - left
    height = bottom - top
    draw.text((center[0] - width / 2 - left, center[1] - height / 2 - top), text, font=font, fill=fill)


def _month_start(day: date, offset: int) -> date:
    month_index = day.year * 12 + day.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def add_three_month_calendar(image: Image.Image, *, today: date | None = None) -> Image.Image:
    """Return an RGB copy with previous/current/next month calendars overlaid."""

    current_day = today or date.today()
    canvas = image.convert("RGB")
    width, height = canvas.size
    if width < 240 or height < 120:
        return canvas

    margin = max(4, min(width, height) // 40)
    panel_width = min(width - 2 * margin, max(240, round(width * 0.82)))
    panel_height = min(height - 2 * margin, max(120, round(height * 0.30)))
    left = (width - panel_width) // 2
    top = height - margin - panel_height
    right = left + panel_width
    bottom = top + panel_height

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    radius = max(4, panel_height // 18)
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(8, 12, 18, 210), outline=(255, 255, 255, 90))

    panel_padding = max(4, panel_height // 18)
    gap = max(3, panel_width // 120)
    card_width = max(1, (panel_width - 2 * panel_padding - 2 * gap) // 3)
    card_top = top + panel_padding
    card_bottom = bottom - panel_padding
    card_height = max(1, card_bottom - card_top)
    title_font = _calendar_font(min(card_height // 9, card_width // 10), bold=True)
    day_font = _calendar_font(min(card_height // 13, card_width // 16))
    current_day_font = _calendar_font(min(card_height // 13, card_width // 16), bold=True)

    for index, month_day in enumerate(_month_start(current_day, offset) for offset in (-1, 0, 1)):
        card_left = left + panel_padding + index * (card_width + gap)
        card_right = card_left + card_width
        is_current_month = month_day.year == current_day.year and month_day.month == current_day.month
        if is_current_month:
            draw.rounded_rectangle(
                (card_left, card_top, card_right, card_bottom),
                radius=max(3, radius // 2),
                fill=(255, 255, 255, 18),
                outline=(255, 255, 255, 110),
            )

        title_height = max(12, card_height // 7)
        _draw_centered_text(
            draw,
            ((card_left + card_right) / 2, card_top + title_height / 2),
            f"{_MONTH_NAMES[month_day.month]} {month_day.year}",
            font=title_font,
            fill=(255, 255, 255, 255),
        )

        grid_top = card_top + title_height
        row_height = max(1.0, (card_bottom - grid_top) / 7)
        column_width = card_width / 7
        for column, label in enumerate(_WEEKDAY_LABELS):
            _draw_centered_text(
                draw,
                (card_left + (column + 0.5) * column_width, grid_top + row_height / 2),
                label,
                font=day_font,
                fill=(190, 203, 220, 255),
            )

        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(month_day.year, month_day.month)
        weeks.extend([[0] * 7 for _ in range(6 - len(weeks))])
        for week_index, week in enumerate(weeks[:6]):
            for column, day_number in enumerate(week):
                if day_number == 0:
                    continue
                cell_center = (
                    card_left + (column + 0.5) * column_width,
                    grid_top + (week_index + 1.5) * row_height,
                )
                is_today = is_current_month and day_number == current_day.day
                if is_today:
                    half_width = max(3, column_width * 0.38)
                    half_height = max(3, row_height * 0.38)
                    draw.rounded_rectangle(
                        (
                            cell_center[0] - half_width,
                            cell_center[1] - half_height,
                            cell_center[0] + half_width,
                            cell_center[1] + half_height,
                        ),
                        radius=max(2, round(min(half_width, half_height) / 2)),
                        fill=CALENDAR_HIGHLIGHT_COLOR,
                    )
                _draw_centered_text(
                    draw,
                    cell_center,
                    str(day_number),
                    font=current_day_font if is_today else day_font,
                    fill=(255, 255, 255, 255),
                )

    return Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")


def apply_effect(image_path: str | Path, effect: str) -> Path:
    """Apply a configured post-processing effect to a composed wallpaper."""
    path = Path(image_path)
    if effect == "none":
        return path
    with Image.open(path) as source:
        if effect == "blur":
            processed = source.convert("RGB").filter(ImageFilter.GaussianBlur(radius=4))
        elif effect == "vignette":
            rgb_source = source.convert("RGB")
            radial_mask = Image.radial_gradient("L").resize(rgb_source.size, Image.Resampling.LANCZOS)
            darkening_mask = radial_mask.point([round(level * 0.55) for level in range(256)])
            processed = Image.composite(Image.new("RGB", rgb_source.size, (0, 0, 0)), rgb_source, darkening_mask)
        elif effect == "calendar":
            processed = add_three_month_calendar(source)
        elif effect == "sepia":
            grayscale = ImageOps.grayscale(source)
            processed = ImageOps.colorize(grayscale, black=(0, 0, 0), white=(255, 240, 192))
        elif effect == "grayscale":
            grayscale = ImageOps.grayscale(source)
            processed = grayscale.convert("RGB")
        else:
            raise ValueError(f"Unsupported wallpaper effect: {effect}")
        _save_png_atomic(processed, path)
    return path


def compose_per_monitor(
    monitors: list[Monitor],
    image_by_monitor: dict[str, str],
    output_path: str | Path,
    *,
    bar_color: str = "black",
) -> Path:
    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    width, height, min_x, min_y = virtual_canvas(monitors)
    combined = Image.new("RGB", (width, height), (0, 0, 0))
    for monitor in monitors:
        image_path = image_by_monitor.get(monitor.name)
        if not image_path:
            continue
        panel = fit_with_black_bars(open_image(image_path), (monitor.width, monitor.height), bar_color)
        combined.paste(panel, normalized_position(monitor, min_x, min_y))
    return _save_png_atomic(combined, output_path)


def compose_montage(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
) -> Path:
    """Compose a 2x2 local-image montage independently on each monitor."""

    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    width, height, min_x, min_y = virtual_canvas(monitors)
    combined = Image.new("RGB", (width, height), (0, 0, 0))
    for monitor in monitors:
        image_paths = images_by_monitor.get(monitor.name, [])
        if not image_paths:
            continue
        panel = Image.new("RGB", (monitor.width, monitor.height), (0, 0, 0))
        split_x = monitor.width // 2
        split_y = monitor.height // 2
        cells = (
            (0, 0, split_x, split_y),
            (split_x, 0, monitor.width, split_y),
            (0, split_y, split_x, monitor.height),
            (split_x, split_y, monitor.width, monitor.height),
        )
        for image_path, (left, top, right, bottom) in zip(image_paths, cells):
            cell_width = right - left
            cell_height = bottom - top
            if cell_width <= 0 or cell_height <= 0:
                continue
            tile = fit_with_black_bars(open_image(image_path), (cell_width, cell_height), bar_color)
            panel.paste(tile, (left, top))
        combined.paste(panel, normalized_position(monitor, min_x, min_y))
    return _save_png_atomic(combined, output_path)


def _postcard_tile(
    image_path: str,
    cell_size: tuple[int, int],
    angle: float,
    *,
    bar_color: str,
) -> Image.Image:
    """Return one uncropped, framed photo sized to remain inside a pile cell."""

    cell_width, cell_height = cell_size
    photo_width = max(1, round(cell_width * 0.68))
    photo_height = max(1, round(cell_height * 0.58))
    border = max(1, min(cell_width, cell_height) // 30)
    fitted = fit_with_black_bars(open_image(image_path), (photo_width, photo_height), bar_color)
    card = Image.new(
        "RGBA",
        (photo_width + 2 * border, photo_height + 4 * border),
        (248, 246, 238, 255),
    )
    card.paste(fitted, (border, border))
    draw = ImageDraw.Draw(card)
    pin_radius = max(1, border // 2)
    pin_x = card.width // 2
    pin_y = max(pin_radius + 1, border // 2)
    draw.ellipse(
        (pin_x - pin_radius, pin_y - pin_radius, pin_x + pin_radius, pin_y + pin_radius),
        fill=POSTCARD_PIN_COLOR,
    )
    rotated = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    rotated.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
    return rotated


def compose_postcard(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
) -> Path:
    """Compose four locally selected photos as a framed postcard pile per monitor."""

    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    width, height, min_x, min_y = virtual_canvas(monitors)
    combined = Image.new("RGB", (width, height), (0, 0, 0))
    angles = (-8.0, 7.0, 5.0, -6.0)
    for monitor in monitors:
        panel = Image.new("RGB", (monitor.width, monitor.height), POSTCARD_BACKGROUND_COLOR)
        split_x = monitor.width // 2
        split_y = monitor.height // 2
        cells = (
            (0, 0, split_x, split_y),
            (split_x, 0, monitor.width, split_y),
            (0, split_y, split_x, monitor.height),
            (split_x, split_y, monitor.width, monitor.height),
        )
        image_paths = images_by_monitor.get(monitor.name, [])
        for image_path, angle, (left, top, right, bottom) in zip(image_paths, angles, cells):
            cell_width = right - left
            cell_height = bottom - top
            if cell_width <= 0 or cell_height <= 0:
                continue
            card = _postcard_tile(image_path, (cell_width, cell_height), angle, bar_color=bar_color)
            x = left + (cell_width - card.width) // 2
            y = top + (cell_height - card.height) // 2
            panel.paste(card, (x, y), card)
        combined.paste(panel, normalized_position(monitor, min_x, min_y))
    return _save_png_atomic(combined, output_path)


def compose_span(
    monitors: list[Monitor],
    image_path: str,
    output_path: str | Path,
    *,
    bar_color: str = "black",
) -> Path:
    width, height, _, _ = virtual_canvas(monitors)
    fitted = fit_with_black_bars(open_image(image_path), (width, height), bar_color)
    return _save_png_atomic(fitted, output_path)


def compose_black(monitors: list[Monitor], output_path: str | Path) -> Path:
    width, height, _, _ = virtual_canvas(monitors)
    return _save_png_atomic(Image.new("RGB", (width, height), (0, 0, 0)), output_path)


def ensure_cache_dir() -> Path:
    path = xdg_cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
