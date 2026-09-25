import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.requests import Request


class RateLimiter:
    """In-process sliding window. Correct for a single web process, which is the deployment target."""

    def __init__(self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.max_events:
                return False
            events.append(now)
            return True


def client_ip(request: Request, *, trust_cf: bool) -> str:
    if trust_cf and (ip := request.headers.get("cf-connecting-ip")):
        return ip
    return request.client.host if request.client else "unknown"
