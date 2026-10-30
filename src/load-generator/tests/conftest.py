import os

import pytest

# Unit tests never send telemetry to Azure.
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)


class FakeCounter:
    def __init__(self):
        self.calls = []

    def add(self, amount, attributes=None):
        self.calls.append((amount, dict(attributes or {})))

    def total(self, **attributes):
        return sum(a for a, attrs in self.calls if all(attrs.get(k) == v for k, v in attributes.items()))


class FakeMeter:
    def __init__(self):
        self.counters = {}
        self.gauges = {}

    def create_counter(self, name, unit="", description=""):
        self.counters[name] = FakeCounter()
        return self.counters[name]

    def create_observable_gauge(self, name, callbacks=None, unit="", description=""):
        self.gauges[name] = list(callbacks or [])
        return object()


@pytest.fixture
def meter():
    return FakeMeter()
