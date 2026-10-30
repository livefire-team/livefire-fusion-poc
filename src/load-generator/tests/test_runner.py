import threading

import pytest

from loadgen.backlog import Backlog
from loadgen.client import OrderResult
from loadgen.config import load_config
from loadgen.runner import LoadRunner
from loadgen.telemetry import Metrics

OK = OrderResult(ok=True, retryable=False, status=201, reason=None)
DOWN = OrderResult(ok=False, retryable=True, status=503, reason="http_503")
BAD = OrderResult(ok=False, retryable=False, status=404, reason="http_404")


class ScriptedClient:
    def __init__(self, results):
        self.results = list(results)
        self.skus = []

    def place(self, sku):
        self.skus.append(sku)
        return self.results.pop(0) if self.results else OK


def build(results, meter, **env):
    config = load_config({"ORDER_APP_URL": "https://a", "RATE_PER_MINUTE": "60", **env})
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    client = ScriptedClient(results)
    metrics = Metrics(meter, backlog_size=lambda: len(backlog))
    return LoadRunner(config, client, backlog, metrics), client, backlog


def test_new_orders_cycle_through_the_skus(meter):
    runner, client, _ = build([], meter)
    for t in range(3):
        runner.tick(now=float(t))
    assert client.skus == ["SKU-001", "SKU-002", "SKU-001"]
    assert meter.counters["loadgen_orders_sent"].total(kind="new", result="ok") == 3


def test_retryable_failure_goes_to_the_backlog_and_is_retried(meter):
    runner, client, backlog = build([DOWN], meter)
    runner.tick(now=0.0)
    assert len(backlog) == 1
    assert meter.counters["loadgen_orders_sent"].total(kind="new", result="failed") == 1
    runner.tick(now=2.0)
    assert len(backlog) == 0
    assert client.skus == ["SKU-001", "SKU-002", "SKU-001"]
    assert meter.counters["loadgen_orders_sent"].total(kind="retry", result="ok") == 1


def test_failed_retry_is_rescheduled(meter):
    runner, _, backlog = build([DOWN, OK, DOWN], meter)
    runner.tick(now=0.0)
    runner.tick(now=2.0)
    assert len(backlog) == 1
    assert backlog.pop_due(now=6.0).attempts == 2


def test_non_retryable_failure_is_dropped(meter):
    runner, _, backlog = build([BAD], meter)
    runner.tick(now=0.0)
    assert len(backlog) == 0
    assert meter.counters["loadgen_orders_dropped"].total(reason="http_404") == 1


def test_full_backlog_counts_a_drop(meter):
    runner, _, backlog = build([DOWN, DOWN], meter, MAX_BACKLOG="1", RETRIES_PER_TICK="0")
    runner.tick(now=0.0)
    runner.tick(now=1.0)
    assert len(backlog) == 1
    assert meter.counters["loadgen_orders_dropped"].total(reason="backlog_full") == 1


def test_retries_per_tick_is_bounded(meter):
    runner, client, backlog = build([DOWN, DOWN, DOWN], meter, RETRIES_PER_TICK="2")
    for t in (0.0, 0.1, 0.2):   # three failures, none due for retry yet
        runner.tick(now=t)
    assert len(backlog) == 3
    client.skus.clear()
    runner.tick(now=100.0)
    assert len(client.skus) == 3
    assert len(backlog) == 1


def test_run_stops_after_the_duration(meter):
    clock = {"t": 0.0}
    waits = []

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            clock["t"] += seconds
            return False

    runner, client, _ = build([], meter, DURATION_SECONDS="3")
    sent = runner.run(stop=Stop(), clock=lambda: clock["t"])
    assert sent == 3
    assert len(client.skus) == 3
    assert waits == [1.0, 1.0, 1.0]


def test_run_stops_when_asked(meter):
    stop = threading.Event()
    stop.set()
    runner, client, _ = build([], meter)
    assert runner.run(stop=stop) == 0
    assert client.skus == []


def test_slow_requests_do_not_lower_the_rate(meter):
    clock = {"t": 0.0}
    waits = []

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            clock["t"] += seconds
            return False

    runner, client, _ = build([], meter, DURATION_SECONDS="3")
    original = client.place

    def slow_place(sku):
        clock["t"] += 0.4
        return original(sku)

    client.place = slow_place
    runner.run(stop=Stop(), clock=lambda: clock["t"])
    assert waits == pytest.approx([0.6, 0.6, 0.6])


def test_missed_ticks_are_skipped_not_burst(meter):
    clock = {"t": 0.0}
    waits = []

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            clock["t"] += seconds
            return False

    runner, client, _ = build([], meter, DURATION_SECONDS="6")
    original = client.place
    calls = {"n": 0}

    def place(sku):
        calls["n"] += 1
        if calls["n"] == 1:
            clock["t"] += 2.5   # one request overruns two intervals
        return original(sku)

    client.place = place
    runner.run(stop=Stop(), clock=lambda: clock["t"])
    assert waits[0] == pytest.approx(0.5)   # next slot is t=3, not an immediate burst
    assert all(w > 0 for w in waits)
