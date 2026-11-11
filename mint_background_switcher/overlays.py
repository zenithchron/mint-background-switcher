"""Picture overlays drawn onto composed wallpapers.

Inspired by John's Background Switcher (OVR-01..OVR-06): the picture
title, photographer, and date are rendered as a small text panel and an
optional monthly calendar card (today highlighted) on top of the
*composed* wallpaper, so overlays compose with every fit mode and stay
sharp on fractionally-scaled displays (all geometry is physical panel
pixels).  User-defined no-draw zones (pixels, per-monitor or for the
whole desktop) are never drawn into.

The overlay step is fail-open: metadata problems or zone collisions skip
the affected panel instead of breaking wallpaper rotation.
"""

from __future__ import annotations

import calendar
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from .monitor import Monitor

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Profile

__all__ = [
    "MAX_LINE_CHARS",
    "MAX_NO_DRAW_ZONES",
    "MAX_ZONE_COORD",
    "CALENDAR_TODAY_FILL",
    "DEFAULT_OVERLAY_CALENDAR_POSITION",
    "OVERLAY_CALENDAR_POSITIONS",
    "NoDrawZone",
    "OverlayPanel",
    "OverlayResult",
    "PictureInfo",
    "apply_overlays",
    "canvas_offset",
    "coerce_no_draw_zones",
    "draw_calendar_panel",
    "overlay_lines",
    "overlays_enabled",
    "panel_for_span",
    "panels_for_monitors",
    "read_picture_info",
    "render_overlay_preview",
    "zones_in_canvas",
]

MAX_NO_DRAW_ZONES = 8
MAX_ZONE_COORD = 100_000
MAX_LINE_CHARS = 60

# Calendar overlay (JBS OVR-06): the corner the monthly calendar card is
# preferred in, plus the allowed corner choices.
OVERLAY_CALENDAR_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")
DEFAULT_OVERLAY_CALENDAR_POSITION = "bottom-right"
# Same blue as the three-month calendar effect (images.py).
CALENDAR_TODAY_FILL = (64, 120, 216, 255)

# Sentinel monitor name: the zone applies to the whole virtual desktop
# (canvas coordinates), not to one physical monitor.
ALL_MONITORS = ""


@dataclass(frozen=True, slots=True)
class PictureInfo:
    """The metadata a picture carries, with filename/mtime fallbacks."""

    title: str
    artist: str
    date_text: str


@dataclass(frozen=True, slots=True)
class NoDrawZone:
    """A rectangle (pixels) where overlays must never be drawn.

    ``monitor`` is a physical monitor name, or the empty string for the
    whole virtual desktop (zone coordinates are then canvas-relative).
    """

    monitor: str
    left: int
    top: int
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return {
            "monitor": self.monitor,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class OverlayPanel:
    """One region of the composed wallpaper that can receive an overlay.

    ``rect`` is (x, y, width, height) in canvas (physical) pixels and
    ``image_path`` is the picture whose metadata should be shown there.
    """

    name: str
    rect: tuple[int, int, int, int]
    image_path: str


@dataclass(frozen=True, slots=True)
class OverlayResult:
    drawn: int
    skipped: int
    note: str


def _coerce_pixel(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def coerce_no_draw_zones(value: object) -> list[NoDrawZone]:
    """Normalize stored zone data; invalid entries are dropped.

    Rules: at most ``MAX_NO_DRAW_ZONES`` zones, coordinates are whole
    pixels in ``0..MAX_ZONE_COORD`` (sizes ``1..MAX_ZONE_COORD``), and
    duplicates are ignored.
    """
    zones: list[NoDrawZone] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    if not isinstance(value, (list, tuple)):
        return zones
    for item in value:
        if len(zones) >= MAX_NO_DRAW_ZONES:
            break
        if not isinstance(item, dict):
            continue
        monitor = item.get("monitor", ALL_MONITORS)
        left = _coerce_pixel(item.get("left"))
        top = _coerce_pixel(item.get("top"))
        width = _coerce_pixel(item.get("width"))
        height = _coerce_pixel(item.get("height"))
        if not isinstance(monitor, str):
            continue
        if left is None or top is None or width is None or height is None:
            continue
        if not 0 <= left <= MAX_ZONE_COORD:
            continue
        if not 0 <= top <= MAX_ZONE_COORD:
            continue
        if not 1 <= width <= MAX_ZONE_COORD:
            continue
        if not 1 <= height <= MAX_ZONE_COORD:
            continue
        key = (monitor, left, top, width, height)
        if key in seen:
            continue
        seen.add(key)
        zones.append(NoDrawZone(monitor, left, top, width, height))
    return zones


def _clean_text(raw: object) -> str:
    text = " ".join(str(raw).split())
    return text[:120]


def _parse_exif_date(raw: object) -> str:
    text = str(raw).strip()
    if not text:
        return ""
    date_part = text[:10].replace(":", "-")
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _fallback_title(path: Path) -> str:
    stem = path.stem
    return stem or path.name


def _fallback_date(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


def read_picture_info(image_path: str | Path) -> PictureInfo:
    """Read title/photographer/date metadata for one picture.

    EXIF fields are used when present (ImageDescription, Artist,
    DateTimeOriginal/DateTimeDigitized/DateTime); otherwise the file
    name and modification date stand in.  Never raises: unreadable
    pictures simply yield their fallbacks.
    """
    path = Path(image_path)
    title = ""
    artist = ""
    date_text = ""
    try:
        with Image.open(path) as source:
            exif = source.getexif()
            base = exif if exif is not None else Image.Exif()
            sub = base.get_ifd(0x8769)  # Exif sub-IFD pointer (PIL.ExifTags.IFD.Exif; the IFD table does not exist in Pillow 9.1)
            title = _clean_text(base.get(0x010E) or sub.get(0x010E) or "")
            artist = _clean_text(base.get(0x013B) or sub.get(0x013B) or "")
            raw_date = sub.get(0x9003) or sub.get(0x9004) or base.get(0x0132) or ""
            date_text = _parse_exif_date(raw_date)
    except Exception:
        pass
    if not title:
        title = _fallback_title(path)
    if not date_text:
        date_text = _fallback_date(path)
    return PictureInfo(title=title, artist=artist, date_text=date_text)


def overlays_enabled(profile: Profile) -> bool:
    return bool(
        profile.overlay_title
        or profile.overlay_artist
        or profile.overlay_date
        or profile.overlay_calendar
    )


def overlay_lines(profile: Profile, info: PictureInfo) -> list[str]:
    """The enabled, non-empty lines for this picture (title first)."""
    lines: list[str] = []
    if profile.overlay_title and info.title:
        lines.append(info.title)
    if profile.overlay_artist and info.artist:
        lines.append(info.artist)
    if profile.overlay_date and info.date_text:
        lines.append(info.date_text)
    return lines


def canvas_offset(monitors: Sequence[Monitor]) -> tuple[int, int]:
    """Canvas origin: the minimum x/y of every monitor."""
    if not monitors:
        return (0, 0)
    return (min(monitor.x for monitor in monitors), min(monitor.y for monitor in monitors))


def panels_for_monitors(
    monitors: Sequence[Monitor], image_by_name: Mapping[str, str]
) -> list[OverlayPanel]:
    """One overlay panel per monitor, in canvas coordinates."""
    min_x, min_y = canvas_offset(monitors)
    return [
        OverlayPanel(
            monitor.name,
            (monitor.x - min_x, monitor.y - min_y, monitor.width, monitor.height),
            str(image_by_name.get(monitor.name, "")),
        )
        for monitor in monitors
    ]


def panel_for_span(monitors: Sequence[Monitor], image_path: str) -> OverlayPanel:
    """The single overlay panel covering the whole virtual desktop."""
    min_x, min_y = canvas_offset(monitors)
    width = max((monitor.x + monitor.width for monitor in monitors), default=0) - min_x
    height = max((monitor.y + monitor.height for monitor in monitors), default=0) - min_y
    return OverlayPanel(ALL_MONITORS, (0, 0, width, height), str(image_path))


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    # Touching edges does not count as overlapping.
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def zones_in_canvas(
    zones: Sequence[NoDrawZone],
    monitors: Sequence[Monitor],
    canvas_size: tuple[int, int],
    panel_rect: tuple[int, int, int, int] | None = None,
) -> list[tuple[int, int, int, int]]:
    """No-draw zones as canvas-coordinate (left, top, right, bottom) rects.

    Per-monitor zones are translated by that monitor's canvas offset;
    unknown monitor names are ignored.  ``panel_rect`` limits the result
    to zones intersecting one overlay panel.
    """
    min_x, min_y = canvas_offset(monitors)
    canvas_w, canvas_h = canvas_size
    by_name = {monitor.name: monitor for monitor in monitors}
    rects: list[tuple[int, int, int, int]] = []
    for zone in zones:
        if zone.monitor:
            monitor = by_name.get(zone.monitor)
            if monitor is None:
                continue
            left = monitor.x - min_x + zone.left
            top = monitor.y - min_y + zone.top
        else:
            left = zone.left
            top = zone.top
        right = left + zone.width
        bottom = top + zone.height
        left = max(0, min(left, canvas_w))
        top = max(0, min(top, canvas_h))
        right = max(0, min(right, canvas_w))
        bottom = max(0, min(bottom, canvas_h))
        if right - left < 1 or bottom - top < 1:
            continue
        rect = (left, top, right, bottom)
        if panel_rect is not None:
            panel_x, panel_y, panel_w, panel_h = panel_rect
            if not _overlaps(rect, (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h)):
                continue
        rects.append(rect)
    return rects


def _overlay_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size=max(8, size))
    except OSError:
        return ImageFont.load_default()


def _fit_fonts(
    draw: ImageDraw.ImageDraw,
    texts: list[str],
    max_width: int,
    sizes: list[int],
) -> tuple[list[str], list[ImageFont.FreeTypeFont | ImageFont.ImageFont], list[int]]:
    """Shrink (and if needed truncate) text until every line fits."""
    limit = MAX_LINE_CHARS
    current = list(sizes)
    for _ in range(12):
        clamped = [
            text[: limit - 1].rstrip() + "…" if len(text) >= limit else text
            for text in texts
        ]
        fonts = [_overlay_font(size, bold=index == 0) for index, size in enumerate(current)]
        if all(draw.textlength(text, font=font) <= max_width for text, font in zip(clamped, fonts)):
            return clamped, fonts, current
        current = [max(9, size - max(2, size // 10)) for size in current]
        limit = max(12, limit // 2)
    clamped = [text[:11].rstrip() + "…" if len(text) >= 12 else text for text in texts]
    fonts = [_overlay_font(size, bold=index == 0) for index, size in enumerate(current)]
    return clamped, fonts, current


def _place_text_panel(
    image: Image.Image,
    panel_rect: tuple[int, int, int, int],
    lines: list[str],
    zone_rects: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """Draw a semi-transparent text panel inside ``panel_rect``.

    Tries bottom-left, bottom-right, top-left, then top-right anchors;
    the first position clear of every no-draw zone wins.  Returns the
    drawn rectangle, or ``None`` when no clear position exists (or the
    panel is too small).
    """
    panel_x, panel_y, panel_w, panel_h = panel_rect
    if panel_w < 112 or panel_h < 84 or not lines:
        return None
    draw = ImageDraw.Draw(image)
    margin = max(6, panel_h // 60)
    pad = max(8, panel_h // 45)
    max_text_w = panel_w - 2 * margin - 2 * pad
    if max_text_w < 64:
        return None
    # Font sizes follow the physical panel height so scaled (fractional)
    # displays get proportionally larger text.
    sizes = [min(72, max(12, panel_h // 30))] + [min(54, max(10, panel_h // 42))] * (len(lines) - 1)
    texts, fonts, sizes = _fit_fonts(draw, lines, max_text_w, sizes)
    metrics = []
    for text, font in zip(texts, fonts):
        top, _, _, bottom = draw.textbbox((0, 0), text, font=font)
        metrics.append((bottom - top, top))
    line_gap = sum(int(size * 0.25) for size in sizes)
    text_w = max(int(draw.textlength(text, font=font)) for text, font in zip(texts, fonts))
    box_w = text_w + 2 * pad
    box_h = sum(height for height, _ in metrics) + line_gap + 2 * pad
    if box_w > panel_w - 2 * margin or box_h > panel_h - 2 * margin:
        return None
    candidates = (
        (panel_x + margin, panel_y + panel_h - box_h - margin),
        (panel_x + panel_w - box_w - margin, panel_y + panel_h - box_h - margin),
        (panel_x + margin, panel_y + margin),
        (panel_x + panel_w - box_w - margin, panel_y + margin),
    )
    chosen: tuple[int, int, int, int] | None = None
    for x, y in candidates:
        rect = (x, y, x + box_w, y + box_h)
        if all(not _overlaps(rect, zone) for zone in zone_rects):
            chosen = rect
            break
    if chosen is None:
        return None
    x, y, right, bottom = chosen
    draw.rounded_rectangle(
        [x, y, right, bottom],
        radius=max(6, box_h // 8),
        fill=(8, 12, 18, 205),
        outline=(255, 255, 255, 90),
        width=max(1, box_h // 90),
    )
    ty = y + pad
    for (text, font, size), (height, top_offset) in zip(zip(texts, fonts, sizes), metrics):
        draw.text(
            (x + pad, ty - top_offset),
            text,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=max(1, size // 16),
            stroke_fill=(0, 0, 0, 200),
        )
        ty += height + int(size * 0.25)
    return chosen


def _centered_text(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (center[0] - (right - left) / 2 - left, center[1] - (bottom - top) / 2 - top),
        text,
        font=font,
        fill=fill,
    )


def draw_calendar_panel(
    image: Image.Image,
    panel_rect: tuple[int, int, int, int],
    *,
    now: datetime | None = None,
    position: str = DEFAULT_OVERLAY_CALENDAR_POSITION,
    zone_rects: Sequence[tuple[int, int, int, int]] = (),
) -> tuple[int, int, int, int] | None:
    """Draw a small monthly calendar card (JBS OVR-06) inside ``panel_rect``.

    The card shows the month of ``now`` (default: the current date) with
    today highlighted.  The requested corner is tried first, then the
    remaining corners in a fixed order; the first one clear of every
    obstacle in ``zone_rects`` wins.  Returns the drawn rectangle in
    canvas pixels, or ``None`` when no corner is clear or the panel is
    too small.
    """
    month_day = (now or datetime.now()).date()
    panel_x, panel_y, panel_w, panel_h = panel_rect
    draw = ImageDraw.Draw(image)
    # Sizing follows the physical panel height so fractional-scale
    # displays get a proportionally larger card.
    day_size = min(20, max(10, panel_h // 68))
    title_font = _overlay_font(day_size + 4, bold=True)
    day_font = _overlay_font(day_size)
    today_font = _overlay_font(day_size, bold=True)
    head_font = _overlay_font(max(8, day_size - 2))
    cell_w = int(draw.textlength("31", font=day_font)) + 2 * max(2, day_size // 4)
    title_h = max(12, _text_height(draw, month_day.strftime("%B %Y"), title_font))
    row_h = max(12, int(day_size * 1.45))
    pad = max(8, panel_h // 90)
    gap = max(3, day_size // 3)
    card_w = 7 * cell_w + 2 * pad
    card_h = pad + title_h + gap + 7 * row_h + pad
    margin = max(8, panel_h // 100)
    if card_w > panel_w - 2 * margin or card_h > panel_h - 2 * margin:
        return None
    order = list(OVERLAY_CALENDAR_POSITIONS)
    if position in order:
        order.remove(position)
        order.insert(0, position)
    for corner in order:
        x = panel_x + margin if corner.endswith("left") else panel_x + panel_w - card_w - margin
        y = panel_y + margin if corner.startswith("top") else panel_y + panel_h - card_h - margin
        rect = (x, y, x + card_w, y + card_h)
        if all(not _overlaps(rect, zone) for zone in zone_rects):
            _draw_calendar_card(draw, rect, month_day, title_font, day_font, today_font, head_font, cell_w, row_h, pad, gap, title_h)
            return rect
    return None


def _text_height(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), text, font=font)
    return int(bottom - top)


def _draw_calendar_card(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    month_day: date,
    title_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    day_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    today_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    head_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    cell_w: int,
    row_h: int,
    pad: int,
    gap: int,
    title_h: int,
) -> None:
    x, y, right, bottom = rect
    card_w = right - x
    card_h = bottom - y
    draw.rounded_rectangle(
        [x, y, right, bottom],
        radius=max(6, card_h // 10),
        fill=(8, 12, 18, 205),
        outline=(255, 255, 255, 90),
        width=max(1, card_h // 90),
    )
    center_x = x + card_w / 2
    _centered_text(draw, (center_x, y + pad + title_h / 2), month_day.strftime("%B %Y"), font=title_font, fill=(255, 255, 255, 255))
    grid_top = y + pad + title_h + gap
    for column, letter in enumerate(("M", "T", "W", "T", "F", "S", "S")):
        _centered_text(
            draw,
            (x + pad + (column + 0.5) * cell_w, grid_top + row_h / 2),
            letter,
            font=head_font,
            fill=(190, 203, 220, 255),
        )
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(month_day.year, month_day.month)
    weeks.extend([[0] * 7 for _ in range(6 - len(weeks))])
    for week_index, week in enumerate(weeks[:6]):
        for column, day_number in enumerate(week):
            if day_number == 0:
                continue
            cell_center = (
                x + pad + (column + 0.5) * cell_w,
                grid_top + (week_index + 1.5) * row_h,
            )
            is_today = day_number == month_day.day
            if is_today:
                half_w = max(3, cell_w * 0.42)
                half_h = max(3, row_h * 0.42)
                draw.rounded_rectangle(
                    (
                        cell_center[0] - half_w,
                        cell_center[1] - half_h,
                        cell_center[0] + half_w,
                        cell_center[1] + half_h,
                    ),
                    radius=max(2, round(min(half_w, half_h) / 2)),
                    fill=CALENDAR_TODAY_FILL,
                )
            _centered_text(
                draw,
                cell_center,
                str(day_number),
                font=today_font if is_today else day_font,
                fill=(255, 255, 255, 255),
            )


def _save_in_place(image: Image.Image, path: Path) -> None:
    """Atomically rewrite the composed file in its own format.

    The rewrite goes to a temporary file in the same directory, then
    replaces the destination in one step, so a failed save (disk full,
    I/O error) can never leave the current wallpaper truncated; the
    service's fail-open handler then applies the last good file.
    """
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image = image.convert("RGB")
        image_format, save_kwargs = "JPEG", {"quality": 95}
    elif suffix == ".webp":
        image_format, save_kwargs = "WEBP", {"quality": 95}
    else:
        image_format, save_kwargs = "PNG", {}
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file_handle:
            image.save(file_handle, format=image_format, **save_kwargs)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _result_note(drawn: int, total: int, reasons: dict[str, int], subject: str = "picture info") -> str:
    if drawn == total:
        plural = "s" if total != 1 else ""
        return f"Overlay: {subject} drawn on {drawn} panel{plural}."
    detail = "; ".join(f"{count} panel{'s' if count != 1 else ''}: {reason}" for reason, count in sorted(reasons.items()))
    if drawn:
        return f"Overlay: {subject} drawn on {drawn} of {total} panels ({detail} skipped)."
    return f"Overlay: no panels annotated ({detail})."


def apply_overlays(
    wallpaper_path: str | Path,
    panels: Sequence[OverlayPanel],
    profile: Profile,
    monitors: Sequence[Monitor],
    *,
    now: datetime | None = None,
) -> OverlayResult:
    """Draw the picture-info and calendar overlays onto a composed wallpaper in place.

    ``panels`` are canvas-coordinate regions, one per picture that was
    composed; each receives the enabled metadata lines for its own
    picture, and a monthly calendar card when the profile enables one.
    Failures on individual panels (missing metadata, no-draw zone
    collisions) skip that panel only.  The composed file is rewritten
    only when at least one panel was drawn.
    """
    if not panels or not overlays_enabled(profile):
        return OverlayResult(0, 0, "")
    path = Path(wallpaper_path)
    text_enabled = bool(profile.overlay_title or profile.overlay_artist or profile.overlay_date)
    calendar_enabled = bool(profile.overlay_calendar)
    if text_enabled and calendar_enabled:
        subject = "picture info and calendar"
    elif calendar_enabled:
        subject = "calendar"
    else:
        subject = "picture info"
    with Image.open(path) as source:
        image = source.convert("RGBA")
        canvas_size = image.size
        reasons: dict[str, int] = {}
        drawn = 0
        for panel in panels:
            zone_rects = zones_in_canvas(profile.no_draw_zones, monitors, canvas_size, panel.rect)
            text_rect: tuple[int, int, int, int] | None = None
            text_reason: str | None = None
            if text_enabled:
                if not panel.image_path or not Path(panel.image_path).is_file():
                    text_reason = "missing picture"
                else:
                    try:
                        info = read_picture_info(panel.image_path)
                        lines = overlay_lines(profile, info)
                        if not lines:
                            text_reason = "no stored metadata"
                        else:
                            text_rect = _place_text_panel(image, panel.rect, lines, zone_rects)
                            if text_rect is None:
                                text_reason = "blocked by no-draw zones" if zone_rects else "panel too small"
                    except Exception:
                        # Fail-open: a drawing error skips this panel's text
                        # without aborting the rest.
                        text_reason = "drawing error"
            calendar_rect: tuple[int, int, int, int] | None = None
            calendar_reason: str | None = None
            if calendar_enabled:
                # The text panel (already placed) is an obstacle too, so the
                # two overlays never draw on top of each other.
                obstacles = list(zone_rects) + ([text_rect] if text_rect is not None else [])
                try:
                    calendar_rect = draw_calendar_panel(
                        image,
                        panel.rect,
                        now=now,
                        position=profile.overlay_calendar_position,
                        zone_rects=obstacles,
                    )
                    if calendar_rect is None:
                        calendar_reason = "blocked by no-draw zones" if obstacles else "panel too small"
                except Exception:
                    calendar_reason = "drawing error"
            if text_rect is not None or calendar_rect is not None:
                drawn += 1
            else:
                reason = text_reason if text_reason is not None else calendar_reason
                if reason is not None:
                    reasons[reason] = reasons.get(reason, 0) + 1
        if drawn:
            _save_in_place(image, path)
    total = len(panels)
    return OverlayResult(drawn, total - drawn, _result_note(drawn, total, reasons, subject))


def render_overlay_preview(
    image_path: str | Path,
    out_path: str | Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fit_mode: str = "scale_to_fit",
    bar_color: str = "black",
    show_title: bool = True,
    show_artist: bool = True,
    show_date: bool = True,
    zones: Sequence[NoDrawZone] | None = None,
    show_calendar: bool = False,
    calendar_position: str = DEFAULT_OVERLAY_CALENDAR_POSITION,
    now: datetime | None = None,
) -> Path:
    """Render a standalone overlay preview image for one picture.

    The picture is fitted into ``width``×``height`` with the given fit
    mode and a single whole-canvas overlay panel is drawn with the
    enabled metadata lines and, when ``show_calendar`` is set, the
    monthly calendar card.  "All monitors" no-draw zones are honored in
    canvas coordinates; per-monitor zones are ignored (a preview is a
    single virtual screen).
    """
    info = read_picture_info(image_path)
    lines = []
    if show_title and info.title:
        lines.append(info.title)
    if show_artist and info.artist:
        lines.append(info.artist)
    if show_date and info.date_text:
        lines.append(info.date_text)
    from .images import fit_image  # lazy: images imports config, config imports overlays

    with Image.open(image_path) as source:
        base = fit_image(source, (width, height), fit_mode=fit_mode, bar_color=bar_color)
    base = base.convert("RGBA")
    if lines or show_calendar:
        panel = OverlayPanel(ALL_MONITORS, (0, 0, width, height), str(image_path))
        zone_rects = zones_in_canvas(list(zones or []), [], (width, height), panel.rect)
        text_rect = None
        if lines:
            text_rect = _place_text_panel(base, panel.rect, lines, zone_rects)
        if show_calendar:
            obstacles = zone_rects + ([text_rect] if text_rect is not None else [])
            draw_calendar_panel(
                base,
                panel.rect,
                now=now,
                position=calendar_position,
                zone_rects=obstacles,
            )
    out = Path(out_path)
    if out.suffix.lower() in {".jpg", ".jpeg"}:
        base.convert("RGB").save(out, quality=95)
    else:
        base.save(out)
    return out
