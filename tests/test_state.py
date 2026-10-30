import random

from mint_background_switcher import state as state_module
from mint_background_switcher.state import RuntimeState, draw_many, draw_one


def test_draw_one_no_repeat_until_exhausted():
    state = RuntimeState()
    pool = ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"]
    rng = random.Random(1)
    first_cycle = [draw_one(state, "bucket", pool, rng=rng) for _ in range(3)]
    assert sorted(first_cycle) == sorted(pool)
    assert state.remaining["bucket"] == []
    fourth = draw_one(state, "bucket", pool, rng=rng)
    assert fourth in pool


def test_draw_many_uses_unique_images_when_possible():
    state = RuntimeState()
    pool = ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg", "/tmp/d.jpg"]
    chosen = draw_many(state, "bucket", pool, 3, rng=random.Random(2))
    assert len(chosen) == 3
    assert len(set(chosen)) == 3
    assert len(state.remaining["bucket"]) == 1


def test_draw_many_uses_set_membership_for_large_existing_remaining(monkeypatch):
    class NoLinearMembership(list):
        def __contains__(self, _item):
            raise AssertionError("normalized pool used linear list membership")

    pool = [f"/tmp/{index}.jpg" for index in range(100)]
    monkeypatch.setattr(state_module, "_normalized_pool", lambda _pool: NoLinearMembership(pool))
    state = RuntimeState(remaining={"bucket": list(pool)})

    chosen = draw_many(state, "bucket", pool, 4, rng=random.Random(2))

    assert len(chosen) == 4
    assert len(set(chosen)) == 4


def test_sequential_draw_folds_pool_in_folder_order_and_wraps_without_repeats():
    state = RuntimeState()
    pool = ["/tmp/c.jpg", "/tmp/a.jpg", "/tmp/b.jpg"]
    first_cycle = [draw_one(state, "bucket", pool, rng=random.Random(3), sequential=True) for _ in range(3)]
    assert first_cycle == ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"]
    assert state.remaining["bucket"] == []
    assert draw_one(state, "bucket", pool, rng=random.Random(3), sequential=True) == "/tmp/a.jpg"


def test_sequential_draw_restarts_leftover_random_pool_in_folder_order():
    pool = [f"/tmp/{name}.jpg" for name in ("c", "a", "b")]
    state = RuntimeState(remaining={"bucket": ["/tmp/c.jpg", "/tmp/b.jpg"]})

    chosen = draw_many(state, "bucket", pool, 2, rng=random.Random(4), sequential=True)

    assert chosen == ["/tmp/b.jpg", "/tmp/c.jpg"]


def test_sequential_draw_many_preserves_folder_order_within_batch():
    state = RuntimeState()
    pool = [f"/tmp/{name}.jpg" for name in ("d", "a", "c", "b")]

    chosen = draw_many(state, "bucket", pool, 4, rng=random.Random(5), sequential=True)

    assert chosen == ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg", "/tmp/d.jpg"]


def test_black_reason_roundtrips_and_defaults_to_empty():
    state = RuntimeState(black_screen=True, black_reason="night")
    assert state.to_dict()["black_reason"] == "night"
    assert RuntimeState.from_dict(state.to_dict()).black_reason == "night"

    assert RuntimeState().black_reason == ""
    assert RuntimeState.from_dict({"black_screen": True}).black_reason == ""
    assert RuntimeState.from_dict({"black_reason": None}).black_reason == ""
