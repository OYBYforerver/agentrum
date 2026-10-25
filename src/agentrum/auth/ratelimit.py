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


# --- Shared-backend (async) facades -----------------------------------------
#
# The primitives above count per process: fine for single-replica, wrong for
# the default Helm topology (2 replicas). The facades keep identical
# semantics and delegate to Redis when ARK_RATELIMIT_BACKEND=redis, sharing
# counters across replicas. Redis outages fail OPEN (allow + one warning per
# process): rate limiting is a mitigation layer, and locking out every human
# because its counters are down would turn a backend outage into a login
# outage.

import logging
import uuid

logger = logging.getLogger(__name__)

_redis_client_cache: object | None = None


def _shared_redis():  # pragma: no cover - wiring, exercised via fakeredis tests
    global _redis_client_cache
    if _redis_client_cache is not None:
        return _redis_client_cache
    from agentrum.config import get_settings

    settings = get_settings()
    if settings.ratelimit_backend != "redis":
        return None
    try:
        import redis.asyncio as aioredis
    except ImportError as exc:  # pragma: no cover - extra not installed
        raise RuntimeError(
            "ARK_RATELIMIT_BACKEND=redis requires the redis extra: "
            "pip install 'agentrum[redis]'"
        ) from exc
    _redis_client_cache = aioredis.from_url(
        settings.ratelimit_redis_url or "redis://localhost:6379/0"
    )
    return _redis_client_cache


# Sliding window as a sorted set of timestamps; the count-vs-add decision
# must be atomic or two replicas can each admit the same final event.
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_events = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) >= max_events then
  return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window * 2)
return 1
"""

# Failure tracking + lockout flip in one round trip, same atomicity reason.
_LOCKOUT_RECORD_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])
local lockms = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
redis.call('ZADD', KEYS[1], now, ARGV[5])
redis.call('PEXPIRE', KEYS[1], window * 2)
if redis.call('ZCARD', KEYS[1]) >= threshold then
  redis.call('SET', KEYS[2], '1', 'PX', lockms)
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""


class AsyncSlidingWindowLimiter:
    """`SlidingWindowLimiter` semantics behind an async interface; counters
    are shared across replicas when a Redis backend is configured."""

    def __init__(self, max_events: int, window_seconds: float, prefix: str) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.prefix = prefix
        self._local = SlidingWindowLimiter(max_events, window_seconds)
        self._warned = False

    async def allow(self, key: str) -> bool:
        redis = _shared_redis()
        if redis is None:
            return self._local.allow(key)
        try:
            now_ms = int(time.time() * 1000)
            ok = await redis.eval(
                _SLIDING_WINDOW_LUA, 1, f"{self.prefix}:{key}",
                now_ms, int(self.window_seconds * 1000), self.max_events,
                uuid.uuid4().hex,
            )
            return bool(ok)
        except Exception:
            if not self._warned:
                logger.warning("rate-limit backend unreachable; failing open", exc_info=True)
                self._warned = True
            return True

    async def reset(self, key: str) -> None:
        redis = _shared_redis()
        if redis is None:
            self._local.reset(key)
            return
        try:
            await redis.delete(f"{self.prefix}:{key}")
        except Exception:  # reset is best-effort; a stuck counter only over-limits
            if not self._warned:
                logger.warning("rate-limit reset failed (best-effort)", exc_info=True)
                self._warned = True


class AsyncFailureLockout:
    """`FailureLockout` semantics behind an async interface; the lock is a
    plain key with a TTL so every replica observes it immediately."""

    def __init__(
        self, threshold: int, window_seconds: float, lock_seconds: float, prefix: str
    ) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.prefix = prefix
        self._local = FailureLockout(threshold, window_seconds, lock_seconds)
        self._warned = False

    def _fail_key(self, key: str) -> str:
        return f"{self.prefix}:fails:{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self.prefix}:lock:{key}"

    async def is_locked(self, key: str) -> int:
        """Remaining lock seconds, 0 if not locked."""
        redis = _shared_redis()
        if redis is None:
            return self._local.is_locked(key)
        try:
            pttl = await redis.pttl(self._lock_key(key))
            # -2: missing, -1: no expiry (never set by us) — both mean unlocked.
            return max(0, -(-pttl // 1000)) if pttl > 0 else 0
        except Exception:
            if not self._warned:
                logger.warning("rate-limit backend unreachable; failing open", exc_info=True)
                self._warned = True
            return 0

    async def record_failure(self, key: str) -> None:
        redis = _shared_redis()
        if redis is None:
            self._local.record_failure(key)
            return
        try:
            await redis.eval(
                _LOCKOUT_RECORD_LUA, 2, self._fail_key(key), self._lock_key(key),
                int(time.time() * 1000), int(self.window_seconds * 1000),
                self.threshold, int(self.lock_seconds * 1000), uuid.uuid4().hex,
            )
        except Exception:
            if not self._warned:
                logger.warning("rate-limit backend unreachable; failing open", exc_info=True)
                self._warned = True

    async def reset(self, key: str) -> None:
        redis = _shared_redis()
        if redis is None:
            self._local.reset(key)
            return
        try:
            await redis.delete(self._fail_key(key), self._lock_key(key))
        except Exception:  # reset is best-effort; a stuck counter only over-limits
            if not self._warned:
                logger.warning("rate-limit reset failed (best-effort)", exc_info=True)
                self._warned = True
