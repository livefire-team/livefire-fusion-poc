"""Entry point: `python -m loadgen`. Exit code 0 when the run ends, 2 for invalid settings."""
import logging
import os
import signal
import sys
import threading
import urllib.request
from collections.abc import Mapping

from opentelemetry import metrics

from loadgen.backlog import Backlog
from loadgen.client import OrderClient
from loadgen.config import ConfigError, load_config
from loadgen.events import OrderEventReporter, OrderTally, sink_from_source
from loadgen.runner import LoadRunner
from loadgen.telemetry import Metrics, setup_telemetry

DEFAULT_OPENER = urllib.request.urlopen
log = logging.getLogger("loadgen")


class FanoutMetrics:
    """Passes each count to every target: the App Insights metrics and, when enabled, the metrics.orders tally."""

    def __init__(self, *targets):
        self._targets = targets

    def sent(self, kind: str, ok: bool) -> None:
        for t in self._targets:
            t.sent(kind=kind, ok=ok)

    def dropped(self, reason: str) -> None:
        for t in self._targets:
            t.dropped(reason)


def _stop_on_signals(stop: threading.Event) -> dict:
    """Container Apps sends SIGTERM when a job execution is stopped: finish the current tick and exit."""
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}


def _open_event_store(source: str, client_id: str | None):
    """The metrics.orders sink, or None (with a warning) if it cannot be opened: the orders run either way."""
    try:
        return sink_from_source(source, client_id)
    except Exception as exc:
        log.warning("metrics.orders off: could not open the event store: %s", type(exc).__name__)
        return None


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.setLevel(logging.INFO)
    try:
        config = load_config(env)
    except ConfigError as exc:
        log.error("invalid configuration: %s", exc)
        return 2
    setup_telemetry(env)
    backlog = Backlog(config.max_backlog, config.retry_base_seconds, config.retry_max_seconds)
    client = OrderClient(config.order_app_url, config.drill_id, config.request_timeout_seconds, DEFAULT_OPENER)
    app_metrics = Metrics(metrics.get_meter("loadgen"), lambda: len(backlog))
    reporter = None
    sink = _open_event_store(config.event_source, env.get("AZURE_CLIENT_ID")) if config.event_source else None
    if sink is not None:
        tally = OrderTally()
        reporter = OrderEventReporter(sink, config.drill_id, tally, lambda: len(backlog),
                                      config.metrics_interval_seconds)
        app_metrics = FanoutMetrics(app_metrics, tally)
    runner = LoadRunner(config, client, backlog, app_metrics, reporter=reporter)
    stop = threading.Event()
    previous = _stop_on_signals(stop)
    log.info("loadgen starting", extra={"rate_per_minute": config.rate_per_minute, "skus": ",".join(config.skus)})
    try:
        runner.run(stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
