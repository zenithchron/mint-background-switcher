"""Image scanning, fitting, and wallpaper composition."""

from __future__ import annotations

import calendar
from datetime import date
import os
from pathlib import Path
import random
import tempfile
from typing import Iterable
import warnings

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

from .config import RANDOM_EFFECT_CHOICES
from .monitor import Monitor, normalized_position, virtual_canvas
from .paths import xdg_cache_dir

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")
CALENDAR_HIGHLIGHT_COLOR = (64, 120, 216, 255)
POLAROID_BACKGROUND_COLOR = (39, 44, 52)
POLAROID_FRAME_COLOR = (248, 246, 238, 255)
POSTCARD_BACKGROUND_COLOR = POLAROID_BACKGROUND_COLOR
SATURATION_FACTOR = 1.5
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


class ImageDecodeError(OSError):
    """A selected source stopped being safely decodable before composition."""

    def __init__(self, image_path: str | Path) -> None:
        self.image_path = str(image_path)
        super().__init__("A selected source image could not be decoded")


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


def apply_effect(
    image_path: str | Path,
    effect: str,
    *,
    rng: random.Random | None = None,
) -> Path:
    """Apply a configured post-processing effect to a composed wallpaper."""
    path = Path(image_path)
    if effect == "random":
        effect = rng.choice(RANDOM_EFFECT_CHOICES) if rng is not None else random.choice(RANDOM_EFFECT_CHOICES)
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
        elif effect == "invert":
            processed = ImageOps.invert(source.convert("RGB"))
        elif effect == "sepia":
            grayscale = ImageOps.grayscale(source)
            processed = ImageOps.colorize(grayscale, black=(0, 0, 0), white=(255, 240, 192))
        elif effect == "desaturate":
            rgb_source = source.convert("RGB")
            grayscale = ImageOps.grayscale(rgb_source).convert("RGB")
            processed = Image.blend(rgb_source, grayscale, 0.5)
        elif effect == "saturate":
            processed = ImageEnhance.Color(source.convert("RGB")).enhance(SATURATION_FACTOR)
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


def _collage_tile(
    image_path: str,
    size: tuple[int, int],
    *,
    bar_color: str,
) -> Image.Image:
    """Fit one complete source image into an asymmetric collage cell."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = open_image(image_path)
    except (
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageDecodeError(image_path) from exc
    return fit_with_black_bars(source, size, bar_color)


def compose_collage(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
) -> Path:
    """Compose five uncropped local photos as an asymmetric mosaic per monitor."""

    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    width, height, min_x, min_y = virtual_canvas(monitors)
    combined = Image.new("RGB", (width, height), (0, 0, 0))
    for monitor in monitors:
        panel = Image.new("RGB", (monitor.width, monitor.height), (0, 0, 0))
        main_x = round(monitor.width * 0.60)
        left_y = round(monitor.height * 0.62)
        right_y = round(monitor.height * 0.42)
        lower_left_x = main_x // 2
        cells = (
            (0, 0, main_x, left_y),
            (0, left_y, lower_left_x, monitor.height),
            (lower_left_x, left_y, main_x, monitor.height),
            (main_x, 0, monitor.width, right_y),
            (main_x, right_y, monitor.width, monitor.height),
        )
        image_paths = images_by_monitor.get(monitor.name, [])
        for image_path, (left, top, right, bottom) in zip(image_paths, cells):
            cell_width = right - left
            cell_height = bottom - top
            if cell_width <= 0 or cell_height <= 0:
                continue
            tile = _collage_tile(
                image_path,
                (cell_width, cell_height),
                bar_color=bar_color,
            )
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
    """Return one bare, uncropped native-aspect photo with no frame or pin."""

    del bar_color  # Retained for API compatibility; bare photos never insert letterbox bars.
    cell_width, cell_height = cell_size
    try:
        source = open_image(image_path)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageDecodeError(image_path) from exc
    scale = min(cell_width / source.width, cell_height / source.height)
    photo_width = max(1, round(source.width * scale))
    photo_height = max(1, round(source.height * scale))
    photo = source.resize((photo_width, photo_height), Image.Resampling.LANCZOS).convert("RGBA")
    rotated = photo.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    rotated.thumbnail((max(1, cell_width), max(1, cell_height)), Image.Resampling.LANCZOS)
    return rotated


def compose_postcard(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    rng: random.Random | None = None,
) -> Path:
    """Compose random bare photos using the same layout behavior as Polaroid."""

    return _compose_scattered_photos(
        monitors,
        images_by_monitor,
        output_path,
        framed=False,
        bar_color=bar_color,
        size=size,
        span=span,
        rng=rng,
    )


def _polaroid_tile(
    image_path: str,
    cell_size: tuple[int, int],
    angle: float,
    *,
    bar_color: str,
) -> Image.Image:
    """Return one uncropped native-aspect photo in a snug bottom-heavy frame."""

    del bar_color  # Retained for API compatibility; Polaroid photos no longer use letterbox bars.
    cell_width, cell_height = cell_size
    border = max(1, min(cell_width, cell_height) // 30)
    bottom_border = max(border * 4, round(cell_height * 0.12))
    photo_max_width = max(1, cell_width - 2 * border)
    photo_max_height = max(1, cell_height - border - bottom_border)
    try:
        source = open_image(image_path)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageDecodeError(image_path) from exc
    scale = min(photo_max_width / source.width, photo_max_height / source.height)
    photo_width = max(1, round(source.width * scale))
    photo_height = max(1, round(source.height * scale))
    fitted = source.resize((photo_width, photo_height), Image.Resampling.LANCZOS)
    card = Image.new(
        "RGBA",
        (photo_width + 2 * border, photo_height + border + bottom_border),
        POLAROID_FRAME_COLOR,
    )
    card.paste(fitted, (border, border))
    rotated = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    rotated.thumbnail((max(1, cell_width), max(1, cell_height)), Image.Resampling.LANCZOS)
    return rotated


def _random_card_position(
    panel_size: tuple[int, int],
    card_size: tuple[int, int],
    rng: random.Random,
) -> tuple[int, int]:
    """Choose a random position that keeps the entire card inside its monitor."""

    max_x = max(0, panel_size[0] - card_size[0])
    max_y = max(0, panel_size[1] - card_size[1])
    return rng.randint(0, max_x), rng.randint(0, max_y)


def _random_spanning_card_position(
    canvas_size: tuple[int, int],
    card_size: tuple[int, int],
    rng: random.Random,
    *,
    anchor_rect: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    """Keep the card center on a screen while allowing its edges to be clipped."""

    if anchor_rect is None:
        left, top, width, height = 0, 0, canvas_size[0], canvas_size[1]
    else:
        left, top, width, height = anchor_rect
    center_x = rng.randint(left, left + max(0, width - 1))
    center_y = rng.randint(top, top + max(0, height - 1))
    return center_x - card_size[0] // 2, center_y - card_size[1] // 2


def _compose_scattered_photos(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    framed: bool,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    rng: random.Random | None = None,
) -> Path:
    """Compose random framed or bare photos per monitor or across the virtual desktop."""

    if not monitors:
        raise ValueError("Cannot compose wallpaper without monitors")
    rng = rng or random.SystemRandom()
    size = max(0.0, min(1.0, float(size)))
    size_fraction = 0.20 + size * 0.35
    tile_factory = _polaroid_tile if framed else _postcard_tile
    width, height, min_x, min_y = virtual_canvas(monitors)
    if span:
        combined = Image.new("RGB", (width, height), POLAROID_BACKGROUND_COLOR)
        max_card_size = (
            max(1, round(max(monitor.width for monitor in monitors) * size_fraction)),
            max(1, round(max(monitor.height for monitor in monitors) * size_fraction)),
        )
        image_paths = [
            image_path
            for monitor in monitors
            for image_path in images_by_monitor.get(monitor.name, [])
        ]
        card_specs = [(image_path, rng.uniform(-10.0, 10.0)) for image_path in image_paths]
        rng.shuffle(card_specs)
        anchors = list(monitors)
        rng.shuffle(anchors)
        for index, (image_path, angle) in enumerate(card_specs):
            if index and index % len(anchors) == 0:
                rng.shuffle(anchors)
            card = tile_factory(image_path, max_card_size, angle, bar_color=bar_color)
            anchor = anchors[index % len(anchors)]
            anchor_x, anchor_y = normalized_position(anchor, min_x, min_y)
            x, y = _random_spanning_card_position(
                (width, height),
                card.size,
                rng,
                anchor_rect=(anchor_x, anchor_y, anchor.width, anchor.height),
            )
            combined.paste(card, (x, y), card)
        return _save_png_atomic(combined, output_path)

    combined = Image.new("RGB", (width, height), (0, 0, 0))
    for monitor in monitors:
        panel = Image.new("RGB", (monitor.width, monitor.height), POLAROID_BACKGROUND_COLOR)
        max_card_size = (
            max(1, round(monitor.width * size_fraction)),
            max(1, round(monitor.height * size_fraction)),
        )
        card_specs = [
            (image_path, rng.uniform(-10.0, 10.0))
            for image_path in images_by_monitor.get(monitor.name, [])
        ]
        rng.shuffle(card_specs)
        for image_path, angle in card_specs:
            card = tile_factory(
                image_path,
                max_card_size,
                angle,
                bar_color=bar_color,
            )
            x, y = _random_card_position((monitor.width, monitor.height), card.size, rng)
            panel.paste(card, (x, y), card)
        combined.paste(panel, normalized_position(monitor, min_x, min_y))
    return _save_png_atomic(combined, output_path)


def compose_polaroid(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    rng: random.Random | None = None,
) -> Path:
    """Compose random framed Polaroid prints per monitor or across the virtual desktop."""

    return _compose_scattered_photos(
        monitors,
        images_by_monitor,
        output_path,
        framed=True,
        bar_color=bar_color,
        size=size,
        span=span,
        rng=rng,
    )


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
