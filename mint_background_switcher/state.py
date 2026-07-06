"""Persistent runtime state and no-repeat image pools."""

from __future__ import annotations

import json
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .paths import state_file, xdg_config_dir
from .storage import atomic_write_json_unlocked, locked_file, locked_read_json, locked_write_json, lock_path_for, read_json_unlocked


@dataclass(slots=True)
class RuntimeState:
    paused: bool = False
    black_screen: bool = False
    active_profile: str | None = None
    remaining: dict[str, list[str]] = field(default_factory=dict)
    last_wallpaper: str | None = None
    last_images: list[str] = field(default_factory=list)
    wallpaper_slot: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        remaining_raw = data.get("remaining", {})
        remaining = (
            {
                str(k): [str(v) for v in vals]
                for k, vals in remaining_raw.items()
                if isinstance(vals, list)
            }
            if isinstance(remaining_raw, dict)
            else {}
        )
        last_images_raw = data.get("last_images", [])
        try:
            wallpaper_slot = int(data.get("wallpaper_slot", 0) or 0) % 2
        except (TypeError, ValueError):
            wallpaper_slot = 0
        return cls(
            paused=bool(data.get("paused", False)),
            black_screen=bool(data.get("black_screen", False)),
            active_profile=data.get("active_profile"),
            remaining=remaining,
            last_wallpaper=data.get("last_wallpaper"),
            last_images=[str(v) for v in last_images_raw] if isinstance(last_images_raw, list) else [],
            wallpaper_slot=wallpaper_slot,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "black_screen": self.black_screen,
            "active_profile": self.active_profile,
            "remaining": self.remaining,
            "last_wallpaper": self.last_wallpaper,
            "last_images": self.last_images,
            "wallpaper_slot": self.wallpaper_slot,
        }


def load_state(path: Path | None = None) -> RuntimeState:
    path = path or state_file()
    if not path.exists():
        return RuntimeState()
    try:
        return RuntimeState.from_dict(locked_read_json(path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return RuntimeState()


def save_state(state: RuntimeState, path: Path | None = None) -> Path:
    path = path or state_file()
    xdg_config_dir().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    locked_write_json(path, state.to_dict())
    return path


@contextmanager
def state_transaction(path: Path | None = None) -> Iterator[RuntimeState]:
    """Lock state for a read-modify-write operation and save atomically on success."""
    path = path or state_file()
    xdg_config_dir().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(lock_path_for(path)):
        try:
            state = RuntimeState.from_dict(read_json_unlocked(path)) if path.exists() else RuntimeState()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            state = RuntimeState()
        yield state
        atomic_write_json_unlocked(path, state.to_dict())


def _normalized_pool(pool: list[str]) -> list[str]:
    return sorted({str(Path(p).expanduser().resolve()) for p in pool})


def draw_one(state: RuntimeState, bucket: str, pool: list[str], rng: random.Random | None = None) -> str:
    chosen = draw_many(state, bucket, pool, 1, rng=rng)
    if not chosen:
        raise ValueError(f"No images available for bucket {bucket}")
    return chosen[0]


def draw_many(
    state: RuntimeState,
    bucket: str,
    pool: list[str],
    count: int,
    rng: random.Random | None = None,
) -> list[str]:
    rng = rng or random.SystemRandom()
    pool_norm = _normalized_pool(pool)
    if not pool_norm or count <= 0:
        return []

    selected: list[str] = []
    while len(selected) < count:
        remaining = [p for p in state.remaining.get(bucket, []) if p in pool_norm and p not in selected]
        if not remaining:
            remaining = [p for p in pool_norm if p not in selected]
            if not remaining:
                remaining = list(pool_norm)
            rng.shuffle(remaining)
        selected.append(remaining.pop())
        state.remaining[bucket] = remaining
    return selected
