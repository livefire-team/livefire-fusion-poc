"""Load generator metrics and logs, exported through Azure Monitor OpenTelemetry when configured."""
import logging
from collections.abc import Callable, Mapping

from opentelemetry.metrics import Observation

log = logging.getLogger("loadgen")


def _configure_azure_monitor(**kwargs) -> None:
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(**kwargs)


def setup_telemetry(env: Mapping[str, str]) -> bool:
    """Send logs and metrics to Application Insights when APPLICATIONINSIGHTS_CONNECTION_STRING is set."""
    if not env.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return False
    _configure_azure_monitor(logger_name="loadgen")
    return True


class Metrics:
    """loadgen_orders_sent{kind,result}, loadgen_orders_dropped{reason} and the loadgen_backlog_size gauge."""

    def __init__(self, meter, backlog_size: Callable[[], int]):
        self._sent = meter.create_counter(
            "loadgen_orders_sent", unit="1", description="Order requests sent, by kind (new/retry) and result")
        self._dropped = meter.create_counter(
            "loadgen_orders_dropped", unit="1", description="Orders given up on, by reason")
        meter.create_observable_gauge(
            "loadgen_backlog_size", callbacks=[lambda _options: [Observation(backlog_size())]],
            unit="1", description="Failed orders waiting to be retried")

    def sent(self, kind: str, ok: bool) -> None:
        self._sent.add(1, {"kind": kind, "result": "ok" if ok else "failed"})

    def dropped(self, reason: str) -> None:
        self._dropped.add(1, {"reason": reason})


def log_status(sent: int, backlog: int, dropped: int) -> None:
    log.info("loadgen status sent=%d backlog=%d dropped=%d", sent, backlog, dropped,
             extra={"sent": sent, "backlog": backlog, "dropped": dropped})
