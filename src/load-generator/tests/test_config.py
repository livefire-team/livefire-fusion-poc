import pytest

from loadgen.config import Config, ConfigError, load_config

BASE = {"ORDER_APP_URL": "https://ca-order.example.net"}


def test_defaults_when_only_the_url_is_set():
    config = load_config(BASE)
    assert config == Config(
        order_app_url="https://ca-order.example.net",
        rate_per_minute=30.0,
        skus=("SKU-001", "SKU-002"),
        drill_id=None,
        max_backlog=500,
        retries_per_tick=5,
        retry_base_seconds=2.0,
        retry_max_seconds=60.0,
        request_timeout_seconds=10.0,
        duration_seconds=0.0,
    )


def test_reads_every_setting():
    env = {
        "ORDER_APP_URL": "http://127.0.0.1:8000/",
        "RATE_PER_MINUTE": "120",
        "SKUS": " SKU-002 , SKU-001 ",
        "DRILL_ID": "drill-42",
        "MAX_BACKLOG": "10",
        "RETRIES_PER_TICK": "3",
        "RETRY_BASE_SECONDS": "1",
        "RETRY_MAX_SECONDS": "8",
        "REQUEST_TIMEOUT_SECONDS": "5",
        "DURATION_SECONDS": "600",
    }
    config = load_config(env)
    assert config.order_app_url == "http://127.0.0.1:8000"
    assert config.rate_per_minute == 120.0
    assert config.skus == ("SKU-002", "SKU-001")
    assert config.drill_id == "drill-42"
    assert (config.max_backlog, config.retries_per_tick) == (10, 3)
    assert (config.retry_base_seconds, config.retry_max_seconds) == (1.0, 8.0)
    assert (config.request_timeout_seconds, config.duration_seconds) == (5.0, 600.0)


def test_interval_follows_the_rate():
    assert load_config({**BASE, "RATE_PER_MINUTE": "120"}).interval_seconds == 0.5


def test_empty_drill_id_means_none():
    assert load_config({**BASE, "DRILL_ID": ""}).drill_id is None


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"ORDER_APP_URL": ""},
        {"ORDER_APP_URL": "ftp://example.net"},
        {"ORDER_APP_URL": "file:///etc/passwd"},
        {"ORDER_APP_URL": "https://"},
        {"ORDER_APP_URL": "https://user:pw@example.net"},
        {"ORDER_APP_URL": "https://example.net/?q=1"},
        {**BASE, "RATE_PER_MINUTE": "0"},
        {**BASE, "RATE_PER_MINUTE": "601"},
        {**BASE, "RATE_PER_MINUTE": "fast"},
        {**BASE, "SKUS": " , "},
        {**BASE, "SKUS": "SKU-001,bad sku"},
        {**BASE, "DRILL_ID": "has space"},
        {**BASE, "DRILL_ID": "x" * 65},
        {**BASE, "MAX_BACKLOG": "0"},
        {**BASE, "MAX_BACKLOG": "1.5"},
        {**BASE, "MAX_BACKLOG": "٣٤"},
        {**BASE, "MAX_BACKLOG": "100001"},
        {**BASE, "RETRIES_PER_TICK": "٥"},
        {**BASE, "RETRIES_PER_TICK": "101"},
        {**BASE, "RETRIES_PER_TICK": "-1"},
        {**BASE, "RETRY_BASE_SECONDS": "0"},
        {**BASE, "RETRY_BASE_SECONDS": "10", "RETRY_MAX_SECONDS": "5"},
        {**BASE, "REQUEST_TIMEOUT_SECONDS": "0"},
        {**BASE, "DURATION_SECONDS": "-1"},
        {**BASE, "DURATION_SECONDS": "nan"},
    ],
)
def test_rejects_invalid_settings(env):
    with pytest.raises(ConfigError):
        load_config(env)
