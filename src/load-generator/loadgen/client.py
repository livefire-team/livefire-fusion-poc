"""HTTP client for the order service's `POST /api/orders`."""
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

RETRYABLE_STATUSES = frozenset({408, 429})


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    retryable: bool
    status: int | None
    reason: str | None


def _failure(status: int) -> OrderResult:
    retryable = status >= 500 or status in RETRYABLE_STATUSES or status < 400
    return OrderResult(ok=False, retryable=retryable, status=status, reason=f"http_{status}")


class OrderClient:
    def __init__(self, base_url: str, drill_id: str | None, timeout: float,
                 opener: Callable = urllib.request.urlopen):
        self._url = f"{base_url}/api/orders"   # base_url is validated as http(s) by load_config
        self._drill_id = drill_id
        self._timeout = timeout
        self._open = opener

    def _request(self, sku: str) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        if self._drill_id:
            headers["x-drill-id"] = self._drill_id
        body = json.dumps({"sku": sku}).encode()
        return urllib.request.Request(self._url, data=body, headers=headers, method="POST")

    def place(self, sku: str) -> OrderResult:
        try:
            with self._open(self._request(sku), timeout=self._timeout) as response:
                response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            exc.close()
            return _failure(exc.code)
        except (urllib.error.URLError, OSError) as exc:   # refused, DNS, TLS, timeout
            return OrderResult(ok=False, retryable=True, status=None, reason=type(exc).__name__)
        if status == 201:
            return OrderResult(ok=True, retryable=False, status=status, reason=None)
        return _failure(status)
