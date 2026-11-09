"""The drill event store the audit trail is written to: a local folder, or Blob storage in Azure (faked here)."""
import json

import pytest

import livefire_events as ev

EVENT = {"ts": "2026-11-08T10:00:00Z", "drill_id": "drill-a", "action": "planner.tool_call", "result": "allow"}


class FakeBlob:
    def __init__(self, blobs, name):
        self.blobs, self.name = blobs, name

    def exists(self):
        return self.name in self.blobs

    def create_append_blob(self):
        self.blobs[self.name] = b""

    def append_block(self, data):
        self.blobs[self.name] += data

    def download_blob(self):
        data = self.blobs[self.name]
        return type("Download", (), {"readall": lambda _self: data})()


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    def get_blob_client(self, name):
        return FakeBlob(self.blobs, name)

    def list_blobs(self):
        return [type("Blob", (), {"name": n})() for n in self.blobs]


def blob_store():
    store = ev.BlobEventStore.__new__(ev.BlobEventStore)
    store.container = FakeContainer()
    return store


def test_blob_store_creates_the_append_blob_once_and_reads_events_back():
    store = blob_store()
    assert store.read("drill-a") == [] and store.list_drills() == []
    store.append("drill-a", EVENT)
    store.append("drill-a", {**EVENT, "result": "deny"})
    assert [e["result"] for e in store.read("drill-a")] == ["allow", "deny"]
    assert store.list_drills() == ["drill-a"]


def test_blob_store_serves_only_the_sealed_package_file():
    store = blob_store()
    assert store.read_file("drill-a", "package.json") is None
    store.container.blobs["drill-a/package.json"] = b"{}"
    assert store.read_file("drill-a", "package.json") == b"{}"
    with pytest.raises(ValueError):
        store.read_file("drill-a", "events.jsonl")


@pytest.mark.parametrize("call", [lambda s: s.append("../x", EVENT), lambda s: s.read("not-a-drill")])
def test_blob_store_refuses_a_bad_drill_id(call):
    with pytest.raises(ValueError):
        call(blob_store())


def test_dir_store_lists_drills_reads_events_and_skips_half_written_lines(tmp_path):
    store = ev.DirEventStore(str(tmp_path))
    assert store.list_drills() == [] and store.read("drill-a") == []
    store.append("drill-a", EVENT)
    with (tmp_path / "drill-a" / "events.jsonl").open("a") as f:
        f.write('{"ts": "2026-11-08T10:00:01Z", "act')               # a writer mid-line
    assert store.read("drill-a") == [EVENT] and store.list_drills() == ["drill-a"]
    assert store.read_file("drill-a", "package.json") is None
    (tmp_path / "drill-a" / "package.json").write_text(json.dumps({"ok": True}))
    assert json.loads(store.read_file("drill-a", "package.json")) == {"ok": True}
    with pytest.raises(ValueError):
        store.read_file("drill-a", "../../etc/passwd")


def test_store_from_env_picks_the_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("EVENT_SOURCE", f"dir:{tmp_path}")
    assert isinstance(ev.store_from_env(), ev.DirEventStore)
    monkeypatch.setenv("EVENT_SOURCE", "ftp://nope")
    with pytest.raises(ValueError):
        ev.store_from_env()
