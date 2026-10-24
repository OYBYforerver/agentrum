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
