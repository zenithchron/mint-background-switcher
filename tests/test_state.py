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
