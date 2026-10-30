import io
import json
import urllib.error

import pytest

from loadgen.client import OrderClient, OrderResult


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code):
    return urllib.error.HTTPError("https://x/api/orders", code, "err", {}, io.BytesIO(b'{"error":"E"}'))


class Recorder:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_posts_the_sku_as_json_with_the_drill_header():
    opener = Recorder(FakeResponse(201, {"order_id": "abc", "confirmation": "LF-ABC"}))
    client = OrderClient("https://app.example.net", drill_id="drill-1", timeout=7.0, opener=opener)
    result = client.place("SKU-001")
    assert result == OrderResult(ok=True, retryable=False, status=201, reason=None)
    request, timeout = opener.requests[0]
    assert request.full_url == "https://app.example.net/api/orders"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"sku": "SKU-001"}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-drill-id") == "drill-1"
    assert timeout == 7.0


def test_no_drill_header_when_not_configured():
    opener = Recorder(FakeResponse(201, {}))
    OrderClient("https://app.example.net", drill_id=None, timeout=1.0, opener=opener).place("SKU-001")
    assert opener.requests[0][0].get_header("X-drill-id") is None


@pytest.mark.parametrize("code", [500, 502, 503, 504, 408, 429])
def test_server_errors_and_throttling_are_retryable(code):
    client = OrderClient("https://a", None, 1.0, opener=Recorder(http_error(code)))
    assert client.place("SKU-001") == OrderResult(ok=False, retryable=True, status=code, reason=f"http_{code}")


@pytest.mark.parametrize("code", [400, 404, 422])
def test_client_errors_are_not_retried(code):
    client = OrderClient("https://a", None, 1.0, opener=Recorder(http_error(code)))
    assert client.place("SKU-001") == OrderResult(ok=False, retryable=False, status=code, reason=f"http_{code}")


@pytest.mark.parametrize("exc", [urllib.error.URLError("refused"), TimeoutError(), ConnectionResetError()])
def test_network_errors_are_retryable(exc):
    client = OrderClient("https://a", None, 1.0, opener=Recorder(exc))
    result = client.place("SKU-001")
    assert (result.ok, result.retryable, result.status) == (False, True, None)
    assert result.reason == type(exc).__name__


def test_unexpected_success_status_is_treated_as_retryable():
    client = OrderClient("https://a", None, 1.0, opener=Recorder(FakeResponse(200, {})))
    assert client.place("SKU-001") == OrderResult(ok=False, retryable=True, status=200, reason="http_200")
