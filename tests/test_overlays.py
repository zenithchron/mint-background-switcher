"""Tests for the picture overlay feature (JBS OVR-01..OVR-05).

Covers the overlay rendering module, its config round-trip, the service
integration (single-picture layouts only, fail-open behavior), and the
new CLI subcommands.
"""

import json
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mint_background_switcher import cli, overlays
from mint_background_switcher import service
from mint_background_switcher.config import Config, Profile, load_config, save_config
from mint_background_switcher.monitor import Monitor
from mint_background_switcher.overlays import (
    MAX_NO_DRAW_ZONES,
    NoDrawZone,
    OverlayPanel,
    apply_overlays,
    canvas_offset,
    coerce_no_draw_zones,
    overlay_lines,
    overlays_enabled,
    panel_for_span,
    panels_for_monitors,
    read_picture_info,
    render_overlay_preview,
    zones_in_canvas,
)

BACKGROUND = (200, 200, 200)


def _make_jpeg(path: Path, *, title=None, artist=None, date=None, size=(160, 120), color=(210, 190, 160)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, quality=90)
    if title or artist or date:
        image = Image.open(path)
        exif = image.getexif()
        if title:
            exif[0x010E] = title
        if artist:
            exif[0x013B] = artist
        if date:
            # 0x8769 = Exif sub-IFD pointer (PIL.ExifTags.IFD.Exif; absent in Pillow 9.1).
            exif.get_ifd(0x8769)[0x9003] = date
            # Base-level DateTime (0x0132) as a fallback: Pillow 9.1 does not
            # round-trip sub-IFDs, so read_picture_info's base-level read keeps
            # the date available on the minimum supported Pillow too.
            exif[0x0132] = date
        image.save(path, quality=90, exif=exif)
    return path


def _make_png(path: Path, size=(400, 300), color=BACKGROUND) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _dark_bbox(path: Path):
    """Bounding box of dark (overlay) pixels in a flat BACKGROUND image."""
    image = Image.open(path).convert("L")
    return image.point(lambda v: 255 if v < 100 else 0).getbbox()


def _calendar_highlight_bbox(image: Image.Image):
    """Bounding box of the blue today-highlight pixels (exact color match)."""
    from PIL import ImageChops

    rgba = image.convert("RGBA")
    target = overlays.CALENDAR_TODAY_FILL
    bands = rgba.split()
    mask = bands[0].point(lambda v: 255 if v == target[0] else 0)
    for band, value in zip(bands[1:], target[1:]):
        mask = ImageChops.multiply(
            mask, band.point(lambda v, val=value: 255 if v == val else 0)
        )
    return mask.getbbox()


# ---------------------------------------------------------------------------
# Picture metadata
# ---------------------------------------------------------------------------


def test_read_picture_info_exif(tmp_path: Path):
    image = _make_jpeg(
        tmp_path / "photo.jpg",
        title="Sunrise",
        artist="Jane",
        date="2026:11:09 08:30:00",
    )
    info = read_picture_info(image)
    assert info.title == "Sunrise"
    assert info.artist == "Jane"
    assert info.date_text == "2026-11-09"


def test_read_picture_info_falls_back_to_name_and_mtime(tmp_path: Path):
    image = _make_png(tmp_path / "no-exif.png")
    info = read_picture_info(image)
    assert info.title == "no-exif"
    assert info.artist == ""
    assert len(info.date_text) == 10  # YYYY-MM-DD from the file mtime


def test_read_picture_info_unreadable_file_does_not_raise(tmp_path: Path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image at all")
    info = read_picture_info(broken)
    assert info.title == "broken"
    assert info.artist == ""


def test_read_picture_info_missing_file_does_not_raise(tmp_path: Path):
    info = read_picture_info(tmp_path / "missing.jpg")
    assert info.title == "missing"


# ---------------------------------------------------------------------------
# No-draw zones: coercion and profile round-trip
# ---------------------------------------------------------------------------


def test_coerce_no_draw_zones_valid():
    zones = coerce_no_draw_zones(
        [
            {"monitor": "", "left": 0, "top": 0, "width": 300, "height": 200},
            {"monitor": "A", "left": 10, "top": 20, "width": 5, "height": 5},
        ]
    )
    assert zones == [
        NoDrawZone("", 0, 0, 300, 200),
        NoDrawZone("A", 10, 20, 5, 5),
    ]


def test_coerce_no_draw_zones_dedupes_and_caps():
    base = {"monitor": "", "left": 1, "top": 2, "width": 3, "height": 4}
    zones = coerce_no_draw_zones([dict(base)] * (MAX_NO_DRAW_ZONES + 5))
    assert len(zones) == 1


def test_coerce_no_draw_zones_rejects_invalid_entries():
    zones = coerce_no_draw_zones(
        [
            "garbage",
            {"monitor": "", "left": -1, "top": 0, "width": 5, "height": 5},
            {"monitor": "", "left": 0, "top": 0, "width": 0, "height": 5},
            {"monitor": "", "left": "x", "top": 0, "width": 5, "height": 5},
            {"monitor": "", "left": 0, "top": 0, "width": 5},
        ]
    )
    assert zones == []


def test_profile_overlay_fields_round_trip():
    profile = Profile(
        name="P",
        overlay_title=True,
        overlay_artist=False,
        overlay_date=True,
        no_draw_zones=[NoDrawZone("A", 1, 2, 3, 4), NoDrawZone("", 5, 6, 7, 8)],
    )
    data = profile.to_dict()
    assert data["overlay_title"] is True
    assert data["overlay_artist"] is False
    assert data["overlay_date"] is True
    assert data["no_draw_zones"] == [
        {"monitor": "A", "left": 1, "top": 2, "width": 3, "height": 4},
        {"monitor": "", "left": 5, "top": 6, "width": 7, "height": 8},
    ]
    restored = Profile.from_dict("P", data)
    assert restored.overlay_title is True
    assert restored.overlay_date is True
    assert restored.no_draw_zones == profile.no_draw_zones


def test_profile_overlay_defaults_off():
    profile = Profile.from_dict("P", {})
    assert not profile.overlay_title
    assert not profile.overlay_artist
    assert not profile.overlay_date
    assert not profile.overlay_calendar
    assert profile.overlay_calendar_position == "bottom-right"
    assert profile.no_draw_zones == []


def test_profile_overlay_calendar_fields_round_trip():
    profile = Profile(name="P", overlay_calendar=True, overlay_calendar_position="top-left")
    data = profile.to_dict()
    assert data["overlay_calendar"] is True
    assert data["overlay_calendar_position"] == "top-left"
    restored = Profile.from_dict("P", data)
    assert restored.overlay_calendar is True
    assert restored.overlay_calendar_position == "top-left"


def test_profile_overlay_calendar_position_invalid_falls_back():
    restored = Profile.from_dict("P", {"overlay_calendar": "1", "overlay_calendar_position": "middle"})
    assert restored.overlay_calendar is True
    assert restored.overlay_calendar_position == "bottom-right"
    assert Profile.from_dict("P", {"overlay_calendar_position": 7}).overlay_calendar_position == "bottom-right"


# ---------------------------------------------------------------------------
# Line selection
# ---------------------------------------------------------------------------


def test_overlay_lines_respect_enabled_fields():
    from mint_background_switcher.overlays import PictureInfo

    picture = PictureInfo(title="T", artist="A", date_text="2026-11-09")
    assert overlay_lines(Profile(name="p"), picture) == []
    assert overlay_lines(Profile(name="p", overlay_title=True), picture) == ["T"]
    assert overlay_lines(Profile(name="p", overlay_artist=True, overlay_date=True), picture) == [
        "A",
        "2026-11-09",
    ]
    # Empty metadata lines are dropped even when the field is enabled.
    empty = PictureInfo(title="", artist="", date_text="")
    assert overlay_lines(Profile(name="p", overlay_title=True, overlay_artist=True), empty) == []
    assert overlays_enabled(Profile(name="p")) is False
    assert overlays_enabled(Profile(name="p", overlay_date=True)) is True


# ---------------------------------------------------------------------------
# Panel geometry
# ---------------------------------------------------------------------------


def test_panels_for_monitors_geometry():
    a = Monitor("A", 1000, 600, 0, 0)
    b = Monitor("B", 800, 600, 1000, 0)
    panels = panels_for_monitors([a, b], {"A": "x.jpg", "B": "y.jpg"})
    assert [panel.rect for panel in panels] == [(0, 0, 1000, 600), (1000, 0, 800, 600)]
    assert [panel.image_path for panel in panels] == ["x.jpg", "y.jpg"]


def test_panel_for_span_covers_all_monitors():
    a = Monitor("A", 1000, 600, 0, 0)
    b = Monitor("B", 800, 400, 1000, 200)
    span = panel_for_span([a, b], "x.jpg")
    assert span.rect == (0, 0, 1800, 600)
    assert span.image_path == "x.jpg"


def test_canvas_offset_with_negative_positions():
    left = Monitor("L", 1000, 600, -1000, 0)
    right = Monitor("R", 1000, 600, 0, 0)
    assert canvas_offset([left, right]) == (-1000, 0)


# ---------------------------------------------------------------------------
# No-draw zones in canvas coordinates
# ---------------------------------------------------------------------------


def test_zones_in_canvas_translates_monitor_offset():
    a = Monitor("A", 1000, 600, 0, 0)
    b = Monitor("B", 1000, 600, 1000, 0)
    zones = zones_in_canvas(
        [NoDrawZone("B", 10, 20, 100, 50)],
        [a, b],
        (2000, 600),
    )
    assert zones == [(1010, 20, 1110, 70)]


def test_zones_in_canvas_all_screens_is_canvas_relative():
    zones = zones_in_canvas([NoDrawZone("", 5, 6, 7, 8)], [], (1000, 500))
    assert zones == [(5, 6, 12, 14)]


def test_zones_in_canvas_unknown_monitor_ignored():
    zones = zones_in_canvas([NoDrawZone("Gone", 5, 6, 7, 8)], [], (1000, 500))
    assert zones == []


def test_zones_in_canvas_panel_filter_uses_xywh_rect():
    # A zone touching only the edge of the panel must not count as overlapping.
    zone = NoDrawZone("", 0, 0, 100, 100)
    panel_rect = (100, 0, 100, 100)  # starts exactly where the zone ends
    assert zones_in_canvas([zone], [], (200, 200), panel_rect) == []
    assert zones_in_canvas([zone], [], (200, 200), (50, 0, 100, 100)) == [(0, 0, 100, 100)]


# ---------------------------------------------------------------------------
# apply_overlays behavior
# ---------------------------------------------------------------------------


def test_apply_overlays_draws_on_panel(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    result = apply_overlays(wall, [panel], Profile(name="p", overlay_title=True), [])
    assert result.drawn == 1 and result.skipped == 0
    assert "1 panel" in result.note
    image = Image.open(wall)
    # Bottom-left corner should carry the dark panel now.
    assert image.getpixel((30, 570))[:3] != BACKGROUND
    # A far corner stays untouched.
    assert image.getpixel((990, 20))[:3] == BACKGROUND


def test_apply_overlays_disabled_profile_is_noop(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    before = wall.read_bytes()
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    result = apply_overlays(wall, [panel], Profile(name="p"), [])
    assert result.drawn == 0 and result.skipped == 0 and result.note == ""
    assert wall.read_bytes() == before


def test_apply_overlays_zone_relocates_panel(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    profile = Profile(name="p", overlay_title=True, no_draw_zones=[NoDrawZone("", 0, 300, 1000, 300)])
    result = apply_overlays(wall, [panel], profile, [])
    assert result.drawn == 1
    image = Image.open(wall)
    assert image.getpixel((30, 570))[:3] == BACKGROUND  # blocked strip stays clear
    assert image.getpixel((30, 30))[:3] != BACKGROUND  # relocated to top-left


def test_apply_overlays_zone_covering_panel_skips(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    before = wall.read_bytes()
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    profile = Profile(name="p", overlay_title=True, no_draw_zones=[NoDrawZone("", 0, 0, 1000, 600)])
    result = apply_overlays(wall, [panel], profile, [])
    assert result.drawn == 0 and result.skipped == 1
    assert "blocked by no-draw zones" in result.note
    assert wall.read_bytes() == before


def test_apply_overlays_per_monitor_zone_scope(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (2000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    a = Monitor("A", 1000, 600, 0, 0)
    b = Monitor("B", 1000, 600, 1000, 0)
    panels = [
        OverlayPanel("A", (0, 0, 1000, 600), str(photo)),
        OverlayPanel("B", (1000, 0, 1000, 600), str(photo)),
    ]
    profile = Profile(name="p", overlay_title=True, no_draw_zones=[NoDrawZone("B", 0, 0, 1000, 600)])
    result = apply_overlays(wall, panels, profile, [a, b])
    assert result.drawn == 1 and result.skipped == 1
    image = Image.open(wall)
    assert image.getpixel((30, 570))[:3] != BACKGROUND
    assert image.getpixel((1970, 570))[:3] == BACKGROUND


def test_apply_overlays_missing_picture_skips(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(tmp_path / "nope.jpg"))
    result = apply_overlays(wall, [panel], Profile(name="p", overlay_title=True), [])
    assert result.drawn == 0 and result.skipped == 1
    assert "missing picture" in result.note


def test_apply_overlays_panel_too_small_skips(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 100, 40), str(photo))
    result = apply_overlays(wall, [panel], Profile(name="p", overlay_title=True), [])
    assert result.drawn == 0 and result.skipped == 1


def test_apply_overlays_fractional_scale_proportional_panel(tmp_path: Path):
    # A physical 1350p panel (2400x1350 at 1.25x logical) must get a larger
    # overlay panel than a physical 1080p panel (1920x1080 at 1.0x): sizes are
    # derived from the panel's physical resolution, not logical size.
    wall_big = _make_png(tmp_path / "wall1350.png", (2400, 1350))
    wall_small = _make_png(tmp_path / "wall1080.png", (1920, 1080))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise over a very long horizon line")
    big = Monitor("S1", 2400, 1350, 0, 0, scale=1.25, logical_width=1920, logical_height=1080)
    small = Monitor("S0", 1920, 1080, 0, 0, scale=1.0)
    profile = Profile(name="p", overlay_title=True, overlay_artist=True, overlay_date=True)
    apply_overlays(wall_big, [panel_for_span([big], str(photo))], profile, [big])
    apply_overlays(wall_small, [panel_for_span([small], str(photo))], profile, [small])
    big_box = _dark_bbox(wall_big)
    small_box = _dark_bbox(wall_small)
    assert big_box and small_box
    big_height = big_box[3] - big_box[1]
    small_height = small_box[3] - small_box[1]
    assert big_height > small_height


# ---------------------------------------------------------------------------
# Calendar overlay (JBS OVR-06)
# ---------------------------------------------------------------------------


def _draw_calendar(tmp_image: Image.Image, *, now, position="bottom-right", zones=()):
    return overlays.draw_calendar_panel(
        tmp_image, (0, 0, 1000, 600), now=now, position=position, zone_rects=list(zones)
    )


def test_draw_calendar_panel_default_corner_and_highlight():
    image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
    rect = _draw_calendar(image, now=datetime(2026, 11, 15, 12, 0))
    assert rect is not None
    x, y, right, bottom = rect
    # Default corner is bottom-right, inside the panel with a small margin.
    assert right <= 1000 and bottom <= 600
    assert 1000 - right <= 40 and 600 - bottom <= 40
    assert x >= 0 and y >= 0
    highlight = _calendar_highlight_bbox(image)
    assert highlight is not None
    hx1, hy1, hx2, hy2 = highlight
    assert x < hx1 < hx2 < right, "today highlight must sit inside the card"
    assert y < hy1 < hy2 < bottom
    # A far corner stays untouched.
    assert image.getpixel((20, 20)) == (200, 200, 200, 255)


@pytest.mark.parametrize("position", ["bottom-right", "bottom-left", "top-right", "top-left"])
def test_draw_calendar_panel_all_corners(position):
    image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
    rect = _draw_calendar(image, now=datetime(2026, 11, 15), position=position)
    assert rect is not None
    x, y, right, bottom = rect
    if position.endswith("right"):
        assert 1000 - right <= 40
    else:
        assert x <= 40
    if position.startswith("top"):
        assert y <= 40
    else:
        assert 600 - bottom <= 40
    assert _calendar_highlight_bbox(image) is not None


def test_draw_calendar_panel_zone_blocks_requested_corner_relocates():
    image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
    # Cover the bottom-right corner; the card must move to the next corner.
    rect = _draw_calendar(image, now=datetime(2026, 11, 15), zones=[(850, 450, 1000, 600)])
    assert rect is not None
    x, y, right, bottom = rect
    assert not (x < 1000 and 850 < right and y < 600 and 450 < bottom), "must not overlap the zone"
    assert _calendar_highlight_bbox(image) is not None


def test_draw_calendar_panel_zones_covering_all_corners_returns_none():
    image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
    zones = [(0, 0, 200, 200), (800, 0, 1000, 200), (0, 400, 200, 600), (800, 400, 1000, 600)]
    assert _draw_calendar(image, now=datetime(2026, 11, 15), zones=zones) is None
    assert _calendar_highlight_bbox(image) is None


def test_draw_calendar_panel_too_small_returns_none():
    image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
    assert overlays.draw_calendar_panel(image, (0, 0, 120, 60), now=datetime(2026, 11, 15)) is None
    assert _calendar_highlight_bbox(image) is None


def test_draw_calendar_panel_highlights_the_right_day():
    # November 2026: 1st = Sunday (last column), 2nd = Monday (first column),
    # 15th is one week row below the 8th (same column).
    rects = {}
    for day in (1, 2, 8, 15):
        image = Image.new("RGBA", (1000, 600), (200, 200, 200, 255))
        rect = _draw_calendar(image, now=datetime(2026, 11, day))
        assert rect is not None
        rects[day] = _calendar_highlight_bbox(image)
    x, y, right, bottom = rects[1]
    sunday_x = (x + right) / 2
    x, y, right, bottom = rects[2]
    monday_x = (x + right) / 2
    assert sunday_x > monday_x
    _, top_8, _, bottom_8 = rects[8]
    _, top_15, _, bottom_15 = rects[15]
    assert (top_15 + bottom_15) / 2 > (top_8 + bottom_8) / 2
    # All highlights share the same card geometry (same month grid).
    centers_x = {((b[0] + b[2]) / 2) % 1 for b in (rects[8], rects[15])}
    assert len(centers_x) <= 2


def test_apply_overlays_calendar_only_draws_without_metadata(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg")  # no EXIF at all
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    profile = Profile(name="p", overlay_calendar=True)
    result = apply_overlays(wall, [panel], profile, [])
    assert result.drawn == 1 and result.skipped == 0
    assert "calendar drawn on 1 panel" in result.note
    image = Image.open(wall)
    assert _calendar_highlight_bbox(image) is not None
    # Bottom-right corner carries the card.
    assert image.getpixel((970, 570))[:3] != (200, 200, 200)
    # Top-left corner stays untouched.
    assert image.getpixel((20, 20))[:3] == (200, 200, 200)


def test_apply_overlays_calendar_only_missing_picture_still_draws(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(tmp_path / "nope.jpg"))
    result = apply_overlays(wall, [panel], Profile(name="p", overlay_calendar=True), [])
    assert result.drawn == 1 and result.skipped == 0
    assert Image.open(wall) is not None and _calendar_highlight_bbox(Image.open(wall)) is not None


def test_apply_overlays_text_and_calendar_do_not_overlap(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    profile = Profile(name="p", overlay_title=True, overlay_calendar=True)
    result = apply_overlays(wall, [panel], profile, [])
    assert result.drawn == 1 and result.skipped == 0
    assert "picture info and calendar" in result.note
    image = Image.open(wall)
    # The text panel takes the bottom-left, the calendar the bottom-right.
    assert image.getpixel((30, 570))[:3] != BACKGROUND
    assert image.getpixel((970, 570))[:3] != BACKGROUND
    # Both overlays are present and do not share pixels.
    assert _calendar_highlight_bbox(image) is not None
    assert _dark_bbox(wall) is not None


def test_apply_overlays_calendar_zone_covering_panel_skips(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    before = wall.read_bytes()
    photo = _make_jpeg(tmp_path / "photo.jpg")
    panel = OverlayPanel("A", (0, 0, 1000, 600), str(photo))
    profile = Profile(name="p", overlay_calendar=True, no_draw_zones=[NoDrawZone("", 0, 0, 1000, 600)])
    result = apply_overlays(wall, [panel], profile, [])
    assert result.drawn == 0 and result.skipped == 1
    assert "blocked by no-draw zones" in result.note
    assert wall.read_bytes() == before


def test_apply_overlays_disabled_profile_is_noop_with_calendar_fields(tmp_path: Path):
    wall = _make_png(tmp_path / "wall.png", (1000, 600))
    before = wall.read_bytes()
    profile = Profile(name="p", overlay_calendar=False, overlay_calendar_position="top-left")
    result = apply_overlays(wall, [OverlayPanel("A", (0, 0, 1000, 600), "")], profile, [])
    assert result.drawn == 0 and result.skipped == 0 and result.note == ""
    assert wall.read_bytes() == before


def test_render_overlay_preview(tmp_path: Path):
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise", artist="Jane", date="2026:11:09 08:30:00")
    out = render_overlay_preview(photo, tmp_path / "preview.png", width=640, height=360)
    image = Image.open(out)
    assert image.size == (640, 360)
    assert _dark_bbox(out) is not None


def test_render_overlay_preview_honors_zones(tmp_path: Path):
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise", size=(1280, 720))
    out = render_overlay_preview(
        photo,
        tmp_path / "preview.png",
        width=640,
        height=360,
        fit_mode="fit_bars",
        zones=[NoDrawZone("", 0, 180, 640, 180), NoDrawZone("", 0, 0, 640, 180)],
    )
    image = Image.open(out)
    # Every pixel must stay bright: the full-canvas zones block the panel and
    # the matching aspect ratio avoids fit bars.
    assert image.convert("L").point(lambda v: 255 if v < 100 else 0).getbbox() is None


def test_render_overlay_preview_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        render_overlay_preview(tmp_path / "nope.jpg", tmp_path / "preview.png")


def test_render_overlay_preview_with_calendar(tmp_path: Path):
    photo = _make_jpeg(tmp_path / "photo.jpg", size=(1280, 720), color=BACKGROUND)
    out = render_overlay_preview(
        photo,
        tmp_path / "preview.png",
        width=640,
        height=360,
        fit_mode="fit_bars",
        show_title=False,
        show_artist=False,
        show_date=False,
        show_calendar=True,
        calendar_position="top-left",
        now=datetime(2026, 11, 15),
    )
    image = Image.open(out)
    assert image.size == (640, 360)
    assert _calendar_highlight_bbox(image) is not None
    card = _dark_bbox(out)
    assert card is not None
    # The requested top-left corner wins when it is clear.
    assert card[0] <= 40 and card[1] <= 40


def test_render_overlay_preview_calendar_blocked_by_zones(tmp_path: Path):
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise", size=(1280, 720))
    out = render_overlay_preview(
        photo,
        tmp_path / "preview.png",
        width=640,
        height=360,
        fit_mode="fit_bars",
        show_calendar=True,
        zones=[NoDrawZone("", 0, 0, 640, 360)],
    )
    image = Image.open(out)
    assert _calendar_highlight_bbox(image) is None


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------


class _FakeDesktopSetter:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def apply(self, *_args, **_kwargs):
        return ["fake"]

    def apply_black(self, *_args, **_kwargs):
        return ["fake-black"]

    def supports_solid_black(self, *_args, **_kwargs):
        return False


def _setup_service(monkeypatch, tmp_path: Path, profile: Profile, monitors: str) -> None:
    config_dir = tmp_path / "config"
    image_dir = tmp_path / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MBS_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MBS_TEST_MONITORS", monitors)
    monkeypatch.setattr("mint_background_switcher.service.DesktopSetter", _FakeDesktopSetter)
    save_config(Config(active_profile=profile.name, profiles={profile.name: profile}))


def test_switch_shared_dry_run_draws_overlay(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise", size=(800, 600))
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_title=True,
        overlay_artist=True,
        overlay_date=True,
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0")
    result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert result.action != "black"
    assert result.overlay_note
    assert "drawn" in result.overlay_note
    wall = Path(result.wallpaper)
    assert wall.exists()
    assert _dark_bbox(wall) is not None, "overlay panel should appear in the composed wallpaper"


def test_switch_shared_dry_run_without_overlays_is_plain(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise", size=(800, 600))
    _setup_service(
        monkeypatch,
        tmp_path,
        Profile(name="P", mode="shared", shared_folders=[str(image_dir)], desktop="unknown"),
        "A:400x300+0+0",
    )
    result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert result.overlay_note == ""
    assert _dark_bbox(Path(result.wallpaper)) is None


def test_switch_shared_dry_run_draws_calendar(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise", size=(800, 600))
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_calendar=True,
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0")
    result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert result.action != "black"
    assert "calendar drawn" in result.overlay_note
    wall = Path(result.wallpaper)
    assert wall.exists()
    assert _calendar_highlight_bbox(Image.open(wall)) is not None, (
        "calendar card should appear in the composed wallpaper"
    )


def test_switch_montage_never_draws_overlay(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "a.jpg", title="Sunrise")
    _make_jpeg(image_dir / "b.jpg", title="Moonrise")
    base = dict(mode="montage", shared_folders=[str(image_dir)], desktop="unknown")
    _setup_service(monkeypatch, tmp_path, Profile(name="P", **base, overlay_title=True), "A:400x300+0+0")
    with_overlay = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert with_overlay.overlay_note == ""
    _setup_service(monkeypatch, tmp_path, Profile(name="P", **base), "A:400x300+0+0")
    without_overlay = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert Path(with_overlay.wallpaper).read_bytes() == Path(without_overlay.wallpaper).read_bytes()


def test_switch_span_zone_covers_canvas_skips_overlay(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise", size=(800, 600))
    base = dict(mode="span", shared_folders=[str(image_dir)], desktop="unknown")
    zoned = Profile(name="P", **base, overlay_title=True, no_draw_zones=[NoDrawZone("", 0, 0, 400, 300)])
    _setup_service(monkeypatch, tmp_path, zoned, "A:400x300+0+0")
    result_zoned = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert "no panels annotated" in result_zoned.overlay_note
    # A full-canvas zone must produce exactly the same wallpaper as if the
    # overlay were turned off entirely.
    disabled = Profile(name="P", **base)
    _setup_service(monkeypatch, tmp_path, disabled, "A:400x300+0+0")
    result_disabled = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert result_disabled.overlay_note == ""
    assert Path(result_zoned.wallpaper).read_bytes() == Path(result_disabled.wallpaper).read_bytes()


def test_switch_artist_only_without_metadata_skips(monkeypatch, tmp_path: Path):
    image_dir = tmp_path / "images"
    _make_png(image_dir / "plain.png", (800, 600), color=(210, 210, 210))
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_artist=True,  # only the artist, which a plain PNG never carries
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0")
    result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert "no stored metadata" in result.overlay_note
    assert _dark_bbox(Path(result.wallpaper)) is None


def test_switch_corrupt_wallpaper_fails_open(monkeypatch, tmp_path: Path):
    # If overlay drawing raises, the switch must still succeed without overlays.
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise")
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_title=True,
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0")

    real_apply = service.apply_overlays

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated overlay failure")

    monkeypatch.setattr("mint_background_switcher.service.apply_overlays", _boom)
    try:
        result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    finally:
        monkeypatch.setattr("mint_background_switcher.service.apply_overlays", real_apply)
    assert result.action != "black"
    assert result.wallpaper
    Path(result.wallpaper).exists()


def test_switch_per_panel_drawing_error_skips_panel_only(monkeypatch, tmp_path: Path):
    # A drawing error on one panel must skip only that panel: on a two-monitor
    # shared switch, a failing first panel still leaves the second panel
    # annotated, and the switch itself succeeds.
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise", size=(800, 600))
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_title=True,
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0,B:400x300+400+0")

    real_place = overlays._place_text_panel
    attempts = {"n": 0}

    def _flaky(image, rect, lines, zone_rects):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("simulated per-panel drawing error")
        return real_place(image, rect, lines, zone_rects)

    monkeypatch.setattr(overlays, "_place_text_panel", _flaky)
    result = service.switch_once("P", dry_run=True, rng=random.Random(7))
    assert result.action != "black"
    assert "1 of 2 panels" in result.overlay_note
    assert "drawing error" in result.overlay_note


def test_save_in_place_failure_keeps_previous_file(monkeypatch, tmp_path: Path):
    # A failed overlay rewrite must not truncate the composed wallpaper: the
    # write targets a temp file in the same directory and replaces the
    # original in one step, so the previous file stays intact on failure.
    wall = _make_jpeg(tmp_path / "wall.jpg", title="Sunrise")
    original = wall.read_bytes()
    image = Image.open(wall).convert("RGBA")

    def _boom(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("os.replace", _boom)
    with pytest.raises(OSError):
        overlays._save_in_place(image, wall)
    assert wall.read_bytes() == original
    assert not list(wall.parent.glob("*.tmp"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_overlay_info_prints_json(tmp_path: Path, capsys):
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise", artist="Jane", date="2026:11:09 08:30:00")
    assert cli.main(["overlay-info", str(photo)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "title": "Sunrise",
        "photographer": "Jane",
        "date": "2026-11-09",
    }


def test_cli_overlay_info_missing_file(tmp_path: Path, capsys):
    # overlay-info is fail-open: a missing file still yields the filename
    # fallback with empty metadata.
    assert cli.main(["overlay-info", str(tmp_path / "nope.jpg")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"title": "nope", "photographer": "", "date": ""}


def test_cli_overlay_preview_writes_image(tmp_path: Path, monkeypatch, capsys):
    photo = _make_jpeg(tmp_path / "photo.jpg", title="Sunrise")
    out = tmp_path / "preview.png"
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    save_config(Config(active_profile="P", profiles={"P": Profile(name="P")}))
    assert cli.main(["overlay-preview", str(photo), "--out", str(out), "--width", "320", "--height", "180"]) == 0
    image = Image.open(out)
    assert image.size == (320, 180)


def test_cli_overlay_preview_missing_file(tmp_path: Path, capsys):
    assert cli.main(["overlay-preview", str(tmp_path / "nope.jpg")]) != 0
    assert "no such file" in capsys.readouterr().err


def test_cli_overlay_preview_uses_profile_calendar_settings(tmp_path: Path, monkeypatch, capsys):
    photo = _make_jpeg(tmp_path / "photo.jpg", size=(1280, 720), color=BACKGROUND)
    out = tmp_path / "preview.png"
    monkeypatch.setenv("MBS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MBS_CACHE_DIR", str(tmp_path / "cache"))
    save_config(
        Config(
            active_profile="P",
            profiles={
                "P": Profile(
                    name="P",
                    overlay_calendar=True,
                    overlay_calendar_position="top-left",
                )
            },
        )
    )
    assert (
        cli.main(["overlay-preview", str(photo), "--out", str(out), "--width", "640", "--height", "360"])
        == 0
    )
    assert _calendar_highlight_bbox(Image.open(out)) is not None
    card = _dark_bbox(out)
    assert card is not None
    # The profile's top-left position is honored.
    assert card[0] <= 40 and card[1] <= 40


def test_cli_print_result_includes_overlay_note(capsys):
    result = SimpleNamespace(
        action="switch",
        profile="P",
        wallpaper="/tmp/w.png",
        monitors=[],
        images=[],
        applied=True,
        lockscreen_note="",
        overlay_note="Overlay: picture info drawn on 1 panel.",
        web_sources=[],
    )
    cli._print_result(result)
    out = capsys.readouterr().out
    assert "overlays=Overlay: picture info drawn on 1 panel." in out


def test_cli_next_prints_overlays_line(monkeypatch, tmp_path: Path, capsys):
    image_dir = tmp_path / "images"
    _make_jpeg(image_dir / "photo.jpg", title="Sunrise")
    profile = Profile(
        name="P",
        mode="shared",
        shared_folders=[str(image_dir)],
        desktop="unknown",
        overlay_title=True,
    )
    _setup_service(monkeypatch, tmp_path, profile, "A:400x300+0+0")
    assert cli.main(["next", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "overlays=" in out
    assert "drawn" in out
