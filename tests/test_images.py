from datetime import date
import os
from pathlib import Path
import random
import subprocess
import sys

from PIL import Image, ImageChops, ImageStat
import pytest

from mint_background_switcher import images as images_module
from mint_background_switcher.config import POSTCARD_BACKGROUND_CHOICES, RANDOM_EFFECT_CHOICES
from mint_background_switcher.images import (
    CALENDAR_HIGHLIGHT_COLOR,
    POLAROID_BACKGROUND_COLOR,
    POLAROID_FRAME_COLOR,
    POSTCARD_BACKGROUND_COLORS,
    POSTCARD_BACKGROUND_COLOR,
    POSTCARD_CORKBOARD_COLOR,
    _collage_tile,
    _corkboard_texture,
    _polaroid_tile,
    _postcard_tile,
    _procedural_surface_texture,
    _procedural_surface_work_size,
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


PROCEDURAL_SURFACES = tuple(POSTCARD_BACKGROUND_COLORS)[2:]
TEXTURED_BACKGROUNDS = tuple(POSTCARD_BACKGROUND_COLORS)[1:]


def test_postcard_config_and_renderer_background_choices_match():
    assert tuple(POSTCARD_BACKGROUND_COLORS) == POSTCARD_BACKGROUND_CHOICES
    expected_procedural = frozenset(POSTCARD_BACKGROUND_CHOICES[2:])
    assert images_module._PROCEDURAL_SURFACE_STYLES == expected_procedural
    assert set(images_module._SURFACE_STYLE_SEEDS) == expected_procedural
    assert set(images_module._SURFACE_NOISE_RECIPES) == expected_procedural
    assert set(images_module._SURFACE_DETAIL_RENDERERS) == expected_procedural
    assert all(
        len(color) == 3 and all(isinstance(channel, int) and 0 <= channel <= 255 for channel in color)
        for color in POSTCARD_BACKGROUND_COLORS.values()
    )


def test_procedural_surface_work_size_is_bounded():
    assert _procedural_surface_work_size(11520, 2160) == (5760, 1080)
    for width, height in ((20000, 10000), (100000, 100), (3840, 6480)):
        work_width, work_height = _procedural_surface_work_size(width, height)
        assert work_width * work_height <= images_module._PROCEDURAL_SURFACE_MAX_WORK_PIXELS
        assert 1 <= work_width <= width
        assert 1 <= work_height <= height


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


def test_fit_with_blurred_edges_keeps_the_whole_foreground_and_does_not_mutate_source():
    source = Image.new("RGB", (100, 50), (240, 20, 20))
    for x in range(50, source.width):
        for y in range(source.height):
            source.putpixel((x, y), (20, 20, 240))
    before = source.tobytes()

    fitted = fit_with_black_bars(source, (100, 100), bar_color="blurred")

    assert source.tobytes() == before
    assert fitted.mode == "RGB"
    assert fitted.size == (100, 100)
    assert fitted.getpixel((0, 50)) == (240, 20, 20)
    assert fitted.getpixel((99, 50)) == (20, 20, 240)
    blurred_seam = fitted.getpixel((50, 5))
    assert isinstance(blurred_seam, tuple)
    assert blurred_seam[0] > 20
    assert blurred_seam[2] > 20
    assert blurred_seam != fitted.getpixel((50, 50))


def test_scan_images_recursive(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "a.jpg").write_bytes(b"not-real-but-extension-counts")
    (nested / "b.png").write_bytes(b"not-real-but-extension-counts")
    assert len(scan_images([str(tmp_path)], recursive=False)) == 1
    assert len(scan_images([str(tmp_path)], recursive=True)) == 2


def test_scan_images_accepts_an_individual_picture_source(tmp_path: Path):
    picture = tmp_path / "individual.PNG"
    picture.write_bytes(b"extension is sufficient for discovery")

    assert scan_images([str(picture)], recursive=False) == [str(picture.resolve())]


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


def test_apply_saturate_effect_boosts_color_and_preserves_rgb(tmp_path: Path):
    path = tmp_path / "color.png"
    source = Image.new("RGB", (3, 1))
    source.putpixel((0, 0), (200, 40, 10))
    source.putpixel((1, 0), (10, 100, 250))
    source.putpixel((2, 0), (128, 128, 128))
    before = source.tobytes()
    source.save(path)

    assert apply_effect(path, "saturate") == path

    assert source.tobytes() == before
    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.size == source.size
        assert processed.getpixel((0, 0)) == (255, 18, 0)
        assert processed.getpixel((1, 0)) == (0, 105, 255)
        assert processed.getpixel((2, 0)) == (128, 128, 128)
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_apply_random_effect_selects_one_concrete_effect(tmp_path: Path):
    class InvertRandom(random.Random):
        def choice(self, seq):
            assert tuple(seq[index] for index in range(len(seq))) == RANDOM_EFFECT_CHOICES
            return "invert"

    path = tmp_path / "random.png"
    expected_path = tmp_path / "expected.png"
    source = Image.new("RGB", (3, 1))
    source.putpixel((0, 0), (0, 64, 255))
    source.putpixel((1, 0), (12, 34, 56))
    source.putpixel((2, 0), (128, 128, 128))
    before = source.tobytes()
    source.save(path)
    source.save(expected_path)

    assert apply_effect(path, "random", rng=InvertRandom()) == path
    assert apply_effect(expected_path, "invert") == expected_path

    assert source.tobytes() == before
    assert path.read_bytes() == expected_path.read_bytes()
    with Image.open(path) as processed:
        assert processed.mode == "RGB"
        assert processed.size == source.size
        assert processed.getpixel((0, 0)) == (255, 191, 0)
        assert processed.getpixel((1, 0)) == (243, 221, 199)
        assert processed.getpixel((2, 0)) == (127, 127, 127)
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


def test_corkboard_texture_is_deterministic_non_flat_and_subtle():
    first = _corkboard_texture((240, 160), seed=7)
    repeated = _corkboard_texture((240, 160), seed=7)
    changed_seed = _corkboard_texture((240, 160), seed=8)

    assert first.mode == "RGB"
    assert first.size == (240, 160)
    assert first.tobytes() == repeated.tobytes()
    assert first.tobytes() != changed_seed.tobytes()
    colors = first.getcolors(maxcolors=first.width * first.height)
    assert colors is not None
    assert len(colors) > 20
    means = ImageStat.Stat(first).mean
    assert isinstance(means, list)
    for mean, base in zip(means, POSTCARD_CORKBOARD_COLOR):
        assert abs(mean - base) < 4
    for (low, high), base in zip(first.getextrema(), POSTCARD_CORKBOARD_COLOR):
        assert base - 50 <= low < base
        assert base < high <= base + 24


@pytest.mark.parametrize("style", PROCEDURAL_SURFACES)
def test_procedural_surface_is_deterministic_non_flat_and_subtle(style: str):
    first = _procedural_surface_texture((240, 160), style, seed=7)
    repeated = _procedural_surface_texture((240, 160), style, seed=7)
    changed_seed = _procedural_surface_texture((240, 160), style, seed=8)

    assert first.mode == "RGB"
    assert first.size == (240, 160)
    assert first.tobytes() == repeated.tobytes()
    assert first.tobytes() != changed_seed.tobytes()
    colors = first.getcolors(maxcolors=first.width * first.height)
    assert colors is not None
    assert len(colors) >= 10
    statistics = ImageStat.Stat(first)
    means = statistics.mean
    standard_deviations = statistics.stddev
    assert isinstance(means, list)
    assert isinstance(standard_deviations, list)
    assert min(standard_deviations) > 1.25
    for mean, base in zip(means, POSTCARD_BACKGROUND_COLORS[style]):
        assert abs(mean - base) < 6


@pytest.mark.parametrize("style", PROCEDURAL_SURFACES)
@pytest.mark.parametrize("size", [(1, 1), (17, 9), (241, 161)])
def test_procedural_surface_supports_edge_and_odd_sizes(style: str, size: tuple[int, int]):
    first = _procedural_surface_texture(size, style, seed=23)
    repeated = _procedural_surface_texture(size, style, seed=23)

    assert first.mode == "RGB"
    assert first.size == size
    assert first.tobytes() == repeated.tobytes()


def test_procedural_surfaces_are_cross_process_deterministic_across_hash_seeds():
    code = f"""
import hashlib
from mint_background_switcher.images import _procedural_surface_texture
styles = {PROCEDURAL_SURFACES!r}
print('|'.join(hashlib.sha256(_procedural_surface_texture((137, 83), style, seed=29).tobytes()).hexdigest() for style in styles))
"""
    outputs = []
    for hash_seed in ("1", "8675309"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = hash_seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", code],
                env=environment,
                text=True,
            ).strip()
        )

    assert outputs[0] == outputs[1]


def test_procedural_surfaces_do_not_consume_global_random_state():
    original_state = random.getstate()
    for style in PROCEDURAL_SURFACES:
        surface = _procedural_surface_texture((137, 83), style, seed=31)
        surface.close()
    assert random.getstate() == original_state


def test_all_procedural_surfaces_have_distinct_pixels():
    rendered = {
        style: _procedural_surface_texture((160, 100), style, seed=7).tobytes()
        for style in PROCEDURAL_SURFACES
    }

    assert len(set(rendered.values())) == len(PROCEDURAL_SURFACES)


def test_procedural_surfaces_retain_material_specific_structure():
    rendered = {
        style: _procedural_surface_texture((600, 320), style, seed=17)
        for style in PROCEDURAL_SURFACES
    }

    def directional_difference(image: Image.Image) -> tuple[float, float]:
        luminance = image.convert("L")
        horizontal = ImageChops.difference(
            luminance.crop((1, 0, image.width, image.height)),
            luminance.crop((0, 0, image.width - 1, image.height)),
        )
        vertical = ImageChops.difference(
            luminance.crop((0, 1, image.width, image.height)),
            luminance.crop((0, 0, image.width, image.height - 1)),
        )
        return ImageStat.Stat(horizontal).mean[0], ImageStat.Stat(vertical).mean[0]

    def count_outliers(style: str, threshold: int) -> int:
        image = rendered[style]
        base = POSTCARD_BACKGROUND_COLORS[style]
        pixels = image.tobytes()
        return sum(
            max(
                abs(pixels[index] - base[0]),
                abs(pixels[index + 1] - base[1]),
                abs(pixels[index + 2] - base[2]),
            )
            >= threshold
            for index in range(0, len(pixels), 3)
        )

    linen_dx, linen_dy = directional_difference(rendered["linen"])
    metal_dx, metal_dy = directional_difference(rendered["brushed metal"])
    slate_dx, slate_dy = directional_difference(rendered["slate"])
    sandstone_dx, sandstone_dy = directional_difference(rendered["sandstone"])

    assert linen_dx > 2.0 and linen_dy > 2.0
    assert 0.8 < linen_dx / linen_dy < 1.25
    assert metal_dy > metal_dx * 10
    assert slate_dy > slate_dx * 1.2
    assert sandstone_dy > sandstone_dx * 1.05
    assert 800 < count_outliers("felt", 6) < 5000
    assert 200 < count_outliers("kraft paper", 16) < 2000
    assert 50 < count_outliers("watercolor paper", 10) < 1000
    assert 20 < count_outliers("plaster", 16) < 500
    assert 50 < count_outliers("concrete", 24) < 1000
    assert 600 < count_outliers("terrazzo", 24) < 10000

    for image in rendered.values():
        image.close()


@pytest.mark.parametrize("span", [False, True])
def test_postcard_corkboard_background_textures_each_layout(span: bool, tmp_path: Path):
    monitors = [Monitor("A", 120, 80, 0, 0)]

    output = compose_postcard(
        monitors,
        {"A": []},
        tmp_path / f"corkboard-{span}.png",
        span=span,
        background="corkboard",
        rng=random.Random(13),
    )
    repeated = compose_postcard(
        monitors,
        {"A": []},
        tmp_path / f"corkboard-repeated-{span}.png",
        span=span,
        background="corkboard",
        rng=random.Random(99),
    )

    assert output.read_bytes() == repeated.read_bytes()
    with Image.open(output) as postcard:
        colors = postcard.getcolors(maxcolors=postcard.width * postcard.height)
        assert colors is not None
        assert len(colors) > 16


@pytest.mark.parametrize("background", PROCEDURAL_SURFACES)
@pytest.mark.parametrize("span", [False, True])
def test_postcard_procedural_background_textures_each_layout(
    background: str,
    span: bool,
    tmp_path: Path,
):
    monitors = [Monitor("A", 120, 80, 0, 0)]

    output = compose_postcard(
        monitors,
        {"A": []},
        tmp_path / f"surface-{background}-{span}.png",
        span=span,
        background=background,
        rng=random.Random(13),
    )
    repeated = compose_postcard(
        monitors,
        {"A": []},
        tmp_path / f"surface-repeated-{background}-{span}.png",
        span=span,
        background=background,
        rng=random.Random(99),
    )

    assert output.read_bytes() == repeated.read_bytes()
    with Image.open(output) as postcard:
        colors = postcard.getcolors(maxcolors=postcard.width * postcard.height)
        assert colors is not None
        assert len(colors) >= 10


@pytest.mark.parametrize("span", [False, True])
def test_postcard_dark_background_remains_a_solid_fill(span: bool, tmp_path: Path):
    output = compose_postcard(
        [Monitor("A", 120, 80, 0, 0)],
        {"A": []},
        tmp_path / f"dark-{span}.png",
        span=span,
        background="dark",
    )

    with Image.open(output) as postcard:
        assert postcard.getcolors(maxcolors=postcard.width * postcard.height) == [
            (postcard.width * postcard.height, POSTCARD_BACKGROUND_COLOR)
        ]


@pytest.mark.parametrize("background", TEXTURED_BACKGROUNDS)
def test_per_screen_textured_panels_do_not_repeat_the_same_texture(background: str, tmp_path: Path):
    output = compose_postcard(
        [Monitor("A", 120, 80, 0, 0), Monitor("B", 120, 80, 120, 0)],
        {"A": [], "B": []},
        tmp_path / f"two-{background}-panels.png",
        background=background,
    )

    with Image.open(output) as postcard:
        first_panel = postcard.crop((0, 0, 120, 80))
        second_panel = postcard.crop((120, 0, 240, 80))
        assert first_panel.tobytes() != second_panel.tobytes()


@pytest.mark.parametrize("background", TEXTURED_BACKGROUNDS)
@pytest.mark.parametrize("span", [False, True])
@pytest.mark.parametrize("tilt", [False, True])
def test_postcard_textures_do_not_consume_photo_rng_or_change_geometry(
    monkeypatch,
    tmp_path: Path,
    background: str,
    span: bool,
    tilt: bool,
):
    colors = {"a": (244, 21, 37, 255), "b": (18, 67, 241, 255)}

    def fake_postcard_tile(image_path, _cell_size, _angle, *, bar_color):
        assert bar_color == "black"
        return Image.new("RGBA", (23, 17), colors[image_path])

    monkeypatch.setattr(images_module, "_postcard_tile", fake_postcard_tile)
    monitors = [Monitor("A", 120, 80, 0, 0), Monitor("B", 100, 80, 120, 0)]
    image_map = {"A": ["a", "b"], "B": ["a", "b"]}

    dark_rng = random.Random(47)
    dark_path = compose_postcard(
        monitors,
        image_map,
        tmp_path / f"dark-geometry-{span}.png",
        background="dark",
        span=span,
        tilt=tilt,
        rng=dark_rng,
    )
    textured_rng = random.Random(47)
    textured_path = compose_postcard(
        monitors,
        image_map,
        tmp_path / f"{background}-geometry-{span}.png",
        background=background,
        span=span,
        tilt=tilt,
        rng=textured_rng,
    )

    assert textured_rng.getstate() == dark_rng.getstate()
    with Image.open(dark_path) as dark, Image.open(textured_path) as textured:
        for color in colors.values():
            rgb = color[:3]
            dark_mask = {
                (x, y)
                for y in range(dark.height)
                for x in range(dark.width)
                if dark.getpixel((x, y)) == rgb
            }
            textured_mask = {
                (x, y)
                for y in range(textured.height)
                for x in range(textured.width)
                if textured.getpixel((x, y)) == rgb
            }
            assert textured_mask == dark_mask


def test_postcard_rejects_unknown_background(tmp_path: Path):
    output = tmp_path / "unknown-background.png"
    output.write_bytes(b"existing output")
    with pytest.raises(ValueError, match="Unsupported Postcard background"):
        compose_postcard(
            [Monitor("A", 120, 80, 0, 0)],
            {"A": []},
            output,
            background="not-a-style",
        )
    assert output.read_bytes() == b"existing output"


@pytest.mark.parametrize("background", ["linen", "terrazzo"])
@pytest.mark.parametrize("span", [False, True])
def test_postcard_textures_preserve_negative_origin_mixed_monitor_bounds(
    background: str,
    span: bool,
    tmp_path: Path,
):
    monitors = [
        Monitor("A", 120, 80, -120, -40),
        Monitor("B", 80, 100, 0, -20),
    ]
    output = compose_postcard(
        monitors,
        {"A": [], "B": []},
        tmp_path / f"mixed-geometry-{background}-{span}.png",
        background=background,
        span=span,
    )

    with Image.open(output) as wallpaper:
        assert wallpaper.mode == "RGB"
        assert wallpaper.size == (200, 120)


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


@pytest.mark.parametrize("span", [False, True])
def test_postcard_tilt_can_be_disabled_for_straight_photos(monkeypatch, tmp_path: Path, span: bool):
    angles = []

    class NoTiltRng(random.Random):
        def __init__(self, x=None):
            super().__init__(x)
            self.position_draws = 0

        def uniform(self, a, b):
            del a, b
            raise AssertionError("straight photos must not generate random angles")

        def randint(self, a, b):
            self.position_draws += 1
            return super().randint(a, b)

    def fake_postcard_tile(image_path, _cell_size, angle, *, bar_color):
        assert image_path in {"a", "b", "c", "d"}
        assert bar_color == "black"
        angles.append(angle)
        return Image.new("RGBA", (20, 20), (60, 90, 220, 255))

    monkeypatch.setattr(images_module, "_postcard_tile", fake_postcard_tile)
    monitors = [Monitor("A", 100, 80, 0, 0), Monitor("B", 120, 80, 100, 0)]
    rng = NoTiltRng(17)

    output = compose_postcard(
        monitors,
        {"A": ["a", "b"], "B": ["c", "d"]},
        tmp_path / f"straight-postcard-{span}.png",
        span=span,
        tilt=False,
        rng=rng,
    )

    assert angles == [0.0, 0.0, 0.0, 0.0]
    assert rng.position_draws == 8
    with Image.open(output) as wallpaper:
        assert wallpaper.size == (220, 80)


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


@pytest.mark.parametrize("span", [False, True])
def test_polaroid_tilt_can_be_disabled_for_straight_prints(monkeypatch, tmp_path: Path, span: bool):
    angles = []

    class NoTiltRng(random.Random):
        def __init__(self, x=None):
            super().__init__(x)
            self.position_draws = 0

        def uniform(self, a, b):
            del a, b
            raise AssertionError("straight prints must not generate random angles")

        def randint(self, a, b):
            self.position_draws += 1
            return super().randint(a, b)

    def fake_polaroid_tile(image_path, _cell_size, angle, *, bar_color):
        assert image_path in {"a", "b", "c", "d"}
        assert bar_color == "black"
        angles.append(angle)
        return Image.new("RGBA", (20, 20), (248, 246, 238, 255))

    monkeypatch.setattr(images_module, "_polaroid_tile", fake_polaroid_tile)
    monitors = [Monitor("A", 100, 80, 0, 0), Monitor("B", 120, 80, 100, 0)]
    rng = NoTiltRng(17)

    output = compose_polaroid(
        monitors,
        {"A": ["a", "b"], "B": ["c", "d"]},
        tmp_path / f"straight-{span}.png",
        span=span,
        tilt=False,
        rng=rng,
    )

    assert angles == [0.0, 0.0, 0.0, 0.0]
    assert rng.position_draws == 8
    with Image.open(output) as wallpaper:
        assert wallpaper.size == (220, 80)


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
