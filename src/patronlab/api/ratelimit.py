"""Per-user rate limit for the AI tools (sliding window, in memory).

The AI tools are CPU-bound, so one artisan clicking "generate" in a loop
could keep the only machine busy. Counts live in the process: this is exact
with the single Fly machine this project runs on; with several machines each
one would count separately (a shared store such as Redis would be needed).
"""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int) -> float | None:
        """Counts one request. Returns None if allowed, or the seconds to wait."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= limit:
            return round(hits[0] + self._window - now, 1)
        hits.append(now)
        # Forget idle users so the dictionary does not grow forever.
        if len(self._hits) > 10_000:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self._window}
        return None
