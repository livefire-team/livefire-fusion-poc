"""metrics.orders lines in the drill's event log (ADR-021), next to the App Insights metrics.

Each line has the shape every drill event writer uses, `{"ts", "drill_id", "action", "result", "details"}`, in
`<drill-id>/events.jsonl` under a local folder (`dir:<path>`) or a Blob container (`blob:https://<account>/<container>`).
Lines are written by a background thread, so a slow or unreachable store never holds up the orders.
"""
import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# The event store's rule for a drill ID ("drill-" plus up to 64 characters). config.DRILL_ID_PATTERN is checked first
# and limits the whole ID to 64 characters.
EVENT_DRILL_ID = re.compile(r"drill-[A-Za-z0-9-]{1,64}")
BLOB_HOST_SUFFIX = ".blob.core.windows.net"
ACTION = "metrics.orders"
MIN_WINDOW_SECONDS = 1.0        # a shorter last window is merged with the one before, so its rate isn't inflated
QUEUE_SIZE = 100
FLUSH_SECONDS = 10.0            # the most close() waits for queued lines on shutdown
# No SDK retries: an append that timed out may still have landed, and a retry would write the line twice. A lost line
# costs little, because every line carries running totals.
BLOB_CLIENT_OPTIONS = {"connection_timeout": 5, "read_timeout": 10, "retry_total": 0}
log = logging.getLogger("loadgen")


def parse_event_source(raw: str) -> tuple[str, str, str]:
    """('dir', path, '') or ('blob', account_url, container). Raises ValueError with a readable message."""
    if raw.startswith("dir:"):
        if not raw[4:]:
            raise ValueError("EVENT_SOURCE dir: needs a path")
        return "dir", raw[4:], ""
    if raw.startswith("blob:"):
        parts = urlsplit(raw[5:])
        container = parts.path[1:] if parts.path.startswith("/") else ""
        host = parts.hostname or ""
        if (parts.scheme != "https" or "@" in parts.netloc or parts.port is not None or parts.query
                or parts.fragment or not host.endswith(BLOB_HOST_SUFFIX) or host == BLOB_HOST_SUFFIX[1:]
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", container)):
            raise ValueError("EVENT_SOURCE blob: must be blob:https://<account>.blob.core.windows.net/<container>")
        return "blob", f"https://{host}", container
    raise ValueError("EVENT_SOURCE must be dir:<path> or blob:https://<account>.blob.core.windows.net/<container>")


def _line(event: dict) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"


def _blob_name(drill_id: str) -> str:
    if not EVENT_DRILL_ID.fullmatch(drill_id):
        raise ValueError("invalid drill id")
    return f"{drill_id}/events.jsonl"


class DirSink:
    """Appends to <root>/<drill-id>/events.jsonl, the format WS2's scripts and the Ops Service write."""

    def __init__(self, root: str):
        self._root = Path(root)

    def append(self, drill_id: str, event: dict) -> None:
        path = self._root / _blob_name(drill_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(_line(event))


class BlobSink:
    """Appends to <container>/<drill-id>/events.jsonl, creating the append blob if no writer has yet."""

    def __init__(self, container):
        self._container = container
        self._created: set[str] = set()

    def append(self, drill_id: str, event: dict) -> None:
        from azure.core.exceptions import ResourceExistsError
        name = _blob_name(drill_id)
        blob = self._container.get_blob_client(name)
        if name not in self._created:
            try:
                blob.create_append_blob(if_none_match="*")      # never replaces a log another writer started
            except ResourceExistsError:
                pass
            self._created.add(name)
        blob.append_block(_line(event).encode("utf-8"))


class QueuedSink:
    """Hands lines to a background thread. append() never blocks; a full queue drops the line with a warning."""

    def __init__(self, sink, size: int = QUEUE_SIZE):
        self._sink = sink
        self._queue: queue.Queue = queue.Queue(maxsize=size)
        self._thread = threading.Thread(target=self._work, name="metrics-orders-writer", daemon=True)
        self._thread.start()

    def append(self, drill_id: str, event: dict) -> None:
        try:
            self._queue.put_nowait((drill_id, event))
        except queue.Full:
            log.warning("could not write metrics.orders: the write queue is full")

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                self._sink.append(*item)
            except Exception as exc:   # the load matters more than one line of its report
                text = " ".join(str(exc).split())[:200]      # one log line, however the SDK formats its errors
                log.warning("could not write metrics.orders: %s: %s", type(exc).__name__, text)

    def close(self, timeout: float = FLUSH_SECONDS) -> None:
        """Writes what is queued, waiting at most `timeout` seconds (the job's shutdown grace is limited)."""
        deadline = time.monotonic() + timeout
        try:
            self._queue.put(None, timeout=timeout)
            self._thread.join(max(0.0, deadline - time.monotonic()))
        except queue.Full:
            pass
        if self._thread.is_alive():
            log.warning("could not write metrics.orders: the last lines did not finish within %.0f s", timeout)


def _managed_identity_container(account_url: str, container: str, client_id: str | None):
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import ContainerClient
    credential = ManagedIdentityCredential(client_id=client_id)
    return ContainerClient(account_url, container, credential=credential, **BLOB_CLIENT_OPTIONS)


def sink_from_source(source: str, client_id: str | None = None,
                     container_factory: Callable | None = None) -> QueuedSink:
    """EVENT_SOURCE (already validated by load_config) as a queued sink."""
    kind, target, container = parse_event_source(source)
    if kind == "dir":
        return QueuedSink(DirSink(target))
    factory = container_factory or _managed_identity_container
    return QueuedSink(BlobSink(factory(target, container, client_id)))


class OrderTally:
    """Counts orders the way the Control Center's tiles read them; takes the same calls as telemetry.Metrics.

    Used only from the order loop's thread (the writer thread receives finished lines, never this object).
    """

    def __init__(self):
        self.placed_in_window = 0
        self.failed_total = 0
        self.recovered_total = 0
        self.dropped_total = 0

    def sent(self, kind: str, ok: bool) -> None:
        if ok:
            self.placed_in_window += 1
            if kind == "retry":
                self.recovered_total += 1
        elif kind == "new":
            self.failed_total += 1

    def dropped(self, reason: str) -> None:
        self.dropped_total += 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OrderEventReporter:
    """Writes one metrics.orders line every `interval` seconds while the run lasts, and a last one when it ends."""

    def __init__(self, sink, drill_id: str, tally: OrderTally, backlog_size: Callable[[], int], interval: float,
                 now_iso: Callable[[], str] = _utc_now):
        self._sink = sink
        self._drill_id = drill_id
        self._tally = tally
        self._backlog_size = backlog_size
        self._interval = interval
        self._now_iso = now_iso
        self._window_start = 0.0
        self._previous = (0, 0.0)      # (orders placed, seconds) of the last window written

    def start(self, now: float) -> None:
        self._window_start = now

    def tick(self, now: float) -> None:
        if now - self._window_start >= self._interval:
            self._emit(now)

    def close(self, now: float) -> None:
        self._emit(now, last=True)
        closer = getattr(self._sink, "close", None)
        if closer:
            closer()

    def _emit(self, now: float, last: bool = False) -> None:
        t = self._tally
        placed, window = t.placed_in_window, max(0.0, now - self._window_start)
        if last and window < MIN_WINDOW_SECONDS:
            placed, window = placed + self._previous[0], window + self._previous[1]
        per_min = round(placed * 60.0 / window, 1) if window > 0 else 0.0
        details = {"orders_per_min": per_min, "failed_total": t.failed_total, "backlog": self._backlog_size(),
                   "recovered_total": t.recovered_total, "dropped_total": t.dropped_total,
                   "window_s": round(window)}
        self._previous = (t.placed_in_window, now - self._window_start)
        t.placed_in_window = 0
        self._window_start = now
        self._sink.append(self._drill_id, {"ts": self._now_iso(), "drill_id": self._drill_id, "action": ACTION,
                                           "result": "ok", "details": details})
