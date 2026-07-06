from pathlib import Path

from PIL import Image

from mint_background_switcher.images import compose_black, compose_per_monitor, fit_with_black_bars, scan_images
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


def test_scan_images_recursive(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "a.jpg").write_bytes(b"not-real-but-extension-counts")
    (nested / "b.png").write_bytes(b"not-real-but-extension-counts")
    assert len(scan_images([str(tmp_path)], recursive=False)) == 1
    assert len(scan_images([str(tmp_path)], recursive=True)) == 2


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
