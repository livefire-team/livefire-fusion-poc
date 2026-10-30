"""Settings for the load generator, read from environment variables and validated up front."""
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DRILL_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")   # same rule the order service applies to x-drill-id
SKU_PATTERN = re.compile(r"[A-Za-z0-9-]{1,32}")
MAX_RATE_PER_MINUTE = 600.0
MAX_BACKLOG_LIMIT = 100_000
MAX_RETRIES_PER_TICK = 100
DIGITS = re.compile(r"[0-9]+")
DEFAULT_SKUS = "SKU-001,SKU-002"


class ConfigError(ValueError):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class Config:
    order_app_url: str
    rate_per_minute: float
    skus: tuple[str, ...]
    drill_id: str | None
    max_backlog: int
    retries_per_tick: int
    retry_base_seconds: float
    retry_max_seconds: float
    request_timeout_seconds: float
    duration_seconds: float

    @property
    def interval_seconds(self) -> float:
        return 60.0 / self.rate_per_minute


def _number(env: Mapping[str, str], name: str, default: str, minimum: float, *, strict: bool) -> float:
    raw = env.get(name, default)
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value < minimum or (strict and value == minimum):
        op = ">" if strict else ">="
        raise ConfigError(f"{name} must be {op} {minimum:g}, got {raw!r}")
    return value


def _integer(env: Mapping[str, str], name: str, default: str, minimum: int, maximum: int) -> int:
    raw = env.get(name, default).strip()
    if not DIGITS.fullmatch(raw) or not minimum <= int(raw) <= maximum:
        raise ConfigError(f"{name} must be a whole number from {minimum} to {maximum}, got {raw!r}")
    return int(raw)


def _url(env: Mapping[str, str]) -> str:
    raw = env.get("ORDER_APP_URL", "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("ORDER_APP_URL must be an http(s) URL with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("ORDER_APP_URL must not contain credentials, a query or a fragment")
    return raw.rstrip("/")


def _skus(env: Mapping[str, str]) -> tuple[str, ...]:
    skus = tuple(s.strip() for s in env.get("SKUS", DEFAULT_SKUS).split(",") if s.strip())
    if not skus or not all(SKU_PATTERN.fullmatch(s) for s in skus):
        raise ConfigError("SKUS must be a comma-separated list of SKUs (letters, digits, hyphens)")
    return skus


def _drill_id(env: Mapping[str, str]) -> str | None:
    raw = env.get("DRILL_ID", "").strip()
    if not raw:
        return None
    if not DRILL_ID_PATTERN.fullmatch(raw):
        raise ConfigError("DRILL_ID must be 1-64 letters, digits or . _ : -")
    return raw


def load_config(env: Mapping[str, str]) -> Config:
    rate = _number(env, "RATE_PER_MINUTE", "30", 0.0, strict=True)
    if rate > MAX_RATE_PER_MINUTE:
        raise ConfigError(f"RATE_PER_MINUTE must be <= {MAX_RATE_PER_MINUTE:g}")
    base = _number(env, "RETRY_BASE_SECONDS", "2", 0.0, strict=True)
    cap = _number(env, "RETRY_MAX_SECONDS", "60", 0.0, strict=True)
    if cap < base:
        raise ConfigError("RETRY_MAX_SECONDS must be >= RETRY_BASE_SECONDS")
    return Config(
        order_app_url=_url(env),
        rate_per_minute=rate,
        skus=_skus(env),
        drill_id=_drill_id(env),
        max_backlog=_integer(env, "MAX_BACKLOG", "500", 1, MAX_BACKLOG_LIMIT),
        retries_per_tick=_integer(env, "RETRIES_PER_TICK", "5", 0, MAX_RETRIES_PER_TICK),
        retry_base_seconds=base,
        retry_max_seconds=cap,
        request_timeout_seconds=_number(env, "REQUEST_TIMEOUT_SECONDS", "10", 0.0, strict=True),
        duration_seconds=_number(env, "DURATION_SECONDS", "0", 0.0, strict=False),
    )
