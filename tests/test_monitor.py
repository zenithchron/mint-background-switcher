from mint_background_switcher.monitor import parse_test_monitors, parse_xrandr, virtual_canvas, normalized_position


def test_parse_xrandr_three_monitors():
    out = """
DP-1 connected primary 2560x1440+1920+0 (normal left inverted right x axis y axis) 600mm x 340mm
HDMI-1 connected 1920x1080+0+180 (normal left inverted right x axis y axis) 530mm x 300mm
DP-2 connected 1920x1080+4480+180 (normal left inverted right x axis y axis) 530mm x 300mm
HDMI-2 disconnected (normal left inverted right x axis y axis)
"""
    monitors = parse_xrandr(out)
    assert [m.name for m in monitors] == ["HDMI-1", "DP-1", "DP-2"]
    assert monitors[1].primary is True
    assert virtual_canvas(monitors) == (6400, 1440, 0, 0)


def test_parse_xrandr_cinnamon_150_percent_scale_uses_physical_pixels():
    out = """
Screen 0: minimum 320 x 200, current 7680 x 1440, maximum 16384 x 16384
DP-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160     60.00*+
DP-2 connected 2560x1440+2560+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160     60.00*+
DP-3 connected 2560x1440+5120+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160     60.00*+
"""
    monitors = parse_xrandr(out)
    assert [(m.name, m.width, m.height, m.x, m.y, m.scale) for m in monitors] == [
        ("DP-1", 3840, 2160, 0, 0, 1.5),
        ("DP-2", 3840, 2160, 3840, 0, 1.5),
        ("DP-3", 3840, 2160, 7680, 0, 1.5),
    ]
    assert monitors[0].logical_geometry == (0, 0, 2560, 1440)
    assert virtual_canvas(monitors) == (11520, 2160, 0, 0)


def test_parse_xrandr_75_percent_scale_uses_physical_pixels():
    out = """
DP-1 connected 5120x2880+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160     60.00*+
"""
    monitors = parse_xrandr(out)
    assert [(m.width, m.height, m.x, m.y, m.scale) for m in monitors] == [(3840, 2160, 0, 0, 0.75)]
    assert monitors[0].logical_geometry == (0, 0, 5120, 2880)


def test_parse_xrandr_mixed_scale_layout_keeps_panels_adjacent():
    out = """
DP-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160     60.00*+
HDMI-1 connected 1920x1080+2560+360 (normal left inverted right x axis y axis) 530mm x 300mm
   1920x1080     60.00*+
"""
    monitors = parse_xrandr(out)
    assert [(m.name, m.width, m.height, m.x, m.y, m.scale) for m in monitors] == [
        ("DP-1", 3840, 2160, 0, 0, 1.5),
        ("HDMI-1", 1920, 1080, 3840, 360, 1.0),
    ]
    assert virtual_canvas(monitors) == (5760, 2160, 0, 0)


def test_parse_xrandr_grid_mixed_scale_uses_row_local_x_mapping():
    monitors = parse_test_monitors(
        "TopHi:100x100+0+0@200%,Bottom:100x100+0+100@100%,BottomRight:100x100+100+100@100%"
    )
    assert [(m.name, m.width, m.height, m.x, m.y, m.scale) for m in monitors] == [
        ("TopHi", 200, 200, 0, 0, 2.0),
        ("Bottom", 100, 100, 0, 200, 1.0),
        ("BottomRight", 100, 100, 100, 200, 1.0),
    ]
    assert virtual_canvas(monitors) == (200, 300, 0, 0)


def test_parse_xrandr_scaled_suffixed_mode_name():
    out = """
DP-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   3840x2160_60.00     60.00*+
"""
    monitor = parse_xrandr(out)[0]
    assert (monitor.width, monitor.height, monitor.scale) == (3840, 2160, 1.5)


def test_test_monitor_scale_syntax():
    monitors = parse_test_monitors("A:2560x1440+0+0@150%,B:2560x1440+2560+0@1.5")
    assert [(m.name, m.width, m.height, m.x, m.scale) for m in monitors] == [
        ("A", 3840, 2160, 0, 1.5),
        ("B", 3840, 2160, 3840, 1.5),
    ]


def test_test_monitor_supports_mint_scale_options():
    for raw_scale, scale in [
        ("75%", 0.75),
        ("100%", 1.0),
        ("125%", 1.25),
        ("150%", 1.5),
        ("175%", 1.75),
        ("200%", 2.0),
    ]:
        monitor = parse_test_monitors(f"A:100x80+40+20@{raw_scale}")[0]
        assert (monitor.width, monitor.height, monitor.x, monitor.y, monitor.scale) == (
            round(100 * scale),
            round(80 * scale),
            round(40 * scale),
            round(20 * scale),
            scale,
        )


def test_negative_offsets_normalize():
    monitors = parse_test_monitors("Left:100x100+-100+0,Right:200x100+0+0")
    width, height, min_x, min_y = virtual_canvas(monitors)
    assert (width, height, min_x, min_y) == (300, 100, -100, 0)
    assert normalized_position(monitors[0], min_x, min_y) == (0, 0)
    assert normalized_position(monitors[1], min_x, min_y) == (100, 0)
