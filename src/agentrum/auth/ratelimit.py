"""In-process rate limiting and lockout primitives (no external dependencies).

Good enough for single- and multi-replica MVP deployments; global (cross-
replica) limiting via Redis is a Phase B upgrade.

Both primitives keep at most _MAX_TRACKED_KEYS entries: adversarial input
(random usernames / IPs) grows the tables until the cap, then expired or
oldest entries are evicted instead of letting memory grow without bound.
"""

import time
from collections import deque

_MAX_TRACKED_KEYS = 10_000
# How often (in calls) the tables are swept for expired entries; keeps the
# amortized GC cost negligible instead of scanning on every call.
_GC_EVERY = 512


def _gc_tables(tables: list[dict], *, stale: callable, now: float) -> None:  # type: ignore[valid-type]
    """Evict stale entries, then the oldest ones, when over the cap."""
    total = sum(len(t) for t in tables)
    if total <= _MAX_TRACKED_KEYS:
        return
    for table in tables:
        for key in [k for k, v in table.items() if stale(v, now)]:
            table.pop(key, None)
    total = sum(len(t) for t in tables)
    for table in tables:
        while total > _MAX_TRACKED_KEYS and table:
            table.pop(next(iter(table)))
            total -= 1


class SlidingWindowLimiter:
    """Allows at most `max_events` events per key per `window_seconds`."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._calls = 0

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % _GC_EVERY == 0:
            self._gc(now)
        q = self._events.get(key)
        if q is None:
            q = self._events[key] = deque()
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def _gc(self, now: float) -> None:  # type: ignore[no-untyped-def]
        _gc_tables(
            [self._events],
            stale=lambda q, t: not q or t - q[-1] > self.window_seconds,
            now=now,
        )


class FailureLockout:
    """Locks a key after `threshold` failures within `window_seconds`,
    for `lock_seconds`."""

    def __init__(self, threshold: int, window_seconds: float, lock_seconds: float) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._calls = 0

    def is_locked(self, key: str) -> int:
        """Return remaining lock seconds, 0 if not locked."""
        now = time.monotonic()
        self._gc_tick(now)
        until = self._locked_until.get(key, 0.0)
        remaining = int(until - now)
        if remaining <= 0:
            self._locked_until.pop(key, None)
            return 0
        return remaining

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._gc_tick(now)
        q = self._failures.get(key)
        if q is None:
            q = self._failures[key] = deque()
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        q.append(now)
        if len(q) >= self.threshold:
            self._locked_until[key] = now + self.lock_seconds
            self._failures.pop(key, None)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)

    def _gc_tick(self, now: float) -> None:  # type: ignore[no-untyped-def]
        self._calls += 1
        if self._calls % _GC_EVERY:
            return
        _gc_tables(
            [self._locked_until, self._failures],
            stale=lambda v, t: (
                v <= t
                if isinstance(v, float)
                else not v or t - v[-1] > self.window_seconds
            ),
            now=now,
        )
