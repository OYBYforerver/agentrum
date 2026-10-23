"""In-process rate limiting and lockout primitives (no external dependencies).

Good enough for single- and multi-replica MVP deployments; global (cross-
replica) limiting via Redis is a Phase B upgrade.
"""

import time
from collections import defaultdict, deque

_MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    """Allows at most `max_events` events per key per `window_seconds`."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._purge(now)
        q = self._events[key]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def _purge(self, now: float) -> None:
        if len(self._events) <= _MAX_TRACKED_KEYS:
            return
        stale = [k for k, q in self._events.items() if not q or now - q[-1] > self.window_seconds]
        for k in stale:
            self._events.pop(k, None)


class FailureLockout:
    """Locks a key after `threshold` failures within `window_seconds`,
    for `lock_seconds`."""

    def __init__(self, threshold: int, window_seconds: float, lock_seconds: float) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> int:
        """Return remaining lock seconds, 0 if not locked."""
        until = self._locked_until.get(key, 0.0)
        remaining = int(until - time.monotonic())
        if remaining <= 0:
            self._locked_until.pop(key, None)
            return 0
        return remaining

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        q = self._failures[key]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        q.append(now)
        if len(q) >= self.threshold:
            self._locked_until[key] = now + self.lock_seconds
            self._failures.pop(key, None)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)
