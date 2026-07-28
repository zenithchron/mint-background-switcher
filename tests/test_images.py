from datetime import date
from pathlib import Path
import random

from PIL import Image
import pytest

from mint_background_switcher import images as images_module
from mint_background_switcher.images import (
    CALENDAR_HIGHLIGHT_COLOR,
    POLAROID_BACKGROUND_COLOR,
    POLAROID_FRAME_COLOR,
    POSTCARD_BACKGROUND_COLOR,
    _collage_tile,
    _polaroid_tile,
    _postcard_tile,
    _random_card_position,
    _random_spanning_card_position,
    add_three_month_calendar,
    apply_effect,
    compose_black,
    compose_collage,
    compose_montage,
    compose_per_monitor,
    compose_polaroid,
    compose_postcard,
    compose_span,
    fit_with_black_bars,
    is_usable_image,
    scan_images,
)
from mint_background_switcher.monitor import Monitor


def test_fit_with_black_bars_preserves_whole_wide_image():
    img = Image.new("RGB", (100, 50), (255, 0, 0))
    fitted = fit_with_black_bars(img, (200, 200))
    assert fitted.size == (200, 200)
    assert fitted.getpixel((10, 10)) == (0, 0, 0)
    assert fitted.getpixel((100, 100)) == (255, 0, 0)
    assert fitted.getpixel((10, 190)) == (0, 0, 0)


def test_fit_with_black_bars_preserves_whole_tall_image():
    img = Image.new("RGB", (50, 100), (0, 255, 0))
    fitted = fit_with_black_bars(img, (200, 200))
    assert fitted.size == (200, 200)
    assert fitted.getpixel((10, 100)) == (0, 0, 0)
    assert fitted.getpixel((100, 100)) == (0, 255, 0)
    assert fitted.getpixel((190, 100)) == (0, 0, 0)


def test_fit_with_automatic_bars_uses_image_average_color():
    img = Image.new("RGB", (100, 50), (120, 60, 30))
    fitted = fit_with_black_bars(img, (200, 200), bar_color="auto")

    assert fitted.getpixel((10, 10)) == (120, 60, 30)
    assert fitted.getpixel((100, 100)) == (120, 60, 30)
    assert fitted.getpixel((10, 190)) == (120, 60, 30)


def test_scan_images_recursive(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "a.jpg").write_bytes(b"not-real-but-extension-counts")
    (nested / "b.png").write_bytes(b"not-real-but-extension-counts")
    assert len(scan_images([str(tmp_path)], recursive=False)) == 1
    assert len(scan_images([str(tmp_path)], recursive=True)) == 2


def test_is_usable_image_rejects_files_pillow_cannot_decode(tmp_path: Path):
    valid = tmp_path / "valid.png"
    broken = tmp_path / "broken.jpg"
    Image.new("RGB", (20, 10), (12, 34, 56)).save(valid)
    broken.write_bytes(b"not a decodable image")

    assert is_usable_image(valid) is True
    assert is_usable_image(broken) is False


def test_is_usable_image_verifies_container_without_loading_pixels(monkeypatch):
    calls = []

    class ProbeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def verify(self):
            calls.append("verify")

        def load(self):
            raise AssertionError("validation decoded pixels before composition")

    monkeypatch.setattr(images_module.Image, "open", lambda _path: ProbeImage())

    assert is_usable_image("candidate.jpg") is True
    assert calls == ["verify"]


def test_apply_grayscale_effect_removes_color_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "color.png"
    Image.new("RGB", (8, 6), (200, 40, 10)).save(path)

    assert apply_effect(path, "grayscale") == path

    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.getchannel("R").tobytes() == processed.getchannel("G").tobytes()
        assert processed.getchannel("G").tobytes() == processed.getchannel("B").tobytes()


def test_apply_desaturate_effect_halves_color_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "color.png"
    source = Image.new("RGB", (2, 1))
    source.putpixel((0, 0), (200, 40, 10))
    source.putpixel((1, 0), (10, 100, 250))
    before = source.tobytes()
    source.save(path)

    assert apply_effect(path, "desaturate") == path

    assert source.tobytes() == before
    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.size == source.size
        assert processed.getpixel((0, 0)) == (142, 62, 47)
        assert processed.getpixel((1, 0)) == (50, 95, 170)
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_apply_sepia_effect_adds_warm_tone_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "color.png"
    Image.new("RGB", (8, 6), (200, 40, 10)).save(path)

    assert apply_effect(path, "sepia") == path

    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        pixel = processed.getpixel((0, 0))
        assert isinstance(pixel, tuple)
        red, green, blue = pixel[:3]
        assert red > green > blue


def test_apply_invert_effect_complements_pixels_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "color.png"
    source = Image.new("RGB", (2, 1))
    source.putpixel((0, 0), (0, 64, 255))
    source.putpixel((1, 0), (12, 34, 56))
    before = source.tobytes()
    source.save(path)

    assert apply_effect(path, "invert") == path

    assert source.tobytes() == before
    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.size == source.size
        assert processed.getpixel((0, 0)) == (255, 191, 0)
        assert processed.getpixel((1, 0)) == (243, 221, 199)
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_apply_blur_effect_softens_sharp_edges_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "edge.png"
    source = Image.new("RGB", (21, 9), (0, 0, 0))
    for x in range(11, source.width):
        for y in range(source.height):
            source.putpixel((x, y), (255, 255, 255))
    source.save(path)
    before = path.read_bytes()

    assert apply_effect(path, "blur") == path

    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        edge = processed.getpixel((10, 4))
        assert isinstance(edge, tuple)
        assert 0 < edge[0] < 255
        assert edge[0] == edge[1] == edge[2]
    assert path.read_bytes() != before


def test_apply_vignette_effect_darkens_edges_and_preserves_center(tmp_path: Path):
    path = tmp_path / "white.png"
    Image.new("RGB", (41, 41), (255, 255, 255)).save(path)

    assert apply_effect(path, "vignette") == path

    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        center = processed.getpixel((20, 20))
        corner = processed.getpixel((0, 0))
        assert isinstance(center, tuple)
        assert isinstance(corner, tuple)
        assert center[0] > 240
        assert corner[0] < center[0]
        assert corner[0] == corner[1] == corner[2]


def test_three_month_calendar_overlay_is_deterministic_and_highlights_today():
    source = Image.new("RGB", (1200, 700), (80, 120, 160))
    today = date(2026, 7, 19)

    first = add_three_month_calendar(source, today=today)
    second = add_three_month_calendar(source, today=today)

    assert first.mode == "RGB"
    assert first.size == source.size
    assert first.tobytes() == second.tobytes()
    assert first.tobytes() != source.tobytes()
    expected_highlight = CALENDAR_HIGHLIGHT_COLOR[:3]
    colors = first.getcolors(maxcolors=first.width * first.height) or []
    assert expected_highlight in {color for _count, color in colors}


def test_apply_calendar_effect_writes_overlay_to_wallpaper(tmp_path: Path):
    path = tmp_path / "calendar.png"
    Image.new("RGB", (900, 500), (120, 80, 40)).save(path)
    before = path.read_bytes()

    assert apply_effect(path, "calendar") == path

    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.size == (900, 500)
        colors = processed.getcolors(maxcolors=processed.width * processed.height) or []
        assert CALENDAR_HIGHLIGHT_COLOR[:3] in {color for _count, color in colors}
    assert path.read_bytes() != before


def test_none_effect_leaves_composite_unchanged(tmp_path: Path):
    path = tmp_path / "color.png"
    Image.new("RGB", (2, 2), (200, 40, 10)).save(path)
    before = path.read_bytes()

    assert apply_effect(path, "none") == path
    assert path.read_bytes() == before


def test_compose_montage_places_four_fitted_images_on_each_monitor(tmp_path: Path):
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
    paths = []
    for index, color in enumerate(colors):
        path = tmp_path / f"montage-{index}.png"
        Image.new("RGB", (100, 100), color).save(path)
        paths.append(str(path))
    monitors = [Monitor("A", 200, 120, 0, 0)]

    output = compose_montage(monitors, {"A": paths}, tmp_path / "montage.png")

    with Image.open(output) as montage:
        assert montage.size == (200, 120)
        assert montage.getpixel((5, 30)) == (0, 0, 0)
        assert montage.getpixel((50, 30)) == colors[0]
        assert montage.getpixel((150, 30)) == colors[1]
        assert montage.getpixel((50, 90)) == colors[2]
        assert montage.getpixel((150, 90)) == colors[3]


def test_generated_wallpaper_replaces_symlink_without_touching_its_target(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (30, 20), (220, 40, 10)).save(source)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"must remain untouched")
    working = tmp_path / "working"
    working.mkdir()
    output = working / "P-active-1.png"
    output.symlink_to(unrelated)

    result = compose_span([Monitor("A", 60, 40, 0, 0)], str(source), output)

    assert result == output
    assert not output.is_symlink()
    assert output.is_file()
    assert unrelated.read_bytes() == b"must remain untouched"
    with Image.open(output) as generated:
        assert generated.size == (60, 40)
    assert list(working.glob(f".{output.name}.*.tmp")) == []


def test_compose_collage_places_five_uncropped_images_on_each_monitor(tmp_path: Path):
    colors = ((230, 40, 50), (40, 200, 80), (50, 90, 230), (230, 190, 40), (180, 50, 210))
    paths = []
    for index, color in enumerate(colors):
        path = tmp_path / f"collage-{index}.png"
        Image.new("RGB", (120, 80), color).save(path)
        paths.append(str(path))
    source_bytes = {path: Path(path).read_bytes() for path in paths}
    monitors = [Monitor("A", 250, 160, 0, 0)]

    output = compose_collage(monitors, {"A": paths}, tmp_path / "collage.png")
    repeated = compose_collage(monitors, {"A": paths}, tmp_path / "collage-repeated.png")

    assert output.read_bytes() == repeated.read_bytes()
    assert {path: Path(path).read_bytes() for path in paths} == source_bytes
    with Image.open(output) as collage:
        assert collage.mode == "RGB"
        assert collage.size == (250, 160)
        rendered_colors = {
            color
            for _count, color in collage.getcolors(maxcolors=collage.width * collage.height) or []
            if isinstance(color, tuple) and len(color) == 3
        }
        assert set(colors).issubset(rendered_colors)
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_collage_tile_preserves_source_edges_and_fits_ultrawide_cells(tmp_path: Path):
    source = Image.new("RGB", (120, 80), (90, 90, 90))
    marker_colors = ((250, 20, 20), (20, 250, 20), (20, 20, 250), (250, 220, 20))
    marker_boxes = ((0, 0, 11, 11), (108, 0, 119, 11), (0, 68, 11, 79), (108, 68, 119, 79))
    for color, (left, top, right, bottom) in zip(marker_colors, marker_boxes):
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                source.putpixel((x, y), color)
    path = tmp_path / "collage-edge-markers.png"
    source.save(path)

    standard = _collage_tile(str(path), (240, 160), bar_color="black")
    standard_colors = {
        color for _count, color in standard.getcolors(maxcolors=standard.width * standard.height) or []
    }
    assert set(marker_colors).issubset(standard_colors)

    ultrawide = _collage_tile(str(path), (1920, 540), bar_color="black")
    assert ultrawide.size == (1920, 540)
    ultrawide_colors = {
        color for _count, color in ultrawide.getcolors(maxcolors=ultrawide.width * ultrawide.height) or []
    }
    assert set(marker_colors).issubset(ultrawide_colors)


def test_collage_tile_rejects_pillow_decompression_bomb_warnings(monkeypatch, tmp_path: Path):
    path = tmp_path / "oversized-for-test.png"
    Image.new("RGB", (15, 10), (20, 40, 60)).save(path)
    monkeypatch.setattr(images_module.Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(images_module.ImageDecodeError):
        _collage_tile(str(path), (30, 20), bar_color="black")


def test_compose_postcard_randomizes_bare_uncropped_images_without_frames_or_pins(tmp_path: Path):
    legacy_pin_color = (188, 42, 42)
    colors = ((40, 180, 80), (40, 80, 220), (220, 200, 40), (40, 200, 200))
    paths = []
    for index, color in enumerate(colors):
        path = tmp_path / f"postcard-{index}.png"
        Image.new("RGB", (120, 80), color).save(path)
        paths.append(str(path))
    monitors = [Monitor("A", 240, 160, 0, 0)]

    source_bytes = {path: Path(path).read_bytes() for path in paths}
    output = compose_postcard(monitors, {"A": paths}, tmp_path / "postcard.png", rng=random.Random(13))
    repeated = compose_postcard(
        monitors,
        {"A": paths},
        tmp_path / "postcard-repeated.png",
        rng=random.Random(13),
    )
    moved = compose_postcard(
        monitors,
        {"A": paths},
        tmp_path / "postcard-moved.png",
        rng=random.Random(14),
    )

    assert output.read_bytes() == repeated.read_bytes()
    assert output.read_bytes() != moved.read_bytes()
    assert {path: Path(path).read_bytes() for path in paths} == source_bytes
    with Image.open(output) as postcard:
        assert postcard.mode == "RGB"
        assert postcard.size == (240, 160)
        assert postcard.getpixel((0, 0)) == POSTCARD_BACKGROUND_COLOR
        rendered_colors = {
            color
            for _count, color in postcard.getcolors(maxcolors=postcard.width * postcard.height) or []
            if isinstance(color, tuple) and len(color) == 3
        }
        assert set(colors).issubset(rendered_colors)
        assert legacy_pin_color not in rendered_colors
        assert POLAROID_FRAME_COLOR[:3] not in rendered_colors


def test_postcard_tile_preserves_source_edges_and_fits_ultrawide_cells(tmp_path: Path):
    legacy_pin_color = (188, 42, 42, 255)
    source = Image.new("RGB", (120, 80), (90, 90, 90))
    marker_colors = ((250, 20, 20), (20, 250, 20), (20, 20, 250), (250, 220, 20))
    marker_boxes = ((0, 0, 11, 11), (108, 0, 119, 11), (0, 68, 11, 79), (108, 68, 119, 79))
    for color, (left, top, right, bottom) in zip(marker_colors, marker_boxes):
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                source.putpixel((x, y), color)
    path = tmp_path / "edge-markers.png"
    source.save(path)

    straight = _postcard_tile(str(path), (240, 160), 0.0, bar_color="black")
    assert straight.size == (240, 160)
    straight_colors = {color for _count, color in straight.getcolors(maxcolors=straight.width * straight.height) or []}
    assert {(*color, 255) for color in marker_colors}.issubset(straight_colors)
    assert legacy_pin_color not in straight_colors
    assert POLAROID_FRAME_COLOR not in straight_colors

    ultrawide = _postcard_tile(str(path), (1920, 540), -8.0, bar_color="black")
    assert ultrawide.width <= 1920
    assert ultrawide.height <= 540


def test_compose_polaroid_frames_four_uncropped_images_on_each_monitor(tmp_path: Path):
    colors = ((210, 50, 60), (50, 190, 90), (60, 90, 220), (220, 180, 40))
    paths = []
    for index, color in enumerate(colors):
        path = tmp_path / f"polaroid-{index}.png"
        Image.new("RGB", (120, 80), color).save(path)
        paths.append(str(path))
    source_bytes = {path: Path(path).read_bytes() for path in paths}
    monitors = [Monitor("A", 240, 160, 0, 0)]

    output = compose_polaroid(monitors, {"A": paths}, tmp_path / "polaroid.png", rng=random.Random(13))
    repeated = compose_polaroid(
        monitors,
        {"A": paths},
        tmp_path / "polaroid-repeated.png",
        rng=random.Random(13),
    )
    moved = compose_polaroid(monitors, {"A": paths}, tmp_path / "polaroid-moved.png", rng=random.Random(14))

    assert output.read_bytes() == repeated.read_bytes()
    assert output.read_bytes() != moved.read_bytes()
    assert {path: Path(path).read_bytes() for path in paths} == source_bytes
    with Image.open(output) as polaroid:
        assert polaroid.mode == "RGB"
        assert polaroid.size == (240, 160)
        assert polaroid.getpixel((0, 0)) == POLAROID_BACKGROUND_COLOR
        rendered_colors = {
            color
            for _count, color in polaroid.getcolors(maxcolors=polaroid.width * polaroid.height) or []
            if isinstance(color, tuple) and len(color) == 3
        }
        assert set(colors).issubset(rendered_colors)
        assert POLAROID_FRAME_COLOR[:3] in rendered_colors
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_polaroid_tile_preserves_source_edges_and_fits_ultrawide_cells(tmp_path: Path):
    source = Image.new("RGB", (120, 80), (90, 90, 90))
    marker_colors = ((250, 20, 20), (20, 250, 20), (20, 20, 250), (250, 220, 20))
    marker_boxes = ((0, 0, 11, 11), (108, 0, 119, 11), (0, 68, 11, 79), (108, 68, 119, 79))
    for color, (left, top, right, bottom) in zip(marker_colors, marker_boxes):
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                source.putpixel((x, y), color)
    path = tmp_path / "polaroid-edge-markers.png"
    source.save(path)

    straight = _polaroid_tile(str(path), (240, 160), 0.0, bar_color="black")
    straight_colors = {color for _count, color in straight.getcolors(maxcolors=straight.width * straight.height) or []}
    assert {(*color, 255) for color in marker_colors}.issubset(straight_colors)
    assert (0, 0, 0, 255) not in straight_colors

    ultrawide = _polaroid_tile(str(path), (1920, 540), 7.0, bar_color="black")
    assert ultrawide.width <= 1920
    assert ultrawide.height <= 540


def test_random_polaroid_positions_vary_and_keep_cards_fully_visible():
    rng = random.Random(29)
    positions = [_random_card_position((1920, 1080), (640, 480), rng) for _index in range(20)]

    assert len(set(positions)) > 1
    assert all(0 <= x <= 1280 and 0 <= y <= 600 for x, y in positions)


def test_random_spanning_positions_keep_centers_visible_but_allow_clipping():
    rng = random.Random(31)
    positions = [_random_spanning_card_position((1920, 1080), (640, 480), rng) for _index in range(100)]

    assert len(set(positions)) > 1
    assert all(0 <= x + 320 <= 1920 and 0 <= y + 240 <= 1080 for x, y in positions)
    assert any(x < 0 or y < 0 or x + 640 > 1920 or y + 480 > 1080 for x, y in positions)


def test_polaroid_span_allows_outer_clipping_and_monitor_crossing(monkeypatch, tmp_path: Path):
    colors = {"outer": (210, 50, 60, 255), "crossing": (60, 90, 220, 255)}
    positions = iter([(-20, 10), (80, 40)])
    anchor_rects = []

    class FixedRng:
        @staticmethod
        def uniform(_low, _high):
            return 0.0

        @staticmethod
        def shuffle(_items):
            return None

    monkeypatch.setattr(
        images_module,
        "_polaroid_tile",
        lambda image_path, _size, _angle, **_kwargs: Image.new("RGBA", (40, 40), colors[image_path]),
    )

    def fixed_position(*_args, anchor_rect=None, **_kwargs):
        anchor_rects.append(anchor_rect)
        return next(positions)

    monkeypatch.setattr(images_module, "_random_spanning_card_position", fixed_position)
    monitors = [Monitor("A", 100, 100, 0, 0), Monitor("B", 100, 100, 100, 0)]

    output = compose_polaroid(
        monitors,
        {"A": ["outer", "crossing"]},
        tmp_path / "spanning.png",
        span=True,
        rng=FixedRng(),
    )

    with Image.open(output) as wallpaper:
        assert wallpaper.size == (200, 100)
        assert wallpaper.getpixel((0, 20)) == colors["outer"][:3]
        assert wallpaper.getpixel((99, 50)) == colors["crossing"][:3]
        assert wallpaper.getpixel((100, 50)) == colors["crossing"][:3]
    assert anchor_rects == [(0, 0, 100, 100), (100, 0, 100, 100)]


def test_polaroid_span_is_reproducible_with_injected_rng(tmp_path: Path):
    paths = []
    for index, color in enumerate(((210, 50, 60), (50, 190, 90), (60, 90, 220), (220, 180, 40))):
        path = tmp_path / f"span-{index}.png"
        Image.new("RGB", (120 + index * 20, 80 + index * 10), color).save(path)
        paths.append(str(path))
    monitors = [Monitor("A", 240, 160, 0, 0), Monitor("B", 240, 160, 240, 0)]

    first = compose_polaroid(
        monitors,
        {"A": paths},
        tmp_path / "span-first.png",
        span=True,
        rng=random.Random(41),
    )
    repeated = compose_polaroid(
        monitors,
        {"A": paths},
        tmp_path / "span-repeated.png",
        span=True,
        rng=random.Random(41),
    )
    moved = compose_polaroid(
        monitors,
        {"A": paths},
        tmp_path / "span-moved.png",
        span=True,
        rng=random.Random(42),
    )

    assert first.read_bytes() == repeated.read_bytes()
    assert first.read_bytes() != moved.read_bytes()


def test_polaroid_size_setting_measurably_changes_print_size(tmp_path: Path):
    source = tmp_path / "red-square.png"
    Image.new("RGB", (100, 100), (220, 30, 30)).save(source)
    monitors = [Monitor("A", 400, 300, 0, 0)]
    images = {"A": [str(source)]}

    small_path = compose_polaroid(monitors, images, tmp_path / "small.png", size=0.0, rng=random.Random(7))
    large_path = compose_polaroid(monitors, images, tmp_path / "large.png", size=1.0, rng=random.Random(7))

    with Image.open(small_path) as small, Image.open(large_path) as large:
        background = (39, 44, 52)
        small_pixels = small.load()
        large_pixels = large.load()
        assert small_pixels is not None
        assert large_pixels is not None
        small_print_pixels = sum(
            small_pixels[x, y] != background for y in range(small.height) for x in range(small.width)
        )
        large_print_pixels = sum(
            large_pixels[x, y] != background for y in range(large.height) for x in range(large.width)
        )
        assert small.size == large.size == (400, 300)
        assert large_print_pixels > small_print_pixels * 2


def test_compose_per_monitor_and_black(tmp_path: Path):
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    Image.new("RGB", (100, 50), (255, 0, 0)).save(red)
    Image.new("RGB", (50, 100), (0, 0, 255)).save(blue)
    monitors = [Monitor("A", 200, 200, 0, 0), Monitor("B", 100, 200, 200, 0)]
    out = compose_per_monitor(monitors, {"A": str(red), "B": str(blue)}, tmp_path / "wall.png")
    composite = Image.open(out)
    assert composite.size == (300, 200)
    assert composite.getpixel((10, 10)) == (0, 0, 0)
    assert composite.getpixel((100, 100)) == (255, 0, 0)
    assert composite.getpixel((250, 100)) == (0, 0, 255)
    black = compose_black(monitors, tmp_path / "black.png")
    black_img = Image.open(black)
    assert black_img.size == (300, 200)
    assert black_img.getpixel((299, 199)) == (0, 0, 0)
