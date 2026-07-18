from pathlib import Path

from PIL import Image

from mint_background_switcher.images import apply_effect, compose_black, compose_per_monitor, fit_with_black_bars, scan_images
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


def test_none_effect_leaves_composite_unchanged(tmp_path: Path):
    path = tmp_path / "color.png"
    Image.new("RGB", (2, 2), (200, 40, 10)).save(path)
    before = path.read_bytes()

    assert apply_effect(path, "none") == path
    assert path.read_bytes() == before


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
