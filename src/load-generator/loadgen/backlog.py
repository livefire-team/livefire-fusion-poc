"""Bounded in-memory backlog of orders that failed and will be tried again, with exponential backoff."""
import heapq
import itertools
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PendingOrder:
    sku: str
    attempts: int
    next_attempt_at: float


class Backlog:
    def __init__(self, max_size: int, base_delay: float, max_delay: float):
        self._max_size = max_size
        self._base = base_delay
        self._cap = max_delay
        self._heap: list[tuple[float, int, PendingOrder]] = []
        self._order = itertools.count()   # tie-breaker keeps first-in-first-out for equal due times
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._heap)

    def _delay(self, attempts: int) -> float:
        return min(self._cap, self._base * 2 ** (attempts - 1))

    def _push(self, order: PendingOrder) -> bool:
        if len(self._heap) >= self._max_size:
            self.dropped += 1
            return False
        heapq.heappush(self._heap, (order.next_attempt_at, next(self._order), order))
        return True

    def add(self, sku: str, now: float) -> bool:
        """Queue a first failure. Returns False (and counts a drop) when the backlog is full."""
        return self._push(PendingOrder(sku=sku, attempts=1, next_attempt_at=now + self._delay(1)))

    def retry_later(self, order: PendingOrder, now: float) -> bool:
        """Queue an order whose retry failed again, with a longer delay."""
        attempts = order.attempts + 1
        return self._push(replace(order, attempts=attempts, next_attempt_at=now + self._delay(attempts)))

    def pop_due(self, now: float) -> PendingOrder | None:
        if not self._heap or self._heap[0][0] > now:
            return None
        return heapq.heappop(self._heap)[2]
