"""Monitor detection and virtual desktop geometry."""

from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass

SUPPORTED_SCALE_FACTORS = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
SCALE_TOLERANCE = 0.03


@dataclass(frozen=True, slots=True)
class Monitor:
    name: str
    width: int
    height: int
    x: int
    y: int
    primary: bool = False
    scale: float = 1.0
    logical_width: int | None = None
    logical_height: int | None = None
    logical_x: int | None = None
    logical_y: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_width", self.width if self.logical_width is None else self.logical_width)
        object.__setattr__(self, "logical_height", self.height if self.logical_height is None else self.logical_height)
        object.__setattr__(self, "logical_x", self.x if self.logical_x is None else self.logical_x)
        object.__setattr__(self, "logical_y", self.y if self.logical_y is None else self.logical_y)

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    @property
    def logical_geometry(self) -> tuple[int, int, int, int]:
        return (
            int(self.logical_x or 0),
            int(self.logical_y or 0),
            int(self.logical_width or self.width),
            int(self.logical_height or self.height),
        )


_XRANDR_RE = re.compile(
    r"^(?P<name>\S+)\s+connected(?:\s+(?P<primary>primary))?\s+"
    r"(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
)
_ACTIVE_MODE_RE = re.compile(r"^\s+(?P<w>\d+)x(?P<h>\d+)(?:[i_][^\s]*)?\s+.*\*")
_TEST_RE = re.compile(
    r"(?P<name>[^:,@]+):(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
    r"(?:@(?P<scale>\d+(?:\.\d+)?%?))?"
)


def _nearest_supported_scale(value: float) -> float | None:
    for supported in SUPPORTED_SCALE_FACTORS:
        if math.isclose(value, supported, abs_tol=SCALE_TOLERANCE):
            return supported
    return None


def _active_mode_after(lines: list[str], start_index: int) -> tuple[int, int] | None:
    for line in lines[start_index + 1 :]:
        # The next non-indented output line starts another connector; stop before
        # accidentally borrowing its active mode.
        if line and not line[:1].isspace():
            break
        match = _ACTIVE_MODE_RE.search(line)
        if match:
            return (int(match.group("w")), int(match.group("h")))
    return None


def _physical_geometry(
    logical_w: int,
    logical_h: int,
    logical_x: int,
    logical_y: int,
    active_mode: tuple[int, int] | None,
) -> tuple[int, int, int, int, float]:
    if active_mode and logical_w > 0 and logical_h > 0:
        active_w, active_h = active_mode
        scale_w = active_w / logical_w
        scale_h = active_h / logical_h
        if math.isclose(scale_w, scale_h, abs_tol=SCALE_TOLERANCE):
            supported_scale = _nearest_supported_scale((scale_w + scale_h) / 2.0)
            if supported_scale is not None:
                return (
                    active_w,
                    active_h,
                    round(logical_x * supported_scale),
                    round(logical_y * supported_scale),
                    supported_scale,
                )
    return (logical_w, logical_h, logical_x, logical_y, 1.0)


def _logical_axis(monitor: Monitor, axis: str) -> tuple[int, int]:
    if axis == "x":
        start = monitor.logical_x if monitor.logical_x is not None else monitor.x
        size = monitor.logical_width if monitor.logical_width is not None else monitor.width
    else:
        start = monitor.logical_y if monitor.logical_y is not None else monitor.y
        size = monitor.logical_height if monitor.logical_height is not None else monitor.height
    return int(start), int(size)


def _intervals_overlap(a_start: int, a_size: int, b_start: int, b_size: int) -> bool:
    return max(a_start, b_start) < min(a_start + a_size, b_start + b_size)


def _intervals_touch_or_overlap(a_start: int, a_size: int, b_start: int, b_size: int) -> bool:
    return max(a_start, b_start) <= min(a_start + a_size, b_start + b_size)


def _scale_monitor_positions(monitors: list[Monitor]) -> list[Monitor]:
    """Convert logical xrandr layout into physical-pixel monitor origins.

    Fractional scaling makes each monitor's logical rectangle a different size
    from its physical panel. Multiplying every logical origin by that monitor's
    own scale works only for homogeneous rows. Instead, preserve logical
    adjacency constraints: monitors touching left/right or top/bottom remain
    touching after conversion, and monitors in the same logical row/column keep
    a shared physical row/column origin.
    """
    if not monitors:
        return []

    x_pos = {index: monitor.x for index, monitor in enumerate(monitors)}
    y_pos = {index: monitor.y for index, monitor in enumerate(monitors)}
    passes = max(1, len(monitors) * len(monitors))

    for _ in range(passes):
        changed = False
        for left_index, left in enumerate(monitors):
            left_x, left_w = _logical_axis(left, "x")
            left_y, left_h = _logical_axis(left, "y")
            for right_index, right in enumerate(monitors):
                if left_index == right_index:
                    continue
                right_x, right_w = _logical_axis(right, "x")
                right_y, right_h = _logical_axis(right, "y")

                if left_y == right_y and _intervals_touch_or_overlap(left_x, left_w, right_x, right_w):
                    aligned_y = max(y_pos[left_index], y_pos[right_index])
                    if y_pos[left_index] != aligned_y:
                        y_pos[left_index] = aligned_y
                        changed = True
                    if y_pos[right_index] != aligned_y:
                        y_pos[right_index] = aligned_y
                        changed = True
                if left_x == right_x and _intervals_touch_or_overlap(left_y, left_h, right_y, right_h):
                    aligned_x = max(x_pos[left_index], x_pos[right_index])
                    if x_pos[left_index] != aligned_x:
                        x_pos[left_index] = aligned_x
                        changed = True
                    if x_pos[right_index] != aligned_x:
                        x_pos[right_index] = aligned_x
                        changed = True

                if left_x + left_w == right_x and _intervals_overlap(left_y, left_h, right_y, right_h):
                    new_x = x_pos[left_index] + left.width
                    if x_pos[right_index] != new_x:
                        x_pos[right_index] = new_x
                        changed = True
                if right_x + right_w == left_x and _intervals_overlap(left_y, left_h, right_y, right_h):
                    new_x = x_pos[right_index] + right.width
                    if x_pos[left_index] != new_x:
                        x_pos[left_index] = new_x
                        changed = True
                if left_y + left_h == right_y and _intervals_overlap(left_x, left_w, right_x, right_w):
                    new_y = y_pos[left_index] + left.height
                    if y_pos[right_index] != new_y:
                        y_pos[right_index] = new_y
                        changed = True
                if right_y + right_h == left_y and _intervals_overlap(left_x, left_w, right_x, right_w):
                    new_y = y_pos[right_index] + right.height
                    if y_pos[left_index] != new_y:
                        y_pos[left_index] = new_y
                        changed = True
        if not changed:
            break

    return [
        Monitor(
            name=monitor.name,
            width=monitor.width,
            height=monitor.height,
            x=x_pos[index],
            y=y_pos[index],
            primary=monitor.primary,
            scale=monitor.scale,
            logical_width=monitor.logical_width,
            logical_height=monitor.logical_height,
            logical_x=monitor.logical_x,
            logical_y=monitor.logical_y,
        )
        for index, monitor in enumerate(monitors)
    ]


def parse_xrandr(output: str) -> list[Monitor]:
    """Parse xrandr output into physical wallpaper-composition geometry.

    Cinnamon fractional monitor scale makes the connector line report logical
    desktop geometry (for example 2560x1440 for a 3840x2160 display at 150%).
    The active mode line still contains the physical panel resolution. When the
    ratio matches a Mint-supported scale factor, use the physical resolution and
    scale the position so generated spanned wallpapers fill the real desktop.
    """
    monitors: list[Monitor] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = _XRANDR_RE.search(line.strip())
        if not match:
            continue
        logical_w = int(match.group("w"))
        logical_h = int(match.group("h"))
        logical_x = int(match.group("x"))
        logical_y = int(match.group("y"))
        width, height, x, y, scale = _physical_geometry(
            logical_w,
            logical_h,
            logical_x,
            logical_y,
            _active_mode_after(lines, index),
        )
        monitors.append(
            Monitor(
                name=match.group("name"),
                width=width,
                height=height,
                x=x,
                y=y,
                primary=bool(match.group("primary")),
                scale=scale,
                logical_width=logical_w,
                logical_height=logical_h,
                logical_x=logical_x,
                logical_y=logical_y,
            )
        )
    return sorted(_scale_monitor_positions(monitors), key=lambda m: (m.x, m.y, m.name))


def _parse_test_scale(raw_scale: str | None) -> float:
    if not raw_scale:
        return 1.0
    value = float(raw_scale[:-1]) / 100.0 if raw_scale.endswith("%") else float(raw_scale)
    supported = _nearest_supported_scale(value)
    if supported is None:
        raise ValueError(f"Unsupported monitor scale in MBS_TEST_MONITORS: {raw_scale!r}")
    return supported


def parse_test_monitors(spec: str) -> list[Monitor]:
    monitors = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _TEST_RE.fullmatch(chunk)
        if not match:
            raise ValueError(f"Invalid MBS_TEST_MONITORS chunk: {chunk!r}")
        scale = _parse_test_scale(match.group("scale"))
        logical_w = int(match.group("w"))
        logical_h = int(match.group("h"))
        logical_x = int(match.group("x"))
        logical_y = int(match.group("y"))
        monitors.append(
            Monitor(
                name=match.group("name"),
                width=round(logical_w * scale),
                height=round(logical_h * scale),
                x=round(logical_x * scale),
                y=round(logical_y * scale),
                scale=scale,
                logical_width=logical_w,
                logical_height=logical_h,
                logical_x=logical_x,
                logical_y=logical_y,
            )
        )
    if not monitors:
        raise ValueError("MBS_TEST_MONITORS did not define any monitors")
    return sorted(_scale_monitor_positions(monitors), key=lambda m: (m.x, m.y, m.name))


def detect_monitors() -> list[Monitor]:
    test_spec = os.environ.get("MBS_TEST_MONITORS")
    if test_spec:
        return parse_test_monitors(test_spec)
    try:
        proc = subprocess.run(["xrandr", "--query"], check=True, capture_output=True, text=True)
        monitors = parse_xrandr(proc.stdout)
        if monitors:
            return monitors
    except (OSError, subprocess.CalledProcessError):
        pass
    return [Monitor("Virtual-0", 1920, 1080, 0, 0, primary=True)]


def virtual_canvas(monitors: list[Monitor]) -> tuple[int, int, int, int]:
    if not monitors:
        raise ValueError("No monitors available")
    min_x = min(m.x for m in monitors)
    min_y = min(m.y for m in monitors)
    max_x = max(m.x + m.width for m in monitors)
    max_y = max(m.y + m.height for m in monitors)
    return (max_x - min_x, max_y - min_y, min_x, min_y)


def normalized_position(monitor: Monitor, min_x: int, min_y: int) -> tuple[int, int]:
    return (monitor.x - min_x, monitor.y - min_y)
