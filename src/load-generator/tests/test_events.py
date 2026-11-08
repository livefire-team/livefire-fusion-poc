import json
import logging
import threading
import time

import pytest
from azure.core.exceptions import ResourceExistsError

from loadgen import __main__ as entry
from loadgen import events
from loadgen.backlog import Backlog
from loadgen.client import OrderResult
from loadgen.config import ConfigError, load_config
from loadgen.events import (BlobSink, DirSink, OrderEventReporter, OrderTally, QueuedSink, parse_event_source,
                            sink_from_source)
from loadgen.runner import LoadRunner
from loadgen.telemetry import Metrics

DRILL = "drill-loadgen-test-1"
KEYS = {"orders_per_min", "failed_total", "backlog", "recovered_total", "dropped_total", "window_s"}
BASE = {"ORDER_APP_URL": "https://a", "RATE_PER_MINUTE": "60"}
BLOB = "blob:https://acct.blob.core.windows.net/evidence"
OK = OrderResult(ok=True, retryable=False, status=201, reason=None)
DOWN = OrderResult(ok=False, retryable=True, status=503, reason="http_503")
BAD = OrderResult(ok=False, retryable=False, status=404, reason="http_404")


class MemorySink:
    def __init__(self, fail=False, delay=0.0):
        self.events, self.fail, self.delay = [], fail, delay

    def append(self, drill_id, event):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise OSError("disk full")
        self.events.append((drill_id, event))


def details(sink):
    return [e["details"] for _, e in sink.events]


# ---- settings ----

def test_events_are_off_by_default():
    config = load_config(BASE)
    assert config.event_source is None
    assert config.metrics_interval_seconds == 30


@pytest.mark.parametrize("env", [
    {"EVENT_SOURCE": "dir:./evidence"},                                         # no DRILL_ID
    {"EVENT_SOURCE": "dir:./evidence", "DRILL_ID": "run-1"},                    # not a drill- ID
    {"EVENT_SOURCE": "file:./evidence", "DRILL_ID": DRILL},                     # unknown prefix
    {"EVENT_SOURCE": "dir:", "DRILL_ID": DRILL},                                # empty path
    {"EVENT_SOURCE": "blob:http://acct.blob.core.windows.net/evidence", "DRILL_ID": DRILL},
    {"EVENT_SOURCE": "blob:https://acct.blob.core.windows.net", "DRILL_ID": DRILL},           # no container
    {"EVENT_SOURCE": "blob:https://acct.blob.core.windows.net/evidence/", "DRILL_ID": DRILL},  # trailing slash
    {"EVENT_SOURCE": "blob:https://acct.blob.core.windows.net/a/b", "DRILL_ID": DRILL},
    {"EVENT_SOURCE": "blob:https://:pw@acct.blob.core.windows.net/evidence", "DRILL_ID": DRILL},
    {"EVENT_SOURCE": "blob:https://example.com/evidence", "DRILL_ID": DRILL},                 # not Azure Storage
    {"EVENT_SOURCE": "blob:https://acct.blob.core.windows.net:8443/evidence", "DRILL_ID": DRILL},
    {"METRICS_INTERVAL_SECONDS": "0"},
    {"METRICS_INTERVAL_SECONDS": "301"},
    {"METRICS_INTERVAL_SECONDS": "ten"},
])
def test_invalid_event_settings_are_refused(env):
    with pytest.raises(ConfigError):
        load_config({**BASE, **env})


def test_valid_event_settings():
    config = load_config({**BASE, "DRILL_ID": DRILL, "METRICS_INTERVAL_SECONDS": "10", "EVENT_SOURCE": BLOB})
    assert config.event_source == BLOB
    assert config.metrics_interval_seconds == 10
    assert parse_event_source(BLOB) == ("blob", "https://acct.blob.core.windows.net", "evidence")
    assert parse_event_source("dir:./evidence") == ("dir", "./evidence", "")


def test_event_source_without_a_drill_id_exits_with_code_2(caplog):
    assert entry.main(env={**BASE, "EVENT_SOURCE": "dir:./evidence"}) == 2
    assert "invalid configuration" in caplog.text


# ---- counting and lines ----

def make_reporter(sink, backlog_size=lambda: 0, interval=30):
    tally = OrderTally()
    return tally, OrderEventReporter(sink, DRILL, tally, backlog_size, interval)


def test_one_line_per_window_with_all_six_keys():
    sink = MemorySink()
    tally, reporter = make_reporter(sink, backlog_size=lambda: 3)
    reporter.start(0.0)
    for _ in range(15):
        tally.sent(kind="new", ok=True)
    reporter.tick(29.0)
    assert sink.events == []
    reporter.tick(30.0)
    drill_id, event = sink.events[0]
    assert drill_id == DRILL
    assert set(event) == {"ts", "drill_id", "action", "result", "details"}
    assert (event["drill_id"], event["action"], event["result"]) == (DRILL, "metrics.orders", "ok")
    assert event["ts"].endswith("Z")
    assert event["details"] == {"orders_per_min": 30.0, "failed_total": 0, "backlog": 3,
                                "recovered_total": 0, "dropped_total": 0, "window_s": 30}
    reporter.tick(45.0)
    assert len(sink.events) == 1
    reporter.tick(60.0)
    assert len(sink.events) == 2
    assert details(sink)[1]["orders_per_min"] == 0.0


def test_failed_total_counts_each_new_order_once():
    sink = MemorySink()
    tally, reporter = make_reporter(sink)
    reporter.start(0.0)
    tally.sent(kind="new", ok=False)
    tally.sent(kind="retry", ok=False)
    tally.sent(kind="retry", ok=False)
    tally.dropped("backlog_full")
    reporter.tick(30.0)
    assert details(sink)[0] == {"orders_per_min": 0.0, "failed_total": 1, "backlog": 0,
                                "recovered_total": 0, "dropped_total": 1, "window_s": 30}


def test_a_later_success_counts_as_recovered_and_as_placed():
    sink = MemorySink()
    tally, reporter = make_reporter(sink)
    reporter.start(0.0)
    tally.sent(kind="new", ok=False)
    tally.sent(kind="retry", ok=True)
    reporter.tick(30.0)
    d = details(sink)[0]
    assert (d["failed_total"], d["recovered_total"], d["orders_per_min"]) == (1, 1, 2.0)


def test_close_writes_a_last_line_for_the_part_window():
    sink = MemorySink()
    tally, reporter = make_reporter(sink)
    reporter.start(0.0)
    tally.sent(kind="new", ok=True)
    reporter.close(10.0)
    assert details(sink) == [{"orders_per_min": 6.0, "failed_total": 0, "backlog": 0,
                              "recovered_total": 0, "dropped_total": 0, "window_s": 10}]


def test_a_very_short_last_window_is_merged_with_the_one_before():
    sink = MemorySink()
    tally, reporter = make_reporter(sink)
    reporter.start(0.0)
    for _ in range(15):
        tally.sent(kind="new", ok=True)
    reporter.tick(30.0)
    tally.sent(kind="new", ok=True)
    reporter.close(30.05)
    assert len(sink.events) == 2
    last = details(sink)[1]
    assert last["orders_per_min"] == pytest.approx(16 * 60 / 30.05, abs=0.1)     # not 1 order in 0.05 s
    assert last["window_s"] == 30


def test_close_right_after_an_empty_window():
    sink = MemorySink()
    _, reporter = make_reporter(sink)
    reporter.start(0.0)
    reporter.close(0.0)
    assert details(sink)[0]["orders_per_min"] == 0.0 and details(sink)[0]["window_s"] == 0


# ---- the queued writer ----

def test_a_failed_write_logs_a_warning_and_the_load_carries_on(caplog):
    caplog.set_level(logging.WARNING, logger="loadgen")
    tally, reporter = make_reporter(QueuedSink(MemorySink(fail=True)))
    reporter.start(0.0)
    tally.sent(kind="new", ok=True)
    reporter.tick(30.0)
    reporter.close(31.0)
    assert "could not write metrics.orders: OSError: disk full" in caplog.text


class GatedSink(MemorySink):
    """A store that does not answer until the test opens the gate."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()

    def append(self, drill_id, event):
        self.gate.wait(5)
        super().append(drill_id, event)


def test_a_slow_store_never_holds_up_the_orders():
    store = GatedSink()
    sink = QueuedSink(store)
    for i in range(3):
        sink.append(DRILL, {"n": i})     # returns at once although the store has not answered
    assert store.events == []
    store.gate.set()
    sink.close(timeout=5)
    assert [e["n"] for _, e in store.events] == [0, 1, 2]


def test_close_gives_up_after_its_timeout(caplog):
    caplog.set_level(logging.WARNING, logger="loadgen")
    store = GatedSink()
    sink = QueuedSink(store)
    sink.append(DRILL, {})
    sink.close(timeout=0.2)
    assert "did not finish" in caplog.text
    store.gate.set()


def test_close_waits_at_most_its_timeout_even_with_a_full_queue(caplog):
    caplog.set_level(logging.WARNING, logger="loadgen")
    store = GatedSink()
    sink = QueuedSink(store, size=1)
    sink.append(DRILL, {})
    sink.append(DRILL, {})               # the worker holds one line, the queue holds the other
    started = time.monotonic()
    sink.close(timeout=0.3)
    assert time.monotonic() - started < 2.0     # not twice the timeout
    assert "did not finish" in caplog.text
    store.gate.set()


def test_a_multi_line_store_error_is_logged_on_one_line(caplog):
    caplog.set_level(logging.WARNING, logger="loadgen")

    class Noisy:
        def append(self, drill_id, event):
            raise OSError("denied\nRequestId:1\nErrorCode:AuthorizationFailure")

    sink = QueuedSink(Noisy())
    sink.append(DRILL, {})
    sink.close(timeout=5)
    assert "OSError: denied RequestId:1 ErrorCode:AuthorizationFailure" in caplog.text


def test_a_full_queue_drops_the_line_with_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="loadgen")
    blocker = threading.Event()

    class Stuck:
        def append(self, drill_id, event):
            blocker.wait(5)

    sink = QueuedSink(Stuck(), size=1)
    for _ in range(4):
        sink.append(DRILL, {})
    assert "the write queue is full" in caplog.text
    blocker.set()
    sink.close(timeout=5)


# ---- the runner ----

class ScriptedClient:
    def __init__(self, results):
        self.results = list(results)

    def place(self, sku):
        return self.results.pop(0) if self.results else OK


class FakeStop:
    def __init__(self, clock):
        self.clock = clock

    def is_set(self):
        return False

    def wait(self, seconds):
        self.clock["t"] += seconds
        return False


def run_with_events(meter, results, duration="65", **env):
    config = load_config({**BASE, "DURATION_SECONDS": duration, **env})
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    tally, sink = OrderTally(), MemorySink()
    reporter = OrderEventReporter(sink, DRILL, tally, lambda: len(backlog), 30)
    metrics = entry.FanoutMetrics(Metrics(meter, lambda: len(backlog)), tally)
    runner = LoadRunner(config, ScriptedClient(results), backlog, metrics, reporter=reporter)
    clock = {"t": 0.0}
    runner.run(stop=FakeStop(clock), clock=lambda: clock["t"])
    return details(sink)


def test_the_runner_reports_while_it_runs_and_when_it_ends(meter):
    lines = run_with_events(meter, [DOWN])
    assert len(lines) == 3                      # at 30 s, 60 s, and the last one when the run ends
    assert lines[0]["failed_total"] == 1 and lines[0]["recovered_total"] == 1
    assert meter.counters["loadgen_orders_sent"].total(kind="new", result="failed") == 1


def test_a_non_retryable_new_failure_counts_as_failed_and_dropped(meter):
    lines = run_with_events(meter, [BAD], duration="5")
    assert (lines[-1]["failed_total"], lines[-1]["dropped_total"], lines[-1]["recovered_total"]) == (1, 1, 0)


def test_a_retry_that_fails_and_is_then_dropped(meter):
    config = load_config(BASE)
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    tally, sink = OrderTally(), MemorySink()
    reporter = OrderEventReporter(sink, DRILL, tally, lambda: len(backlog), 30)
    runner = LoadRunner(config, ScriptedClient([DOWN, OK, BAD]), backlog, tally, reporter=reporter)
    reporter.start(0.0)
    runner.tick(0.0)          # new order fails and waits in the backlog
    runner.tick(1000.0)       # next new order works; the retry, now due, fails for good
    reporter.close(1000.0)
    d = details(sink)[-1]
    assert (d["failed_total"], d["dropped_total"], d["recovered_total"], d["backlog"]) == (1, 1, 0, 0)


def test_late_ticks_still_give_one_line_per_window(meter):
    config = load_config({**BASE, "RATE_PER_MINUTE": "1", "DURATION_SECONDS": "200"})   # one tick a minute
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    tally, sink = OrderTally(), MemorySink()
    reporter = OrderEventReporter(sink, DRILL, tally, lambda: 0, 30)
    runner = LoadRunner(config, ScriptedClient([]), backlog, tally, reporter=reporter)
    clock = {"t": 0.0}
    runner.run(stop=FakeStop(clock), clock=lambda: clock["t"])
    lines = details(sink)
    # ticks at 0, 60, 120, 180; the run ends at the next slot (240). A window is as long as the ticks it waited for.
    assert [d["window_s"] for d in lines] == [60, 60, 60, 60]
    assert [d["orders_per_min"] for d in lines] == [2.0, 1.0, 1.0, 0.0]


def test_the_runner_writes_a_last_line_when_stopped(meter):
    config = load_config(BASE)
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    sink = MemorySink()
    reporter = OrderEventReporter(sink, DRILL, OrderTally(), lambda: 0, 30)
    runner = LoadRunner(config, ScriptedClient([]), backlog, Metrics(meter, lambda: 0), reporter=reporter)
    stop = threading.Event()
    stop.set()                                   # what SIGTERM does
    runner.run(stop=stop)
    assert len(sink.events) == 1


# ---- sinks ----

def test_dir_sink_appends_json_lines(tmp_path):
    sink = DirSink(str(tmp_path))
    sink.append(DRILL, {"ts": "t", "action": "metrics.orders"})
    sink.append(DRILL, {"ts": "u", "action": "metrics.orders"})
    lines = (tmp_path / DRILL / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["ts"] for line in lines] == ["t", "u"]
    assert lines[0] == '{"ts":"t","action":"metrics.orders"}'


def test_dir_sink_refuses_a_bad_drill_id(tmp_path):
    with pytest.raises(ValueError):
        DirSink(str(tmp_path)).append("../escape", {})


class FakeContainer:
    def __init__(self, race=False):
        self.store, self.race, self.creates = {}, race, 0

    def get_blob_client(self, name):
        container = self

        class Blob:
            def create_append_blob(self, **kwargs):
                assert kwargs.get("if_none_match") == "*"       # never replaces a blob another writer made
                container.creates += 1
                if container.race or name in container.store:
                    raise ResourceExistsError("exists")
                container.store[name] = b""

            def append_block(self, data):
                container.store[name] = container.store.get(name, b"") + data

        return Blob()


def test_blob_sink_creates_the_append_blob_once_and_appends():
    container = FakeContainer()
    sink = BlobSink(container)
    sink.append(DRILL, {"a": 1})
    sink.append(DRILL, {"a": 2})
    assert container.store[f"{DRILL}/events.jsonl"] == b'{"a":1}\n{"a":2}\n'
    assert container.creates == 1


def test_blob_sink_appends_when_another_writer_created_the_blob_first():
    container = FakeContainer(race=True)
    BlobSink(container).append(DRILL, {"a": 1})
    assert container.store[f"{DRILL}/events.jsonl"] == b'{"a":1}\n'


def test_sink_from_source(tmp_path):
    assert isinstance(sink_from_source(f"dir:{tmp_path}"), QueuedSink)
    made = {}

    def factory(url, container, client_id):
        made.update(url=url, container=container, client_id=client_id)
        return FakeContainer()

    assert isinstance(sink_from_source(BLOB, "client-1", container_factory=factory), QueuedSink)
    assert made == {"url": "https://acct.blob.core.windows.net", "container": "evidence", "client_id": "client-1"}


def test_the_blob_client_uses_the_jobs_identity_and_short_timeouts(monkeypatch):
    import azure.identity
    import azure.storage.blob
    seen = {}

    def credential(client_id=None):
        return ("mi", client_id)

    def container_client(url, container, credential, **options):
        seen.update(url=url, container=container, credential=credential, options=options)
        return "client"

    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", credential)
    monkeypatch.setattr(azure.storage.blob, "ContainerClient", container_client)
    assert events._managed_identity_container("https://acct.blob.core.windows.net", "evidence", "client-1") == "client"
    assert seen == {"url": "https://acct.blob.core.windows.net", "container": "evidence", "credential": ("mi", "client-1"),
                    "options": {"connection_timeout": 5, "read_timeout": 10, "retry_total": 0}}


class Response:
    status = 201

    def read(self, amt=None):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_main_writes_metrics_lines_to_a_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(entry, "DEFAULT_OPENER", lambda request, timeout: Response())
    env = {"ORDER_APP_URL": "http://127.0.0.1:9", "RATE_PER_MINUTE": "600", "DURATION_SECONDS": "0.3",
           "DRILL_ID": DRILL, "EVENT_SOURCE": f"dir:{tmp_path}", "METRICS_INTERVAL_SECONDS": "1"}
    assert entry.main(env=env) == 0
    lines = [json.loads(line) for line in (tmp_path / DRILL / "events.jsonl").read_text().splitlines()]
    assert lines and all(e["action"] == "metrics.orders" and set(e["details"]) == KEYS for e in lines)
    assert lines[-1]["details"]["orders_per_min"] > 0


def test_main_with_blob_uses_the_jobs_identity(monkeypatch):
    monkeypatch.setattr(entry, "DEFAULT_OPENER", lambda request, timeout: Response())
    container, seen = FakeContainer(), {}

    def factory(url, name, client_id):
        seen["client_id"] = client_id
        return container

    monkeypatch.setattr(events, "_managed_identity_container", factory)
    env = {"ORDER_APP_URL": "http://127.0.0.1:9", "RATE_PER_MINUTE": "600", "DURATION_SECONDS": "0.2",
           "DRILL_ID": DRILL, "EVENT_SOURCE": BLOB, "AZURE_CLIENT_ID": "client-1"}
    assert entry.main(env=env) == 0
    assert seen["client_id"] == "client-1"
    assert b'"action":"metrics.orders"' in container.store[f"{DRILL}/events.jsonl"]


def test_main_runs_the_orders_when_the_event_store_cannot_be_opened(monkeypatch, caplog):
    monkeypatch.setattr(entry, "DEFAULT_OPENER", lambda request, timeout: Response())

    def broken(url, name, client_id):
        raise ImportError("no azure")

    monkeypatch.setattr(events, "_managed_identity_container", broken)
    env = {"ORDER_APP_URL": "http://127.0.0.1:9", "RATE_PER_MINUTE": "600", "DURATION_SECONDS": "0.1",
           "DRILL_ID": DRILL, "EVENT_SOURCE": BLOB}
    assert entry.main(env=env) == 0
    assert "metrics.orders off: could not open the event store: ImportError" in caplog.text


def test_the_last_line_is_written_even_if_the_loop_fails(meter):
    class Broken:
        def place(self, sku):
            raise RuntimeError("boom")

    config = load_config(BASE)
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    sink = MemorySink()
    reporter = OrderEventReporter(sink, DRILL, OrderTally(), lambda: 0, 30)
    runner = LoadRunner(config, Broken(), backlog, Metrics(meter, lambda: 0), reporter=reporter)
    with pytest.raises(RuntimeError):
        runner.run(stop=threading.Event())
    assert len(sink.events) == 1
