from datetime import date
from pathlib import Path

from PIL import Image

from mint_background_switcher import images as images_module
from mint_background_switcher.images import (
    CALENDAR_HIGHLIGHT_COLOR,
    POSTCARD_BACKGROUND_COLOR,
    POSTCARD_PIN_COLOR,
    _postcard_tile,
    add_three_month_calendar,
    apply_effect,
    compose_black,
    compose_montage,
    compose_per_monitor,
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


def test_compose_postcard_frames_four_uncropped_images_on_each_monitor(tmp_path: Path):
    colors = ((40, 180, 80), (40, 80, 220), (220, 200, 40), (40, 200, 200))
    paths = []
    for index, color in enumerate(colors):
        path = tmp_path / f"postcard-{index}.png"
        Image.new("RGB", (120, 80), color).save(path)
        paths.append(str(path))
    monitors = [Monitor("A", 240, 160, 0, 0)]

    output = compose_postcard(monitors, {"A": paths}, tmp_path / "postcard.png")

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
        pin_red, pin_green, pin_blue = POSTCARD_PIN_COLOR[:3]
        assert any(
            abs(red - pin_red) < 30 and abs(green - pin_green) < 30 and abs(blue - pin_blue) < 30
            for red, green, blue in rendered_colors
        )
        assert (248, 246, 238) in rendered_colors


def test_postcard_tile_preserves_source_edges_and_fits_ultrawide_cells(tmp_path: Path):
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
    straight_colors = {color for _count, color in straight.getcolors(maxcolors=straight.width * straight.height) or []}
    assert {(*color, 255) for color in marker_colors}.issubset(straight_colors)

    ultrawide = _postcard_tile(str(path), (1920, 540), -8.0, bar_color="black")
    assert ultrawide.width <= 1920
    assert ultrawide.height <= 540


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
