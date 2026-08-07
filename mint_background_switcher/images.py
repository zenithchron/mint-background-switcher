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
POSTCARD_CORKBOARD_COLOR = (174, 126, 78)
POSTCARD_BACKGROUND_COLORS = {
    "dark": POSTCARD_BACKGROUND_COLOR,
    "corkboard": POSTCARD_CORKBOARD_COLOR,
    "felt": (61, 85, 70),
    "linen": (194, 181, 155),
    "kraft paper": (177, 139, 88),
    "watercolor paper": (225, 218, 201),
    "slate": (51, 58, 57),
    "plaster": (205, 199, 187),
    "concrete": (132, 137, 136),
    "brushed metal": (151, 157, 160),
    "sandstone": (187, 154, 107),
    "terrazzo": (203, 197, 185),
}
_PROCEDURAL_SURFACE_STYLES = frozenset(POSTCARD_BACKGROUND_COLORS) - {"dark", "corkboard"}
_SURFACE_STYLE_SEEDS = {
    "felt": 0xA0761D6478BD642F,
    "linen": 0xE7037ED1A0B428DB,
    "kraft paper": 0x8EBC6AF09C88C6E3,
    "watercolor paper": 0x589965CC75374CC3,
    "slate": 0x1D8E4E27C47D124F,
    "plaster": 0xEB44ACCAB455D165,
    "concrete": 0x9E3779B97F4A7C15,
    "brushed metal": 0xD1B54A32D192ED03,
    "sandstone": 0xABC98388FB8FAC03,
    "terrazzo": 0x8CB92BA72F3D8DD7,
}
_SURFACE_NOISE_RECIPES = {
    # fine contrast/blend, coarse contrast/blend, coarse-cell divisor
    "felt": (12, 0.38, 16, 0.16, 34),
    "linen": (9, 0.30, 13, 0.13, 30),
    "kraft paper": (15, 0.38, 22, 0.18, 27),
    "watercolor paper": (12, 0.32, 18, 0.15, 25),
    "slate": (11, 0.32, 22, 0.22, 22),
    "plaster": (10, 0.26, 21, 0.20, 21),
    "concrete": (14, 0.34, 25, 0.22, 23),
    "brushed metal": (8, 0.24, 12, 0.12, 32),
    "sandstone": (13, 0.32, 22, 0.20, 25),
    "terrazzo": (8, 0.22, 14, 0.13, 28),
}
_PROCEDURAL_SURFACE_MAX_WORK_PIXELS = 6_500_000
_CORKBOARD_SEED_MASK = (1 << 64) - 1
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
    if bar_color == "blurred":
        blur_radius = max(4.0, min(target_w, target_h) * 0.025)
        canvas = ImageOps.fit(
            image.convert("RGB"),
            (target_w, target_h),
            method=Image.Resampling.LANCZOS,
        ).filter(ImageFilter.GaussianBlur(radius=blur_radius))
    elif bar_color == "auto":
        fill = automatic_bar_color(image)
        canvas = Image.new("RGB", (target_w, target_h), fill)
    elif bar_color == "black":
        fill = (0, 0, 0)
        canvas = Image.new("RGB", (target_w, target_h), fill)
    else:
        raise ValueError(f"Unsupported letterbox bar style: {bar_color}")
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


def _corkboard_texture(size: tuple[int, int], *, seed: int = 0) -> Image.Image:
    """Generate a deterministic, subtle cork surface without an image asset."""

    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid corkboard size: {size}")

    mixed_seed = (
        seed
        ^ (width * 0x9E3779B185EBCA87)
        ^ (height * 0xC2B2AE3D27D4EB4F)
    ) & _CORKBOARD_SEED_MASK
    texture_rng = random.Random(mixed_seed)

    # Work below full resolution on high-DPI canvases. This keeps temporary
    # layers bounded while the final upscale gives the grain an appropriate
    # physical size on 4K displays.
    output_scale = max(1, min(3, round(min(width, height) / 1080)))
    work_size = (
        max(1, (width + output_scale - 1) // output_scale),
        max(1, (height + output_scale - 1) // output_scale),
    )
    work_width, work_height = work_size
    surface = Image.new("RGB", work_size, POSTCARD_CORKBOARD_COLOR)

    fine_size = (
        max(1, (work_width + 1) // 2),
        max(1, (work_height + 1) // 2),
    )
    fine_source = Image.frombytes(
        "L",
        fine_size,
        texture_rng.randbytes(fine_size[0] * fine_size[1]),
    )
    fine_noise = fine_source.resize(work_size, Image.Resampling.BILINEAR)
    fine_source.close()
    fine_layer = ImageOps.colorize(
        fine_noise,
        black=tuple(max(0, channel - 18) for channel in POSTCARD_CORKBOARD_COLOR),
        white=tuple(min(255, channel + 18) for channel in POSTCARD_CORKBOARD_COLOR),
    )
    blended = Image.blend(surface, fine_layer, 0.45)
    surface.close()
    fine_noise.close()
    fine_layer.close()
    surface = blended

    coarse_step = max(18, min(work_width, work_height) // 28)
    coarse_size = (
        max(2, (work_width + coarse_step - 1) // coarse_step),
        max(2, (work_height + coarse_step - 1) // coarse_step),
    )
    coarse_source = Image.frombytes(
        "L",
        coarse_size,
        texture_rng.randbytes(coarse_size[0] * coarse_size[1]),
    )
    coarse_noise = coarse_source.resize(work_size, Image.Resampling.BICUBIC)
    coarse_source.close()
    coarse_layer = ImageOps.colorize(
        coarse_noise,
        black=tuple(max(0, channel - 24) for channel in POSTCARD_CORKBOARD_COLOR),
        white=tuple(min(255, channel + 24) for channel in POSTCARD_CORKBOARD_COLOR),
    )
    blended = Image.blend(surface, coarse_layer, 0.18)
    surface.close()
    coarse_noise.close()
    coarse_layer.close()
    surface = blended

    draw = ImageDraw.Draw(surface)
    mark_count = max(16, (work_width * work_height) // 3000)
    for _index in range(mark_count):
        x = texture_rng.randrange(work_width)
        y = texture_rng.randrange(work_height)
        if texture_rng.random() < 0.72:
            shade = texture_rng.randint(28, 48)
            color = tuple(max(0, channel - shade) for channel in POSTCARD_CORKBOARD_COLOR)
            pore_width = texture_rng.randint(1, 4)
            pore_height = texture_rng.randint(1, 2)
            draw.ellipse((x, y, x + pore_width, y + pore_height), fill=color)
        else:
            shade = texture_rng.choice((-26, 20))
            color = tuple(
                max(0, min(255, channel + shade)) for channel in POSTCARD_CORKBOARD_COLOR
            )
            fiber_length = texture_rng.randint(3, 9)
            fiber_rise = texture_rng.randint(-2, 2)
            draw.line((x, y, x + fiber_length, y + fiber_rise), fill=color)

    if work_size == size:
        return surface
    textured = surface.resize(size, Image.Resampling.BILINEAR)
    surface.close()
    return textured


def _shift_rgb(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Shift an RGB color without wrapping channel values."""

    red, green, blue = color
    return (
        max(0, min(255, red + amount)),
        max(0, min(255, green + amount)),
        max(0, min(255, blue + amount)),
    )


def _blend_seeded_noise(
    surface: Image.Image,
    *,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
    source_size: tuple[int, int],
    contrast: int,
    opacity: float,
    resample: Image.Resampling,
) -> Image.Image:
    """Blend one private-RNG noise layer, taking ownership of ``surface``."""

    noise_source = Image.frombytes(
        "L",
        source_size,
        texture_rng.randbytes(source_size[0] * source_size[1]),
    )
    noise = noise_source.resize(surface.size, resample)
    noise_source.close()
    layer = ImageOps.colorize(
        noise,
        black=_shift_rgb(base_color, -contrast),
        white=_shift_rgb(base_color, contrast),
    )
    blended = Image.blend(surface, layer, opacity)
    surface.close()
    noise.close()
    layer.close()
    return blended


def _draw_felt_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    for _index in range(max(24, width * height // 1800)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        length = texture_rng.randint(1, 4)
        rise = texture_rng.randint(-1, 1)
        shade = texture_rng.choice((-9, -6, 6, 9))
        draw.line((x, y, x + length, y + rise), fill=_shift_rgb(base_color, shade))


def _draw_linen_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    x = texture_rng.randint(1, 4)
    while x < width:
        shade = texture_rng.choice((-7, -5, 5, 7))
        draw.line((x, 0, x + texture_rng.randint(-1, 1), height), fill=_shift_rgb(base_color, shade))
        x += texture_rng.randint(3, 6)
    y = texture_rng.randint(1, 4)
    while y < height:
        shade = texture_rng.choice((-6, -4, 4, 6))
        draw.line((0, y, width, y + texture_rng.randint(-1, 1)), fill=_shift_rgb(base_color, shade))
        y += texture_rng.randint(3, 6)


def _draw_kraft_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    for _index in range(max(24, width * height // 2400)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        if texture_rng.random() < 0.76:
            length = texture_rng.randint(5, 18)
            rise = texture_rng.randint(-3, 3)
            shade = texture_rng.choice((-18, -12, 13, 19))
            draw.line((x, y, x + length, y + rise), fill=_shift_rgb(base_color, shade))
        else:
            radius = texture_rng.randint(1, 2)
            draw.ellipse(
                (x, y, x + radius, y + radius),
                fill=_shift_rgb(base_color, -texture_rng.randint(20, 34)),
            )


def _draw_watercolor_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    for _index in range(max(20, width * height // 3200)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        length = texture_rng.randint(2, 8)
        rise = texture_rng.randint(-2, 2)
        shade = texture_rng.randint(5, 10)
        draw.line((x, y, x + length, y + rise), fill=_shift_rgb(base_color, -shade))
        draw.line((x, y + 1, x + length, y + rise + 1), fill=_shift_rgb(base_color, shade))


def _draw_slate_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    for _index in range(max(8, height // 36)):
        y = texture_rng.randrange(height)
        start = texture_rng.randrange(max(1, width // 3))
        end = texture_rng.randint(max(start + 1, width * 2 // 3), width)
        rise = texture_rng.randint(-3, 3)
        draw.line((start, y, end, y + rise), fill=_shift_rgb(base_color, texture_rng.randint(4, 8)))
    for _index in range(max(20, width * height // 5000)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        draw.point((x, y), fill=_shift_rgb(base_color, texture_rng.randint(9, 18)))


def _draw_plaster_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    minimum = min(width, height)
    for _index in range(max(4, width * height // 160000)):
        radius = texture_rng.randint(max(8, minimum // 12), max(9, minimum // 4))
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        start = texture_rng.randint(0, 330)
        draw.arc(
            (x - radius, y - radius, x + radius, y + radius),
            start=start,
            end=start + texture_rng.randint(18, 52),
            fill=_shift_rgb(base_color, texture_rng.choice((-3, 3))),
        )
    for _index in range(max(20, width * height // 4300)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        radius = texture_rng.randint(1, 2)
        draw.ellipse((x, y, x + radius, y + radius), fill=_shift_rgb(base_color, -texture_rng.randint(9, 18)))


def _draw_concrete_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    for _index in range(max(30, width * height // 2600)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        radius = texture_rng.randint(1, 3)
        shade = texture_rng.choice((-24, -17, 13, 20))
        draw.ellipse((x, y, x + radius, y + radius), fill=_shift_rgb(base_color, shade))
    for _index in range(max(2, width * height // 220000)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        points = [(x, y)]
        for _segment in range(texture_rng.randint(2, 4)):
            x += texture_rng.randint(5, 18)
            y += texture_rng.randint(-5, 5)
            points.append((x, y))
        draw.line(points, fill=_shift_rgb(base_color, -14))


def _draw_brushed_metal_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    y = texture_rng.randint(0, 2)
    while y < height:
        shade = texture_rng.choice((-8, -5, 4, 7))
        draw.line((0, y, width, y + texture_rng.randint(-1, 1)), fill=_shift_rgb(base_color, shade))
        y += texture_rng.randint(2, 4)
    for _index in range(max(12, width * height // 9000)):
        y = texture_rng.randrange(height)
        x = texture_rng.randrange(width)
        length = texture_rng.randint(max(2, width // 30), max(3, width // 7))
        draw.line((x, y, x + length, y), fill=_shift_rgb(base_color, texture_rng.choice((-12, 11))))


def _draw_sandstone_details(
    surface: Image.Image,
    texture_rng: random.Random,
    base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    y = texture_rng.randint(10, 24)
    while y < height:
        shade = texture_rng.choice((-4, -3, 3, 4))
        x = texture_rng.randint(0, max(1, width // 8))
        while x < width:
            length = texture_rng.randint(max(10, width // 9), max(12, width // 3))
            end = min(width, x + length)
            step = max(8, length // 4)
            points = [(x, y)]
            current_y = y
            for point_x in range(x + step, end, step):
                current_y += texture_rng.randint(-2, 2)
                points.append((point_x, current_y))
            points.append((end, current_y + texture_rng.randint(-2, 2)))
            draw.line(points, fill=_shift_rgb(base_color, shade))
            x = end + texture_rng.randint(max(4, width // 30), max(6, width // 12))
        y += texture_rng.randint(32, 68)
    for _index in range(max(24, width * height // 3600)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        shade = texture_rng.choice((-20, -13, 13, 19))
        draw.point((x, y), fill=_shift_rgb(base_color, shade))


def _draw_terrazzo_details(
    surface: Image.Image,
    texture_rng: random.Random,
    _base_color: tuple[int, int, int],
) -> None:
    width, height = surface.size
    draw = ImageDraw.Draw(surface)
    chip_colors = (
        (112, 119, 115),
        (164, 112, 96),
        (184, 159, 111),
        (103, 101, 96),
        (217, 207, 183),
    )
    for _index in range(max(20, width * height // 6200)):
        x = texture_rng.randrange(width)
        y = texture_rng.randrange(height)
        radius = texture_rng.randint(2, 7)
        points = (
            (x - radius, y + texture_rng.randint(-radius, 0)),
            (x + texture_rng.randint(0, radius), y - radius),
            (x + radius, y + texture_rng.randint(0, radius)),
            (x + texture_rng.randint(-radius, 0), y + radius),
        )
        draw.polygon(points, fill=texture_rng.choice(chip_colors))


_SURFACE_DETAIL_RENDERERS = {
    "felt": _draw_felt_details,
    "linen": _draw_linen_details,
    "kraft paper": _draw_kraft_details,
    "watercolor paper": _draw_watercolor_details,
    "slate": _draw_slate_details,
    "plaster": _draw_plaster_details,
    "concrete": _draw_concrete_details,
    "brushed metal": _draw_brushed_metal_details,
    "sandstone": _draw_sandstone_details,
    "terrazzo": _draw_terrazzo_details,
}


def _procedural_surface_work_size(width: int, height: int) -> tuple[int, int]:
    """Return a high-DPI work size capped independently of output dimensions."""

    output_scale = max(1, min(3, round(min(width, height) / 1080)))
    while (
        ((width + output_scale - 1) // output_scale)
        * ((height + output_scale - 1) // output_scale)
        > _PROCEDURAL_SURFACE_MAX_WORK_PIXELS
    ):
        output_scale += 1
    return (
        max(1, (width + output_scale - 1) // output_scale),
        max(1, (height + output_scale - 1) // output_scale),
    )


def _procedural_surface_texture(
    size: tuple[int, int],
    style: str,
    *,
    seed: int = 0,
) -> Image.Image:
    """Generate one deterministic matte surface using Pillow-only primitives."""

    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid procedural surface size: {size}")
    if style not in _PROCEDURAL_SURFACE_STYLES:
        raise ValueError(f"Unsupported procedural surface: {style}")

    mixed_seed = (
        seed
        ^ _SURFACE_STYLE_SEEDS[style]
        ^ (width * 0x9E3779B185EBCA87)
        ^ (height * 0xC2B2AE3D27D4EB4F)
    ) & _CORKBOARD_SEED_MASK
    texture_rng = random.Random(mixed_seed)
    work_size = _procedural_surface_work_size(width, height)
    work_width, work_height = work_size
    base_color = POSTCARD_BACKGROUND_COLORS[style]
    surface = Image.new("RGB", work_size, base_color)
    fine_contrast, fine_opacity, coarse_contrast, coarse_opacity, coarse_divisor = (
        _SURFACE_NOISE_RECIPES[style]
    )
    fine_size = (
        max(1, (work_width + 1) // 2),
        max(1, (work_height + 1) // 2),
    )
    surface = _blend_seeded_noise(
        surface,
        texture_rng=texture_rng,
        base_color=base_color,
        source_size=fine_size,
        contrast=fine_contrast,
        opacity=fine_opacity,
        resample=Image.Resampling.BILINEAR,
    )
    coarse_step = max(18, min(work_width, work_height) // coarse_divisor)
    coarse_size = (
        max(2, (work_width + coarse_step - 1) // coarse_step),
        max(2, (work_height + coarse_step - 1) // coarse_step),
    )
    surface = _blend_seeded_noise(
        surface,
        texture_rng=texture_rng,
        base_color=base_color,
        source_size=coarse_size,
        contrast=coarse_contrast,
        opacity=coarse_opacity,
        resample=Image.Resampling.BICUBIC,
    )
    _SURFACE_DETAIL_RENDERERS[style](surface, texture_rng, base_color)

    if work_size == size:
        return surface
    textured = surface.resize(size, Image.Resampling.BILINEAR)
    surface.close()
    return textured


def _postcard_background_image(
    size: tuple[int, int],
    color: tuple[int, int, int],
    *,
    surface_style: str | None,
    seed: int = 0,
) -> Image.Image:
    """Allocate a solid or procedurally textured Postcard background."""

    if surface_style is None:
        return Image.new("RGB", size, color)
    if surface_style == "corkboard":
        return _corkboard_texture(size, seed=seed)
    return _procedural_surface_texture(size, surface_style, seed=seed)


def compose_postcard(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    tilt: bool = True,
    background: str = "dark",
    rng: random.Random | None = None,
) -> Path:
    """Compose random bare photos using the same layout behavior as Polaroid."""

    try:
        background_color = POSTCARD_BACKGROUND_COLORS[background]
    except KeyError as exc:
        raise ValueError(f"Unsupported Postcard background: {background}") from exc

    return _compose_scattered_photos(
        monitors,
        images_by_monitor,
        output_path,
        framed=False,
        background_color=background_color,
        surface_style=None if background == "dark" else background,
        bar_color=bar_color,
        size=size,
        span=span,
        tilt=tilt,
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
    background_color: tuple[int, int, int],
    surface_style: str | None = None,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    tilt: bool = True,
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
        combined = _postcard_background_image(
            (width, height),
            background_color,
            surface_style=surface_style,
        )
        max_card_size = (
            max(1, round(max(monitor.width for monitor in monitors) * size_fraction)),
            max(1, round(max(monitor.height for monitor in monitors) * size_fraction)),
        )
        image_paths = [
            image_path
            for monitor in monitors
            for image_path in images_by_monitor.get(monitor.name, [])
        ]
        card_specs = [
            (image_path, rng.uniform(-10.0, 10.0) if tilt else 0.0)
            for image_path in image_paths
        ]
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
        panel_position = normalized_position(monitor, min_x, min_y)
        texture_seed = (
            panel_position[0] * 0x9E3779B1 ^ panel_position[1] * 0x85EBCA77
        ) & _CORKBOARD_SEED_MASK
        panel = _postcard_background_image(
            (monitor.width, monitor.height),
            background_color,
            surface_style=surface_style,
            seed=texture_seed,
        )
        max_card_size = (
            max(1, round(monitor.width * size_fraction)),
            max(1, round(monitor.height * size_fraction)),
        )
        card_specs = [
            (image_path, rng.uniform(-10.0, 10.0) if tilt else 0.0)
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
        combined.paste(panel, panel_position)
    return _save_png_atomic(combined, output_path)


def compose_polaroid(
    monitors: list[Monitor],
    images_by_monitor: dict[str, list[str]],
    output_path: str | Path,
    *,
    bar_color: str = "black",
    size: float = 0.5,
    span: bool = False,
    tilt: bool = True,
    rng: random.Random | None = None,
) -> Path:
    """Compose random framed Polaroid prints per monitor or across the virtual desktop."""

    return _compose_scattered_photos(
        monitors,
        images_by_monitor,
        output_path,
        framed=True,
        background_color=POLAROID_BACKGROUND_COLOR,
        bar_color=bar_color,
        size=size,
        span=span,
        tilt=tilt,
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
