from agentrum.auth.ratelimit import (
    _GC_EVERY,
    _MAX_TRACKED_KEYS,
    FailureLockout,
    SlidingWindowLimiter,
)


def test_sliding_window_blocks_after_max():
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
    assert limiter.allow("ip1")
    assert limiter.allow("ip1")
    assert limiter.allow("ip1")
    assert not limiter.allow("ip1")
    assert limiter.allow("ip2")  # independent keys


def test_sliding_window_recovers_after_reset():
    limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
    assert limiter.allow("k")
    assert not limiter.allow("k")
    limiter.reset("k")
    assert limiter.allow("k")


def test_lockout_after_threshold_and_reset_on_success():
    lock = FailureLockout(threshold=3, window_seconds=60, lock_seconds=120)
    lock.record_failure("u")
    lock.record_failure("u")
    assert lock.is_locked("u") == 0
    lock.record_failure("u")  # third failure locks
    assert lock.is_locked("u") > 0
    lock.reset("u")
    assert lock.is_locked("u") == 0


def test_sliding_window_memory_is_bounded():
    """Spraying random keys must not grow the table without bound (the GC
    runs every _GC_EVERY calls, so allow one GC interval of slack)."""
    limiter = SlidingWindowLimiter(max_events=1000, window_seconds=60)
    for i in range(_MAX_TRACKED_KEYS + 2000):
        limiter.allow(f"key-{i}")
    assert len(limiter._events) <= _MAX_TRACKED_KEYS + _GC_EVERY


def test_lockout_memory_is_bounded():
    lock = FailureLockout(threshold=10_000, window_seconds=60, lock_seconds=1)
    for i in range(_MAX_TRACKED_KEYS + 2000):
        lock.record_failure(f"user-{i}")
    assert len(lock._failures) <= _MAX_TRACKED_KEYS + _GC_EVERY
    assert len(lock._locked_until) <= _MAX_TRACKED_KEYS + _GC_EVERY


# --- async, pluggable-backend facades ----------------------------------------

import pytest

from agentrum.auth import ratelimit
from agentrum.auth.ratelimit import AsyncFailureLockout, AsyncSlidingWindowLimiter


async def test_async_sliding_window_memory_matches_sync_semantics():
    limiter = AsyncSlidingWindowLimiter(max_events=3, window_seconds=60, prefix="t")
    assert await limiter.allow("ip1")
    assert await limiter.allow("ip1")
    assert await limiter.allow("ip1")
    assert not await limiter.allow("ip1")
    assert await limiter.allow("ip2")
    await limiter.reset("ip1")
    assert await limiter.allow("ip1")


async def test_async_lockout_memory_semantics():
    lock = AsyncFailureLockout(threshold=2, window_seconds=60, lock_seconds=120, prefix="t")
    assert await lock.is_locked("u") == 0
    await lock.record_failure("u")
    await lock.record_failure("u")
    assert await lock.is_locked("u") > 0
    await lock.reset("u")
    assert await lock.is_locked("u") == 0


@pytest.fixture
def shared_redis(monkeypatch):
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(ratelimit, "_redis_client_cache", fake)
    yield fake
    # fakeredis clients are closed implicitly; nothing to tear down.


async def test_async_sliding_window_counters_are_shared_across_instances(shared_redis):
    """Two 'replicas' (separate facades) must see one shared window."""
    replica_a = AsyncSlidingWindowLimiter(max_events=3, window_seconds=60, prefix="rl")
    replica_b = AsyncSlidingWindowLimiter(max_events=3, window_seconds=60, prefix="rl")
    assert await replica_a.allow("ip")
    assert await replica_b.allow("ip")
    assert await replica_a.allow("ip")
    # 3 events across both replicas: the 4th is refused regardless of facade.
    assert not await replica_b.allow("ip")


async def test_async_lockout_is_shared_across_instances(shared_redis):
    replica_a = AsyncFailureLockout(threshold=2, window_seconds=60, lock_seconds=120, prefix="rlk")
    replica_b = AsyncFailureLockout(threshold=2, window_seconds=60, lock_seconds=120, prefix="rlk")
    await replica_a.record_failure("ak-1")
    await replica_b.record_failure("ak-1")
    assert await replica_a.is_locked("ak-1") > 0
    assert await replica_b.is_locked("ak-1") > 0
    await replica_a.reset("ak-1")
    assert await replica_b.is_locked("ak-1") == 0


async def test_async_lockout_lock_expires(shared_redis):
    lock = AsyncFailureLockout(threshold=1, window_seconds=60, lock_seconds=1, prefix="rlk")
    await lock.record_failure("u")
    assert await lock.is_locked("u") > 0
    await shared_redis.delete("rlk:lock:u")
    assert await lock.is_locked("u") == 0
