"""evidence_unlock.py, driven through a fake blob container that answers like Azure (no Azure needed)."""
import json
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evidence_unlock.py"
VALUES = {"EVIDENCE_BLOB_URL": "https://stlfevtest.blob.core.windows.net/evidence", "CONTROL_RG": "rg-lf-control-test"}


class FakeHttpError(Exception):
    """Stands in for azure.core.exceptions.HttpResponseError."""

    def __init__(self, status_code, error_code):
        super().__init__(error_code)
        self.status_code, self.error_code = status_code, error_code


class FakeNotFound(FakeHttpError):
    """Stands in for azure.core.exceptions.ResourceNotFoundError, a kind of HttpResponseError as in azure-core."""

    def __init__(self, what):
        super().__init__(404, "BlobNotFound")


class Version:
    def __init__(self, version_id, current, policy=True, locked=False, hold=False, busy=False):
        self.version_id, self.current, self.policy, self.locked = version_id, current, policy, locked
        self.hold, self.busy = hold, busy  # busy: every delete by id answers 503


class FakeContainer:
    """A versioned container with version-level immutability. A current version can't be deleted by its id
    (403 OperationNotAllowedOnRootBlob); deleting the blob itself keeps the current version as a previous one."""

    def __init__(self, blobs, gone=False):
        self.blobs, self.gone = blobs, gone  # name -> [Version]; gone: the container was already deleted

    def exists(self):
        return not self.gone

    def list_blobs(self, include=None):
        if self.gone:
            raise FakeNotFound("ContainerNotFound")
        return [types.SimpleNamespace(name=name, version_id=v.version_id, is_current_version=v.current,
                                      immutability_policy=types.SimpleNamespace(
                                          expiry_time="2026-11-07T00:00:00Z" if v.policy else None),
                                      has_legal_hold=v.hold)
                for name, versions in self.blobs.items() for v in list(versions)]

    def get_blob_client(self, name):
        return FakeBlob(self, name)

    def versions_left(self):
        return sum(len(v) for v in self.blobs.values())


class FakeBlob:
    def __init__(self, container, name):
        self.container, self.name = container, name

    def _version(self, version_id):
        for v in self.container.blobs.get(self.name, []):
            if v.version_id == version_id:
                return v
        raise FakeNotFound(version_id)

    def delete_immutability_policy(self, version_id):
        v = self._version(version_id)
        if v.locked:
            raise FakeHttpError(409, "ImmutabilityPolicyLocked")
        v.policy = False

    def set_legal_hold(self, hold, version_id):
        self._version(version_id).hold = hold

    def delete_blob(self, version_id=None):
        versions = self.container.blobs.get(self.name, [])
        if version_id is None:
            current = next((v for v in versions if v.current), None)
            if current is None:
                raise FakeNotFound(self.name)
            if current.policy or current.hold:
                raise FakeHttpError(409, "BlobImmutableDueToPolicy")
            current.current = False
            return
        v = self._version(version_id)
        if v.current:
            raise FakeHttpError(403, "OperationNotAllowedOnRootBlob")
        if v.policy or v.hold:
            raise FakeHttpError(409, "BlobImmutableDueToPolicy")
        if v.busy:
            raise FakeHttpError(503, "ServerBusy")
        versions.remove(v)


@pytest.fixture
def run_unlock(monkeypatch, capsys):
    def run(container, *args):
        exceptions = types.ModuleType("azure.core.exceptions")
        exceptions.ResourceNotFoundError, exceptions.HttpResponseError = FakeNotFound, FakeHttpError
        identity = types.ModuleType("azure.identity")
        identity.AzureCliCredential = lambda: object()
        blob = types.ModuleType("azure.storage.blob")
        blob.ContainerClient = lambda *_a, **_k: container
        for name, module in {"azure": types.ModuleType("azure"), "azure.core": types.ModuleType("azure.core"),
                             "azure.core.exceptions": exceptions, "azure.identity": identity,
                             "azure.storage": types.ModuleType("azure.storage"), "azure.storage.blob": blob}.items():
            monkeypatch.setitem(sys.modules, name, module)

        calls = []

        def fake_run(cmd, **_kwargs):  # azd env get-values, then az: the container's default policy is already gone
            calls.append(cmd)
            out = json.dumps(VALUES) if cmd[0] == "azd" else ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), *args])
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
            code = 0
        except SystemExit as stop:
            code = stop.code
        return types.SimpleNamespace(code=code, out=capsys.readouterr().out, calls=calls)
    return run


def test_without_yes_it_only_prints_the_usage(run_unlock):
    container = FakeContainer({"d/events.jsonl": [Version("v1", current=True)]})
    result = run_unlock(container)
    assert result.code == 2
    assert container.versions_left() == 1


def test_it_empties_the_container_including_current_versions(run_unlock):
    container = FakeContainer({
        "d/events.jsonl": [Version("v1", current=True)],
        "d/r1-baseline/referee-result.json": [Version("v1", current=False), Version("v2", current=True)],
    })
    result = run_unlock(container, "--yes")
    assert result.code == 0, result.out
    assert container.versions_left() == 0
    assert "version policies removed: 3, versions deleted: 3, versions left: 0, failures: 0" in result.out


def test_an_empty_container_is_deleted_so_azd_down_can_delete_the_account(run_unlock):
    result = run_unlock(FakeContainer({"d/events.jsonl": [Version("v1", current=True)]}), "--yes")
    assert result.code == 0, result.out
    assert ["az", "storage", "container-rm", "delete", "--storage-account", "stlfevtest", "-g", "rg-lf-control-test",
            "-n", "evidence", "--yes", "-o", "none"] in result.calls


def test_a_legal_hold_is_released_before_the_delete(run_unlock):
    container = FakeContainer({"d/events.jsonl": [Version("v1", current=True, policy=False, hold=True)]})
    result = run_unlock(container, "--yes")
    assert result.code == 0, result.out
    assert container.versions_left() == 0


def test_a_rerun_after_the_container_is_gone_exits_zero(run_unlock):
    result = run_unlock(FakeContainer({}, gone=True), "--yes")
    assert result.code == 0, result.out
    assert "already gone" in result.out
    assert not [c for c in result.calls if "container-rm" in c]


def test_versions_still_there_at_the_end_exit_one(run_unlock):
    container = FakeContainer({"d/events.jsonl": [Version("v1", current=True, busy=True)]})
    result = run_unlock(container, "--yes")
    assert result.code == 1
    assert "versions left: 1" in result.out
    assert not [c for c in result.calls if "container-rm" in c]


def test_a_version_it_cannot_unlock_is_reported_and_exits_one(run_unlock):
    container = FakeContainer({
        "d/events.jsonl": [Version("v1", current=True, locked=True)],
        "d/step.txt": [Version("v1", current=True)],
    })
    result = run_unlock(container, "--yes")
    assert result.code == 1
    assert "could not clear d/events.jsonl" in result.out
    assert container.blobs["d/step.txt"] == []
