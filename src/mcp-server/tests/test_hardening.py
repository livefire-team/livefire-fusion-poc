"""Review fixes for #40: protected paths, redaction before the size cut, and odd Authorization headers."""
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import Client

from guard import MAX_TEXT

APP = Path(__file__).resolve().parents[1] / "app"


class Store:
    def append(self, *args):
        pass


# ---------------------------------------------------------------- protected paths

@pytest.mark.parametrize("bad", ["referee/**", "referee/assert_order.py", "src/ops-service/ops/main.py", "docs/x.md",
                                 "azure.yaml", ".gitleaks.toml"])
def test_the_write_paths_setting_cannot_name_a_protected_path(bad):
    from engineer_tools import write_paths
    with pytest.raises(RuntimeError, match="ENGINEER_WRITE_PATHS"):
        write_paths(bad)


def test_the_server_refuses_to_start_on_a_protected_write_path():
    env = {**os.environ, "BACKEND": "fixtures", "AUTH_MODE": "key", "PLANNER_KEY": "p" * 40,
           "ENGINEER_KEY": "e" * 40, "RECOVERY_KEY": "r" * 40, "EVENT_SOURCE": "dir:/tmp/ws3-hardening",
           "ENGINEER_WRITE_PATHS": "referee/**"}
    out = subprocess.run([sys.executable, "-c", "import main"], cwd=APP, env=env, capture_output=True, text=True,
                         timeout=60)
    assert out.returncode != 0 and "ENGINEER_WRITE_PATHS" in out.stderr


# ---------------------------------------------------------------- redaction happens before the 20,000-character cut

KEY_BODY = "placeholder-not-a-key-" * 8                       # fake, low-entropy on purpose
KEY = "-----BEGIN " + "PRIVATE KEY-----\n" + KEY_BODY + "\n-----END " + "PRIVATE KEY-----\n"


def straddling_file() -> str:
    """A file whose private key starts before the cut and ends after it."""
    return "x" * (MAX_TEXT - 40) + "\n" + KEY + "y" * 100


class OneFile:
    def __init__(self, path, text):
        self.files = {path: text}

    def read_file(self, path, ref):
        return self.files[path]


def call(mcp, tool, args):
    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(tool, args)
    return json.loads(anyio.run(go).content[0].text)


def test_a_key_split_by_the_cut_is_still_redacted_in_planner_results():
    import planner_tools
    path = "src/order-service/app/big.py"
    mcp = planner_tools.build(OneFile(path, straddling_file()), Store(), "main")
    out = call(mcp, "read_repository_context", {"drill_id": "drill-x", "path": path})
    assert KEY_BODY[:20] not in json.dumps(out)
    assert out["redaction"]["applied"] and out["redaction"]["kinds"] == ["private_key"]


def test_a_key_split_by_the_cut_is_still_redacted_in_engineer_results():
    import engineer_tools
    from backends.fixtures import FixtureRepo
    path = "src/order-service/app/big.py"
    mcp = engineer_tools.build(FixtureRepo({path: straddling_file()}), Store(), "main", ())
    out = call(mcp, "read_allowed_files", {"drill_id": "drill-x", "paths": [path]})
    assert KEY_BODY[:20] not in json.dumps(out)
    assert out["redaction"]["applied"] and out["redaction"]["kinds"] == ["private_key"]


# ---------------------------------------------------------------- odd Authorization headers get 401, not 500

@pytest.mark.parametrize("value", ["Bearer café".encode("utf-8"), b"Bearer caf\xe9"])
def test_a_non_ascii_or_non_utf8_credential_gets_401(server, value):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    r = httpx.post(server["url"] + "/planner/mcp", json=body,
                   headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                            "Authorization": value})
    assert r.status_code == 401
