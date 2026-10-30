import json

from loadgen import __main__ as entry


class FakeResponse:
    status = 201

    def read(self, amt=None):
        return json.dumps({"order_id": "x"}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_invalid_config_exits_with_code_2(caplog):
    assert entry.main(env={}) == 2
    assert "invalid configuration" in caplog.text


def test_runs_for_the_configured_duration(monkeypatch):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(entry, "DEFAULT_OPENER", opener)
    env = {"ORDER_APP_URL": "http://127.0.0.1:9", "RATE_PER_MINUTE": "600", "DURATION_SECONDS": "0.25"}
    assert entry.main(env=env) == 0
    assert calls and all(url == "http://127.0.0.1:9/api/orders" for url in calls)
