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
from loadgen.runner import LoadRunner
from loadgen.telemetry import Metrics, setup_telemetry

DEFAULT_OPENER = urllib.request.urlopen
log = logging.getLogger("loadgen")


def _stop_on_signals(stop: threading.Event) -> dict:
    """Container Apps sends SIGTERM when a job execution is stopped: finish the current tick and exit."""
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}


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
    runner = LoadRunner(config, client, backlog, Metrics(metrics.get_meter("loadgen"), lambda: len(backlog)))
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
