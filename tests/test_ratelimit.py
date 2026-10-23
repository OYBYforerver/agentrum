from agentrum.auth.ratelimit import FailureLockout, SlidingWindowLimiter


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
