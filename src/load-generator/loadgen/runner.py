"""The steady loop: one new order per tick, plus a bounded number of due retries from the backlog."""
import itertools
import math
import time
from collections.abc import Callable

from loadgen.backlog import Backlog, PendingOrder
from loadgen.config import Config
from loadgen.telemetry import Metrics, log_status

STATUS_EVERY_TICKS = 30


class LoadRunner:
    def __init__(self, config: Config, client, backlog: Backlog, metrics: Metrics):
        self._config = config
        self._client = client
        self._backlog = backlog
        self._metrics = metrics
        self._skus = itertools.cycle(config.skus)
        self.sent = 0

    def _handle_failure(self, result, queue: Callable[[], bool]) -> None:
        if not result.retryable:
            self._metrics.dropped(result.reason or "error")
        elif not queue():
            self._metrics.dropped("backlog_full")

    def _send_new(self, now: float) -> None:
        sku = next(self._skus)
        result = self._client.place(sku)
        self.sent += 1
        self._metrics.sent(kind="new", ok=result.ok)
        if not result.ok:
            self._handle_failure(result, lambda: self._backlog.add(sku, now))

    def _retry(self, order: PendingOrder, now: float) -> None:
        result = self._client.place(order.sku)
        self.sent += 1
        self._metrics.sent(kind="retry", ok=result.ok)
        if not result.ok:
            self._handle_failure(result, lambda: self._backlog.retry_later(order, now))

    def tick(self, now: float) -> None:
        self._send_new(now)
        for _ in range(self._config.retries_per_tick):
            order = self._backlog.pop_due(now)
            if order is None:
                break
            self._retry(order, now)

    def _seconds_until_next_slot(self, start: float, ticks: int, now: float) -> float:
        """Slots sit at start + n*interval; slots already missed are skipped rather than bursted."""
        interval = self._config.interval_seconds
        slot = ticks
        if start + slot * interval <= now:
            slot = math.floor((now - start) / interval) + 1
        return start + slot * interval - now

    def run(self, stop, clock: Callable[[], float] = time.monotonic) -> int:
        """Tick at the configured rate until `stop` is set or DURATION_SECONDS (0 = no limit) has passed."""
        start = clock()
        duration = self._config.duration_seconds
        ticks = 0
        while not stop.is_set():
            if duration and clock() - start >= duration:
                break
            self.tick(clock())
            ticks += 1
            if ticks % STATUS_EVERY_TICKS == 0:
                log_status(self.sent, len(self._backlog), self._backlog.dropped)
            if stop.wait(self._seconds_until_next_slot(start, ticks, clock())):
                break
        log_status(self.sent, len(self._backlog), self._backlog.dropped)
        return self.sent
