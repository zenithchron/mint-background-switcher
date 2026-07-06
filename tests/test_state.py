import random

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
