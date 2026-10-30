import logging

from loadgen import telemetry
from loadgen.telemetry import Metrics, setup_telemetry


def test_metric_names_and_backlog_gauge(meter):
    Metrics(meter, backlog_size=lambda: 7)
    assert set(meter.counters) == {"loadgen_orders_sent", "loadgen_orders_dropped"}
    (callback,) = meter.gauges["loadgen_backlog_size"]
    (observation,) = list(callback(None))
    assert observation.value == 7


def test_record_helpers_add_attributes(meter):
    metrics = Metrics(meter, backlog_size=lambda: 0)
    metrics.sent(kind="retry", ok=False)
    metrics.dropped("backlog_full")
    assert meter.counters["loadgen_orders_sent"].calls == [(1, {"kind": "retry", "result": "failed"})]
    assert meter.counters["loadgen_orders_dropped"].calls == [(1, {"reason": "backlog_full"})]


def test_setup_is_skipped_without_a_connection_string(monkeypatch):
    called = []
    monkeypatch.setattr(telemetry, "_configure_azure_monitor", lambda **kw: called.append(kw))
    assert setup_telemetry({}) is False
    assert called == []


def test_setup_configures_azure_monitor_when_set(monkeypatch):
    called = []
    monkeypatch.setattr(telemetry, "_configure_azure_monitor", lambda **kw: called.append(kw))
    assert setup_telemetry({"APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=x"}) is True
    assert called == [{"logger_name": "loadgen"}]


def test_configure_azure_monitor_wrapper_calls_the_distro(monkeypatch):
    import azure.monitor.opentelemetry as distro

    called = []
    monkeypatch.setattr(distro, "configure_azure_monitor", lambda **kw: called.append(kw))
    telemetry._configure_azure_monitor(logger_name="loadgen")
    assert called == [{"logger_name": "loadgen"}]


def test_status_log_reports_counts(caplog):
    with caplog.at_level(logging.INFO, logger="loadgen"):
        telemetry.log_status(sent=10, backlog=2, dropped=1)
    assert "loadgen status" in caplog.text
    record = caplog.records[-1]
    assert (record.sent, record.backlog, record.dropped) == (10, 2, 1)
